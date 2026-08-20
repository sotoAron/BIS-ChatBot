"""
app/api/routes.py — Endpoints del chatbot (SSE streaming + healthcheck).

ENDPOINTS:
  GET  /health          → Estado de todos los servicios (Redis, Ollama, ChromaDB)
  POST /api/chat/stream → Respuesta SSE token a token (requiere JWT válido)
  GET  /api/chat/stream → Idem para EventSource (JWT en query param ?token=)

FLUJO DE /api/chat/stream:
  1. Verificar JWT (Bearer header o ?token= query param)
  2. Verificar Rate Limit (sliding window por user_id)
  3. Buscar en Caché Semántica Redis (similitud coseno ≥ 0.92)
     → Si HIT: retornar respuesta cacheada vía SSE (sin llamar al LLM)
     → Si MISS: continuar
  4. Consultar ChromaDB para contexto RAG (Fase 3 — stub en Fase 2)
  5. Construir prompt con system prompt + contexto RAG + historial
  6. Streaming con Ollama Qwen 2.5 3B token a token
  7. Almacenar respuesta completa en caché semántica
"""
import json
import logging
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import get_current_user
from app.rag.embeddings import embed_text
from app.rag.retriever import NO_CONTEXT_MESSAGE, Retriever, build_rag_prompt
from app.rag.intent_router import IntentRouter, Intent
from app.rag.tools import ToolExecutor
from app.services.cache import SemanticCache, _make_namespace
from app.services.history import ConversationHistory
from app.services.llm import OllamaClient, OllamaConnectionError, OllamaModelError
from app.services.rate_limit import RateLimiter


logger = logging.getLogger(__name__)
router = APIRouter()

# ── System prompt base ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente académico de la Facultad. Tu rol es ayudar a
estudiantes y docentes con consultas sobre reglamentos, planes de estudio, fechas
importantes y procedimientos académicos.

Responde siempre en español, de forma clara y concisa.
Si no conoces la respuesta con certeza, indícalo honestamente.
Nunca inventes información sobre fechas, notas o reglamentos.
Basa tus respuestas únicamente en el contexto académico proporcionado."""


# ══════════════════════════════════════════════════════════════════════════════
# Modelos Pydantic
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    question:       str
    año_academico:  str = "2026"  # Año del plan de estudios (para filtro RAG)
    carrera:        str = ""      # Carrera del usuario (para filtro RAG)
    user_id:        Optional[int] = None


# ══════════════════════════════════════════════════════════════════════════════
# Dependencias
# ══════════════════════════════════════════════════════════════════════════════

async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


async def get_rate_limiter(request: Request) -> RateLimiter:
    settings = get_settings()
    return RateLimiter(
        redis_client=request.app.state.redis,
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


async def get_semantic_cache(request: Request) -> SemanticCache:
    settings = get_settings()
    return SemanticCache(
        redis_client=request.app.state.redis,
        embedder=embed_text,
        threshold=settings.semantic_cache_threshold,
        ttl=settings.semantic_cache_ttl,
    )


async def get_ollama(request: Request) -> OllamaClient:
    return request.app.state.ollama


# ══════════════════════════════════════════════════════════════════════════════
# Generadores SSE
# ══════════════════════════════════════════════════════════════════════════════

def _sse_chunk(data: dict) -> str:
    """Formatea un dict como evento SSE."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_done() -> str:
    """Evento SSE de finalización."""
    return f"data: {json.dumps({'done': True})}\n\n"


def _sse_error(message: str, code: int = 500) -> str:
    """Evento SSE de error."""
    return f"data: {json.dumps({'error': message, 'code': code})}\n\n"


async def _stream_from_cache(response: str) -> AsyncGenerator[str, None]:
    """Simula streaming para respuestas cacheadas (bloques de ~10 chars)."""
    chunk_size = 10
    for i in range(0, len(response), chunk_size):
        yield _sse_chunk({"chunk": response[i:i + chunk_size], "cached": True})
    yield _sse_done()


