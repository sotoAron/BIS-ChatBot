"""
app/services/cache.py — Caché Semántica con Redis.

DISEÑO:
  Almacena pares (pregunta → respuesta) con sus embeddings vectoriales en Redis.
  En cada consulta, calcula la similitud coseno entre la nueva pregunta y las
  preguntas cacheadas. Si alguna supera el umbral (default: 0.92), retorna
  la respuesta almacenada sin invocar al LLM → respuesta en milisegundos.

NAMESPACE:
  Cada entrada se aísla por namespace = hash(año_academico + carrera + role).
  Esto garantiza que la misma pregunta hecha para distintas carreras/años/roles
  NO comparta caché, evitando que una respuesta para "Medicina 2026" reaparezca
  como hit de caché para "Informática 2026".

ESTRUCTURA DE DATOS EN REDIS:
  - Hash semcache:entry:{namespace}:{id}:
      question    → texto de la pregunta original
      response    → respuesta del LLM
      embedding   → vector JSON (lista de floats)
      created_at  → timestamp UNIX
  - Set  semcache:index:{namespace}  → conjunto de IDs activos en ese namespace
  - TTL aplicado a cada entry según semantic_cache_ttl

COMPLEJIDAD DE BÚSQUEDA: O(N) donde N = entradas en caché del namespace.
  Para ~2000 usuarios con historial moderado, esto es aceptable sin Redis Stack.
  En Fase 4 se puede migrar a RedisSearch/VSS si el N crece.
"""
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional

import numpy as np
# pyrefly: ignore [missing-import]
import redis.asyncio as aioredis  # type: ignore

logger = logging.getLogger(__name__)


