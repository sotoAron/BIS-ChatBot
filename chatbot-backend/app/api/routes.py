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
import time
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


def _sse_done(timings: dict | None = None) -> str:
    """Evento SSE de finalización con métricas de tiempo opcionales."""
    payload = {"done": True}
    if timings:
        payload["timings"] = timings
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    cache: SemanticCache | None,
    system_prompt: str,
    history: list[dict] | None = None,
    history_manager: ConversationHistory | None = None,
    user_id: int | None = None,
    pipeline_timings: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming desde Ollama con métricas de profiling y almacenamiento en caché."""
    full_response = []
    t_llm_start = time.perf_counter()
    t_first_token: float | None = None
    token_count = 0

    try:
        async for token in ollama.stream(prompt=question, system_prompt=system_prompt, history=history):
            if t_first_token is None:
                t_first_token = time.perf_counter()
            token_count += 1
            full_response.append(token)
            yield _sse_chunk({"chunk": token, "cached": False})

        t_llm_end = time.perf_counter()
        llm_total_s = t_llm_end - t_llm_start
        ttft_s = (t_first_token - t_llm_start) if t_first_token else llm_total_s
        gen_s = (t_llm_end - t_first_token) if t_first_token else 0.0
        tok_speed = (token_count / gen_s) if gen_s > 0 else 0.0

        # Consolidar métricas de profiling del pipeline completo
        timings_summary = dict(pipeline_timings or {})
        t_global_start = timings_summary.pop("_t0", t_llm_start)
        total_pipeline_s = t_llm_end - t_global_start

        timings_summary["llm_ttft_s"] = round(ttft_s, 2)
        timings_summary["llm_gen_s"] = round(gen_s, 2)
        timings_summary["llm_tokens"] = token_count
        timings_summary["llm_speed_tok_s"] = round(tok_speed, 1)
        timings_summary["pipeline_total_s"] = round(total_pipeline_s, 2)

        # Log visual detallado del proceso y timers
        logger.info(
            "\n" + "╔" + "═" * 78 + "\n"
            f"║ ⏱️ [PROCESO DE PENSAMIENTO & TIMERS]\n"
            f"║ 👤 User ID: {user_id} | Pregunta: \"{question[:50]}...\"\n"
            "║ ────────────────────────────────────────────────────────────────────────────\n"
            f"║ 🔹 [1] Rate Limit & Auth     : {timings_summary.get('rate_limit_ms', 0):>6.1f} ms\n"
            f"║ 🔹 [2] Clasificación Intent  : {timings_summary.get('intent_ms', 0):>6.1f} ms  ➔ [{timings_summary.get('intent', 'RAG')}]\n"
            f"║       📍 Destino Enrutador   : {timings_summary.get('intent_destination', 'N/A')}\n"
            f"║ 🔹 [3] Búsqueda en Caché     : {timings_summary.get('cache_ms', 0):>6.1f} ms  ({timings_summary.get('cache_result', 'MISS')})\n"
            f"║ 🔹 [4] Carga de Historial    : {timings_summary.get('history_ms', 0):>6.1f} ms\n"
            f"║ 🔹 [5] Búsqueda RAG ChromaDB : {timings_summary.get('rag_ms', 0):>6.1f} ms  ({timings_summary.get('rag_docs_count', 0)} chunks recuperados)\n"
            f"║ 🔹 [6] LLM Prompt Eval (TTFT): {ttft_s:>6.2f} s   (Evaluación de contexto en CPU Ollama)\n"
            f"║ 🔹 [7] LLM Generación Texto  : {gen_s:>6.2f} s   ({token_count} tokens @ {tok_speed:.1f} tok/s)\n"
            "║ ────────────────────────────────────────────────────────────────────────────\n"
            f"║ 🏁 TIEMPO TOTAL DE RESPUESTA : {total_pipeline_s:>6.2f} s\n"
            "╚" + "═" * 78
        )

        yield _sse_done(timings=timings_summary)

        complete = "".join(full_response)
        
        # Guardar historial si se pasaron las dependencias
        if history_manager and user_id:
            try:
                await history_manager.add_turn(user_id, question, complete)
            except Exception as e:
                logger.warning("Error guardando historial: %s", e)

        # Guardar en caché semántica al finalizar el stream si aplica
        if full_response and cache:
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
    t0 = time.perf_counter()
    pipeline_timings: dict = {"_t0": t0}

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
    t_rl_start = time.perf_counter()
    rate_limiter = RateLimiter(
        redis_client=request.app.state.redis,
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    rl_result = await rate_limiter.check(user_id)
    pipeline_timings["rate_limit_ms"] = round((time.perf_counter() - t_rl_start) * 1000, 2)

    if not rl_result.is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Límite de peticiones superado. Reintenta en {settings.rate_limit_window_seconds}s.",
            headers={"Retry-After": str(settings.rate_limit_window_seconds)},
        )

    # ── 2. Intent Router (Mover antes de caché) ───────────────────────────────
    t_intent_start = time.perf_counter()
    intent = IntentRouter.classify(question)
    destination = IntentRouter.get_destination(intent)
    pipeline_timings["intent_ms"] = round((time.perf_counter() - t_intent_start) * 1000, 2)
    pipeline_timings["intent"] = intent.name
    pipeline_timings["intent_destination"] = destination
    logger.info("🎯 [ENRUTADOR] Intención: %s ➔ Destino: %s", intent.name, destination)

    # ── 3. Caché Semántica (Solo para RAG/preguntas generales) ────────────────
    t_cache_start = time.perf_counter()
    cache = None
    if intent == Intent.RAG:
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
        pipeline_timings["cache_ms"] = round((time.perf_counter() - t_cache_start) * 1000, 2)
        if cached_response:
            pipeline_timings["cache_result"] = "HIT"
            logger.info("Cache HIT para user_id=%s (%.2f ms)", user_id, pipeline_timings["cache_ms"])
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
        else:
            pipeline_timings["cache_result"] = "MISS"
    else:
        pipeline_timings["cache_ms"] = round((time.perf_counter() - t_cache_start) * 1000, 2)
        pipeline_timings["cache_result"] = "BYPASS"

    # ── 4. Historial Conversacional ───────────────────────────────────────────
    t_hist_start = time.perf_counter()
    history_manager = ConversationHistory(request.app.state.redis)
    history = await history_manager.get_history(user_id)
    pipeline_timings["history_ms"] = round((time.perf_counter() - t_hist_start) * 1000, 2)
    
    rag_docs: list = []
    vector_store = getattr(request.app.state, "vector_store", None)
    total_docs = vector_store.count() if vector_store else 0

    if intent == Intent.ASSIGNMENTS:
        tool_result = await ToolExecutor.get_pending_assignments(user_id)
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE TAREAS EN MOODLE]\n{tool_result}"
        generator = _stream_from_llm(
            question,
            request.app.state.ollama,
            cache,
            system_prompt=rag_system_prompt,
            history=history,
            history_manager=history_manager,
            user_id=user_id,
            pipeline_timings=pipeline_timings,
        )

    elif intent == Intent.COURSES:
        tool_result = await ToolExecutor.get_my_courses(user_id)
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE CURSOS INSCRIPTOS]\n{tool_result}"
        generator = _stream_from_llm(
            question,
            request.app.state.ollama,
            cache,
            system_prompt=rag_system_prompt,
            history=history,
            history_manager=history_manager,
            user_id=user_id,
            pipeline_timings=pipeline_timings,
        )

    elif intent == Intent.GRADES:
        courses = await request.app.state.vector_store._client if False else []
        tool_result = await ToolExecutor.get_my_grades(user_id, course_id=2)
        rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE CALIFICACIONES EN MOODLE]\n{tool_result}"
        generator = _stream_from_llm(
            question,
            request.app.state.ollama,
            cache,
            system_prompt=rag_system_prompt,
            history=history,
            history_manager=history_manager,
            user_id=user_id,
            pipeline_timings=pipeline_timings,
        )

    elif intent == Intent.SYNC:
        tool_result = await ToolExecutor.sync_course_syllabus(
            course_id=2, año=effective_año, carrera=effective_car
        )
        rag_system_prompt = (
            f"Eres el asistente académico del curso.\n"
            f"Se ejecutó una acción del sistema con el siguiente resultado:\n{tool_result}\n\n"
            f"Instrucción: Confirma al usuario de forma amigable y concisa que el documento del curso "
            f"ha sido sincronizado e indexado correctamente en la base de conocimiento y que ya puede "
            f"hacerte preguntas sobre los temas, fechas de exámenes o condiciones de la materia."
        )
        generator = _stream_from_llm(
            question,
            request.app.state.ollama,
            cache,
            system_prompt=rag_system_prompt,
            history=history,
            history_manager=history_manager,
            user_id=user_id,
            pipeline_timings=pipeline_timings,
        )

    elif intent == Intent.CALENDAR_WRITE:
        if "confirm" not in question.lower() and "si" not in question.lower() and "sí" not in question.lower():
            rag_system_prompt = (
                f"{SYSTEM_PROMPT}\n\nEl usuario quiere agendar un evento, pero debes "
                "pedirle confirmación explícita (ej. '¿Estás seguro que quieres agendar esto en tu calendario?'). "
                "No uses la herramienta de escritura todavía."
            )
        else:
            tool_result = await ToolExecutor.add_exam_to_calendar(
                user_id=user_id, course_id=2, event_name="Examen Parcial", 
                description="Agendado por el Chatbot Académico", timestamp=int(time.time() + 86400 * 7)
            )
            rag_system_prompt = f"{SYSTEM_PROMPT}\n\n[RESULTADO DE ESCRITURA EN CALENDARIO]\n{tool_result}"

        generator = _stream_from_llm(
            question,
            request.app.state.ollama,
            cache,
            system_prompt=rag_system_prompt,
            history=history,
            history_manager=history_manager,
            user_id=user_id,
            pipeline_timings=pipeline_timings,
        )

    else:
        # ── 5. RAG: recuperar contexto académico relevante (Fallback) ─────────
        t_rag_start = time.perf_counter()
        vector_store      = getattr(request.app.state, "vector_store", None)
        total_docs        = vector_store.count() if vector_store else 0
        rag_docs: list    = []

        if vector_store is not None and total_docs > 0:
            try:
                retriever = Retriever(
                    vector_store=vector_store,
                    embedder=embed_text,
                    min_score=0.20,
                    n_results=5,
                )
                
                # Contextualizar la búsqueda RAG con la última pregunta del usuario (Short-term memory)
                search_query = question
                if history:
                    last_user_msg = next((msg["content"] for msg in reversed(history) if msg["role"] == "user"), "")
                    if last_user_msg:
                        search_query = f"{last_user_msg}. {question}"

                rag_result = await retriever.retrieve_with_prompt(
                    query=search_query,
                    año_academico=effective_año,
                    carrera=effective_car,
                )
                rag_docs = rag_result.docs
                pipeline_timings["rag_ms"] = round((time.perf_counter() - t_rag_start) * 1000, 2)
                pipeline_timings["rag_docs_count"] = len(rag_docs)
                logger.info(
                    "RAG: %d docs recuperados en %.2f ms para user_id=%s "
                    "(año=%s, carrera='%s')",
                    len(rag_docs), pipeline_timings["rag_ms"], user_id, effective_año, effective_car,
                )
                logger.info("RAG CHUNKS RECUPERADOS: %s", [doc.get("metadata", {}).get("chunk_index") for doc in rag_docs])
            except Exception as rag_err:
                pipeline_timings["rag_ms"] = round((time.perf_counter() - t_rag_start) * 1000, 2)
                pipeline_timings["rag_docs_count"] = 0
                logger.warning("Error en RAG: %s", rag_err)
        else:
            pipeline_timings["rag_ms"] = 0.0
            pipeline_timings["rag_docs_count"] = 0
            logger.info(
                "RAG omitido: ChromaDB %s.",
                f"vacío ({total_docs} docs)" if vector_store else "no disponible",
            )

        # ── Anti-alucinación / Streaming LLM ──────────────────────────────────
        if not rag_docs:
            logger.info(
                "Anti-alucinación activada para user_id=%s "
                "(0 docs, carrera='%s', año=%s). No se invoca Ollama.",
                user_id, effective_car, effective_año,
            )
            generator = _stream_no_context()
        else:
            generator = _stream_from_llm(
                question,
                request.app.state.ollama,
                cache,
                system_prompt=rag_result.system_prompt,
                history=history,
                history_manager=history_manager,
                user_id=user_id,
                pipeline_timings=pipeline_timings,
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