async def _stream_no_context() -> AsyncGenerator[str, None]:
    """
    Cláusula anti-alucinación: respuesta directa sin invocar Ollama.

    Se usa cuando ChromaDB no devuelve ningún documento relevante para el
    contexto (año + carrera) del usuario. Evita que el modelo responda
    con su conocimiento general en lugar de los documentos oficiales.
    """
    msg = (
        "No dispongo de información oficial sobre esa consulta en los reglamentos "
        "y documentos cargados para tu carrera y año académico. "
        "Te recomiendo consultar directamente con la secretaría académica "
        "o revisar el portal oficial de la facultad."
    )
    # Simular streaming natural para no romper el contrato SSE del widget
    chunk_size = 15
    for i in range(0, len(msg), chunk_size):
        yield _sse_chunk({"chunk": msg[i:i + chunk_size], "cached": False, "no_context": True})
    yield _sse_done()


async def _stream_from_llm(
    question: str,
    ollama: OllamaClient,
    cache: SemanticCache,
    system_prompt: str,
    history: list[dict] | None = None,
    history_manager: ConversationHistory | None = None,
    user_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming desde Ollama con system_prompt RAG y almacenamiento en caché al finalizar."""
    full_response = []
    try:
        async for token in ollama.stream(prompt=question, system_prompt=system_prompt, history=history):
            full_response.append(token)
            yield _sse_chunk({"chunk": token, "cached": False})

        yield _sse_done()

        complete = "".join(full_response)
        
        # Guardar historial si se pasaron las dependencias
        if history_manager and user_id:
            try:
                await history_manager.add_turn(user_id, question, complete)
            except Exception as e:
                logger.warning("Error guardando historial: %s", e)

        # Guardar en caché semántica al finalizar el stream
        if full_response:
            try:
                await cache.set(question, complete)
            except Exception as cache_err:
                logger.warning("Error guardando en caché semántica: %s", cache_err)

    except OllamaConnectionError as exc:
        logger.error("Ollama no disponible: %s", exc)
        yield _sse_error("El servicio de IA no está disponible. Inténtalo de nuevo.", 503)
    except OllamaModelError as exc:
        logger.error("Error en el modelo Ollama: %s", exc)
        yield _sse_error("Error interno del modelo de IA.", 500)
    except Exception as exc:
        logger.exception("Error inesperado en streaming LLM: %s", exc)
        yield _sse_error("Error interno del servidor.", 500)


# ══════════════════════════════════════════════════════════════════════════════
# Endpoint: GET /health
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/health", tags=["Monitoring"])
async def health_check(request: Request):
    """
    Verifica el estado de todos los servicios del backend.
    No requiere autenticación (usado por Docker healthcheck y monitoreo).
    """
    settings = get_settings()
    status_map = {}

    # Redis
    try:
        await request.app.state.redis.ping()
        status_map["redis"] = "ok"
    except Exception as exc:
        status_map["redis"] = f"error: {exc}"

    # Ollama
    try:
        ollama_ok = await request.app.state.ollama.is_available()
        status_map["ollama"] = "ok" if ollama_ok else f"model '{settings.ollama_model}' not loaded"
    except Exception as exc:
        status_map["ollama"] = f"error: {exc}"

    # ChromaDB
    try:
        vs = request.app.state.vector_store
        status_map["chromadb"] = "ok" if vs.is_available() else "unavailable"
    except Exception as exc:
        status_map["chromadb"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in status_map.values())

    return {
        "status":   "healthy" if all_ok else "degraded",
        "services": status_map,
        "model":    settings.ollama_model,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Endpoint: POST + GET /api/chat/stream
# ══════════════════════════════════════════════════════════════════════════════

async def _chat_stream_handler(
    question: str,
    user_payload: dict,
    request: Request,
    año_academico: str = "",
    carrera: str = "",
) -> StreamingResponse:
    """
    Lógica compartida entre POST y GET del endpoint de streaming.

    PIPELINE COMPLETO (Fase 3):
      1. Rate Limiting (sliding window por user_id)
      2. Caché Semántica Redis (hit → respuesta en ms sin LLM)
      3. RAG: Retriever con filtros año_academico + carrera (anti-alucinaciones)
      4. Construir system_prompt con contexto RAG recuperado
      5. Streaming Ollama Qwen 2.5 3B con system_prompt RAG
    """
    user_id  = user_payload.get("sub", 0)
    settings = get_settings()

    # ── 0. Resolver año y carrera ANTES de todo (se usan en rate limit key y cache ns) ───
    effective_año = (
        año_academico
        or user_payload.get("año_academico", "")
        or settings.default_año_academico
    )
    effective_car = (
        carrera
        or user_payload.get("carrera", "")
        or settings.default_carrera
    )
    # ── 1. Rate Limiting ──────────────────────────────────────────────────────
    rate_limiter = RateLimiter(
        redis_client=request.app.state.redis,
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    rl_result = await rate_limiter.check(user_id)

    if not rl_result.is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Límite de peticiones superado. Reintenta en {settings.rate_limit_window_seconds}s.",
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )

    # ── 2. Caché Semántica ────────────────────────────────────────────────────
    cache_ns = _make_namespace(
        año_academico=effective_año,
        carrera=effective_car,
        role=user_payload.get("role", "student"),
    )
    cache = SemanticCache(
        redis_client=request.app.state.redis,
        embedder=embed_text,
        threshold=settings.semantic_cache_threshold,
        ttl=settings.semantic_cache_ttl,
        namespace=cache_ns,
    )

    cached_response = await cache.get(question)
    if cached_response:
        logger.info("Cache HIT para user_id=%s", user_id)
        generator = _stream_from_cache(cached_response)
        
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control":               "no-cache",
                "X-Accel-Buffering":           "no",
                "X-RateLimit-Remaining":       str(rl_result.remaining),
                "Access-Control-Allow-Origin": "*",
            },
        )

    # ── 3. Historial Conversacional ───────────────────────────────────────────
    history_manager = ConversationHistory(request.app.state.redis)
    history = await history_manager.get_history(user_id)

    # ── 4. Intent Router & Tools (Fase 4) ─────────────────────────────────────
    intent = IntentRouter.classify(question)
    logger.info("Intent detectado: %s", intent.name)
    
    rag_docs: list = []
    vector_store = getattr(request.app.state, "vector_store", None)
    total_docs = vector_store.count() if vector_store else 0

    if intent == Intent.ASSIGNMENTS:
        tool_result = await ToolExecutor.get_pending_assignments(user_id)
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE TAREAS]\n{tool_result}"
        
    elif intent == Intent.GRADES:
        # En una impl. completa se deduciría el course_id del RAG o del estado, 
        # para Fase 4 asumimos un curso global (ej. ID 1) si no hay contexto.
        tool_result = await ToolExecutor.get_my_grades(user_id, course_id=1)
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE NOTAS]\n{tool_result}"
        
    elif intent == Intent.SYNC:
        tool_result = await ToolExecutor.sync_course_syllabus(
            course_id=1, año=effective_año, carrera=effective_car
        )
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[RESULTADO DE SINCRONIZACIÓN]\n{tool_result}"
        
    elif intent == Intent.CALENDAR_WRITE:
        if "confirm" not in question.lower() and "si" not in question.lower() and "sí" not in question.lower():
            # Req explícito de confirmación antes de escribir
            rag_system_prompt = (
                f"{SYSTEM_PROMPT}\n\nEl usuario quiere agendar un evento, pero debes "
                "pedirle confirmación explícita (ej. '¿Estás seguro que quieres agendar esto?'). "
                "No uses la herramienta de escritura todavía."
            )
        else:
            # Fake parsing of dates for Phase 4 stub
            import time
            tool_result = await ToolExecutor.add_exam_to_calendar(
                user_id=user_id, course_id=1, event_name="Examen Extraído", 
                description="Agendado por el Chatbot", timestamp=int(time.time() + 86400)
            )
            rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[RESULTADO DE ESCRITURA EN CALENDARIO]\n{tool_result}"
            
    else:
        # ── 5. RAG: recuperar contexto académico relevante (Fallback) ─────────
        vector_store      = getattr(request.app.state, "vector_store", None)
        total_docs        = vector_store.count() if vector_store else 0
        rag_docs: list    = []

        if vector_store is not None and total_docs > 0:
            try:
                retriever = Retriever(
                    vector_store=vector_store,
                    embedder=embed_text,
                    # Umbral bajado a 0.40: distancias coseno reales para docs
                    # relevantes con paraphrase-multilingual caen en [0.30-0.65]
                    min_score=0.40,
                    n_results=5,
                )
                rag_result = await retriever.retrieve_with_prompt(
                    query=question,
                    año_academico=effective_año,
                    carrera=effective_car,
                )
                rag_docs = rag_result.docs
                logger.info(
                    "RAG: %d docs recuperados para user_id=%s "
                    "(año=%s, carrera='%s', ns=%s)",
                    len(rag_docs), user_id, effective_año, effective_car, cache_ns,
                )
            except Exception as rag_err:
                logger.warning("Error en RAG: %s", rag_err)
        else:
            logger.info(
                "RAG omitido: ChromaDB %s.",
                f"vacío ({total_docs} docs)" if vector_store else "no disponible",
            )

        # ── 4. Anti-alucinación / Streaming LLM ──────────────────────────────
        if not rag_docs:
            # HARD STOP: sin documentos relevantes → NO llamar a Ollama.
            # El LLM respondería con su conocimiento general, que puede
            # contradecir los reglamentos oficiales de la facultad.
            logger.info(
                "Anti-alucinación activada para user_id=%s "
                "(0 docs, carrera='%s', año=%s). No se invoca Ollama.",
                user_id, effective_car, effective_año,
            )
            generator = _stream_no_context()
        else:
            # Contexto RAG o Tool disponible → streaming con prompt enriquecido
            generator = _stream_from_llm(
                question,
                request.app.state.ollama,
                cache,
                system_prompt=rag_system_prompt if intent != Intent.RAG else rag_result.system_prompt,
                history=history,
                history_manager=history_manager,
                user_id=user_id,
            )


    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",       # Nginx: deshabilitar buffer SSE
            "X-RateLimit-Remaining":       str(rl_result.remaining),
            "Access-Control-Allow-Origin": "*",
        },
    )




@router.post("/api/chat/stream", tags=["Chat"])
async def chat_stream_post(
    body: ChatRequest,
    request: Request,
    user_payload: dict = Depends(get_current_user),
):
    """
    Endpoint SSE para peticiones estándar REST con Authorization header.
    El JWT se envía en el header: Authorization: Bearer <token>
    """
    return await _chat_stream_handler(
        question=body.question,
        user_payload=user_payload,
        request=request,
        año_academico=body.año_academico,
        carrera=body.carrera,
    )


@router.get("/api/chat/stream", tags=["Chat"])
async def chat_stream_get(
    request: Request,
    question: str = Query(..., description="Pregunta del usuario"),
    token: str = Query(..., description="JWT de autenticación (para EventSource)"),
    año_academico: str = Query("2026", description="Año académico para filtro RAG"),
    carrera: str = Query("", description="Carrera para filtro RAG"),
):
    """
    Endpoint SSE para EventSource (navegador).
    El JWT se envía como query param porque EventSource no soporta headers custom.
    """
    from app.core.security import verify_token
    user_payload = verify_token(token)
    return await _chat_stream_handler(
        question=question,
        user_payload=user_payload,
        request=request,
        año_academico=año_academico,
        carrera=carrera,
    )
