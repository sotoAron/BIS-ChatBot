"""
app/main.py — FastAPI application factory y lifespan.

LIFESPAN:
  Al arrancar: inicializa Redis, Ollama client, Vector Store y modelo de embeddings.
  Al apagar:   cierra las conexiones limpiamente.

Todos los recursos se guardan en app.state para compartirlos entre requests
sin crear nuevas conexiones en cada petición.
"""
import logging
import sys
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.ingest_routes import admin_router
from app.core.config import get_settings
from app.rag.embeddings import load_model
from app.rag.vectorstore import VectorStore
from app.services.llm import OllamaClient

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Lifespan (startup + shutdown)
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Contexto de vida de la aplicación.
    yield → aplicación en ejecución.
    """
    settings = get_settings()
    logger.info("Iniciando IA Chatbot Backend [env=%s]", settings.environment)

    # ── Startup ───────────────────────────────────────────────────────────────

    # 1. Redis
    logger.info("Conectando a Redis: %s", settings.redis_url)
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=False,
    )
    await app.state.redis.ping()
    logger.info("Redis conectado ✓")

    # 2. Modelo de embeddings (carga CPU — puede tardar ~10s en el primer inicio)
    logger.info("Cargando modelo de embeddings: %s", settings.embedding_model)
    load_model(settings.embedding_model)
    logger.info("Modelo de embeddings listo ✓")

    # 3. Ollama client
    app.state.ollama = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )
    logger.info("Cliente Ollama configurado (modelo: %s) ✓", settings.ollama_model)

    # 4. ChromaDB Vector Store
    try:
        app.state.vector_store = VectorStore(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        logger.info("ChromaDB conectado ✓ (docs: %d)", app.state.vector_store.count())
    except Exception as exc:
        logger.warning("ChromaDB no disponible en startup: %s (RAG deshabilitado)", exc)
        app.state.vector_store = None

    logger.info("Backend IA Chatbot listo para recibir peticiones.")

    yield  # ── La aplicación está en ejecución ──────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Apagando backend...")
    await app.state.redis.aclose()
    logger.info("Redis desconectado ✓")
    logger.info("Backend detenido.")


# ══════════════════════════════════════════════════════════════════════════════
# Aplicación FastAPI
# ══════════════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="IA Academic Chatbot API",
        description=(
            "Backend del asistente académico con IA local. "
            "Streaming SSE + JWT Auth + Rate Limiting + Semantic Cache."
        ),
        version="1.0.0-alpha",
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
        lifespan=lifespan,
    )

    # ── CORS Middleware nativo y robusto ──────────────────────────────────────
    @app.middleware("http")
    async def cors_handler(request: Request, call_next):
        origin = request.headers.get("origin", "*")
        if request.method == "OPTIONS":
            from fastapi.responses import Response
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin if origin != "*" else "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Credentials": "true",
                },
            )
        response = await call_next(request)
        allow_origin = origin if origin else "*"
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Rutas ─────────────────────────────────────────────────────────────────
    app.include_router(router)
    app.include_router(admin_router)

    return app


# Instancia exportada (usada por uvicorn y los tests)
app = create_app()
