"""
app/rag/embeddings.py — Motor de Embeddings con sentence-transformers.

MODELO: paraphrase-multilingual-MiniLM-L12-v2 (o multilingual-e5-small)
  - 50 lenguajes incluyendo español
  - Dimensión: 384 (MiniLM) / 384 (e5-small)
  - Tamaño en disco: ~470 MB
  - Inferencia CPU: ~50-200ms por oración

DISEÑO:
  - Singleton: el modelo se carga UNA VEZ en el lifespan de la app.
  - Función async embed_text() para integrar con el event loop de FastAPI.
  - La carga del modelo se hace en un thread pool (to_thread) para no
    bloquear el loop de asyncio durante los ~5-10 segundos de startup.
"""
import asyncio
import logging
from functools import lru_cache
from typing import Callable

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Carga del modelo (singleton, thread-safe)
# ══════════════════════════════════════════════════════════════════════════════

_model: SentenceTransformer | None = None


def load_model(model_name: str | None = None) -> SentenceTransformer:
    """
    Carga el modelo de embeddings de forma lazy y en singleton.
    Seguro para llamar múltiples veces (retorna la misma instancia).
    """
    global _model
    if _model is None:
        name = model_name or get_settings().embedding_model
        logger.info("Cargando modelo de embeddings: %s", name)
        _model = SentenceTransformer(name)
        logger.info("Modelo de embeddings listo. Dimensión: %d", _model.get_sentence_embedding_dimension())
    return _model


async def embed_text(text: str) -> np.ndarray:
    """
    Genera el embedding de un texto de forma asíncrona.

    Usa asyncio.to_thread para ejecutar la inferencia CPU en un thread pool
    sin bloquear el event loop de FastAPI.

    Args:
        text: Texto a vectorizar.

    Returns:
        np.ndarray: Vector de embeddings (float32).
    """
    model = load_model()
    # to_thread previene que la inferencia CPU bloquee el event loop
    embedding = await asyncio.to_thread(
        model.encode,
        text,
        normalize_embeddings=True,  # Normalización L2 → similitud coseno = producto punto
        convert_to_numpy=True,
    )
    return embedding


def get_embedder() -> Callable:
    """
    Retorna la función embed_text lista para inyectar en SemanticCache.
    Compatible con el patrón de dependency injection de FastAPI.
    """
    return embed_text