def _make_namespace(año_academico: str, carrera: str, role: str, materia_id: Optional[str] = None) -> str:
    """
    Genera un namespace corto (8 hex chars) a partir del contexto del usuario.

    El namespace aísla la caché por (año_academico, carrera, role, materia_id), de modo que
    la misma pregunta para distintas carreras o materias nunca produce un cache hit cruzado.
    """
    materia_str = materia_id.strip().lower() if materia_id else "none"
    raw = f"{año_academico}|{carrera.strip().lower()}|{role.strip().lower()}|{materia_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class SemanticCache:
    """
    Caché semántica que evita llamadas al LLM para preguntas similares.

    Args:
        redis_client:  Cliente redis.asyncio.
        embedder:      Función async que recibe texto y retorna np.ndarray.
        threshold:     Similitud coseno mínima para considerar un cache hit (0-1).
        ttl:           TTL de las entradas en segundos. 0 = sin expiración.
        namespace:     Identificador de contexto (año + carrera + role).
                       Usar _make_namespace() para construirlo.
    """

    ENTRY_PREFIX = "semcache:entry:"
    INDEX_PREFIX = "semcache:index:"

    def __init__(
        self,
        redis_client: Any,          # redis.asyncio.Redis — type: ignore a nivel de import
        embedder,
        threshold: float = 0.92,
        ttl: int = 3600,
        namespace: str = "default",
    ) -> None:
        self._redis     = redis_client
        self._embedder  = embedder
        self._threshold = threshold
        self._ttl       = ttl
        self._ns        = namespace
        self._index_key = f"{self.INDEX_PREFIX}{namespace}"

    # ══════════════════════════════════════════════════════════════════════════
    # API pública
    # ══════════════════════════════════════════════════════════════════════════

    async def get(self, question: str) -> Optional[str]:
        """
        Busca una respuesta cacheada semánticamente similar a la pregunta
        dentro del namespace de este contexto (año + carrera + role).

        Returns:
            La respuesta cacheada si la similitud ≥ threshold, o None.
        """
        query_embedding = await self._embed(question)
        entry_ids       = await self._redis.smembers(self._index_key)

        best_score   = -1.0
        best_response: Optional[str] = None

        for entry_id_bytes in entry_ids:
            entry_id = entry_id_bytes.decode() if isinstance(entry_id_bytes, bytes) else entry_id_bytes
            entry    = await self._redis.hgetall(f"{self.ENTRY_PREFIX}{self._ns}:{entry_id}")

            if not entry:
                # Entrada expirada — limpiar el índice
                await self._redis.srem(self._index_key, entry_id)
                continue

            try:
                cached_embedding = np.array(
                    json.loads(entry.get(b"embedding", entry.get("embedding", "[]")))
                )
                similarity = self._cosine_similarity(query_embedding, cached_embedding)

                if similarity > best_score:
                    best_score    = similarity
                    raw_response  = entry.get(b"response", entry.get("response", b""))
                    best_response = raw_response.decode() if isinstance(raw_response, bytes) else raw_response

            except (json.JSONDecodeError, ValueError):
                # Entrada corrupta — ignorar
                continue

        if best_score >= self._threshold and best_response:
            logger.debug("Cache HIT (ns=%s, score=%.4f)", self._ns, best_score)
            return best_response

        return None

    async def set(self, question: str, response: str) -> str:
        """
        Almacena un par (pregunta, respuesta) en la caché semántica del namespace.

        Returns:
            El ID de la entrada creada.
        """
        embedding   = await self._embed(question)
        entry_id    = str(uuid.uuid4())
        entry_key   = f"{self.ENTRY_PREFIX}{self._ns}:{entry_id}"

        entry_data = {
            "question":   question,
            "response":   response,
            "embedding":  json.dumps(embedding.tolist()),
            "created_at": str(time.time()),
            "namespace":  self._ns,
        }

        async with self._redis.pipeline() as pipe:
            pipe.hset(entry_key, mapping=entry_data)
            if self._ttl > 0:
                pipe.expire(entry_key, self._ttl)
            pipe.sadd(self._index_key, entry_id)
            if self._ttl > 0:
                # Refrescar TTL del índice también para evitar sets huérfanos
                pipe.expire(self._index_key, self._ttl * 2)
            await pipe.execute()

        return entry_id

    async def clear(self, all_namespaces: bool = False) -> int:
        """
        Elimina entradas de la caché.

        Args:
            all_namespaces: Si True, borra toda la caché (todas las claves semcache:*).
                            Si False (default), borra solo el namespace actual.

        Returns:
            Número de entradas borradas.
        """
        if all_namespaces:
            # Buscar y borrar todas las claves del índice
            keys = await self._redis.keys("semcache:index:*")
            deleted = 0
            for idx_key in keys:
                idx_key_str = idx_key.decode() if isinstance(idx_key, bytes) else idx_key
                entry_ids = await self._redis.smembers(idx_key_str)
                ns = idx_key_str.replace(self.INDEX_PREFIX, "")
                for eid_bytes in entry_ids:
                    eid = eid_bytes.decode() if isinstance(eid_bytes, bytes) else eid_bytes
                    await self._redis.delete(f"{self.ENTRY_PREFIX}{ns}:{eid}")
                    deleted += 1
                await self._redis.delete(idx_key_str)
            return deleted
        else:
            entry_ids = await self._redis.smembers(self._index_key)
            deleted = 0
            for entry_id_bytes in entry_ids:
                entry_id = entry_id_bytes.decode() if isinstance(entry_id_bytes, bytes) else entry_id_bytes
                await self._redis.delete(f"{self.ENTRY_PREFIX}{self._ns}:{entry_id}")
                deleted += 1
            await self._redis.delete(self._index_key)
            return deleted

    # ══════════════════════════════════════════════════════════════════════════
    # Métodos privados
    # ══════════════════════════════════════════════════════════════════════════

    async def _embed(self, text: str) -> np.ndarray:
        """Genera el embedding del texto usando el embedder inyectado."""
        return await self._embedder(text)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        Similitud coseno entre dos vectores.
        Retorna 0.0 si algún vector es nulo para evitar división por cero.
        """
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
