"""
app/services/rate_limit.py — Sliding Window Rate Limiter con Redis.

ALGORITMO: Sliding Window usando Redis Sorted Sets.
  - Clave: ratelimit:{user_id}
  - Score: timestamp UNIX (float) de cada petición
  - Window: los últimos N segundos antes de "now"

OPERACIONES (pipeline atómico):
  1. ZREMRANGEBYSCORE  → eliminar entradas fuera de la ventana
  2. ZCARD            → contar peticiones vigentes
  3. ZADD             → registrar la petición actual (si se permite)
  4. EXPIRE           → TTL de la clave (window + 1 seg de margen)

COMPLEJIDAD: O(log N + M) donde M = entradas eliminadas por ciclo.
"""
import time
from dataclasses import dataclass

import redis.asyncio as aioredis


@dataclass
class RateLimitResult:
    """Resultado de una verificación de rate limit."""
    is_allowed: bool
    remaining: int       # Peticiones restantes en la ventana actual
    reset_at: float      # Timestamp UNIX cuando se reinicia la ventana


class RateLimiter:
    """
    Sliding Window Rate Limiter respaldado por Redis.

    Args:
        redis_client:    Cliente redis.asyncio (o fakeredis compatible).
        max_requests:    Máximo de peticiones permitidas por ventana.
        window_seconds:  Duración de la ventana en segundos.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        max_requests: int = 5,
        window_seconds: int = 60,
    ) -> None:
        self._redis = redis_client
        self._max = max_requests
        self._window = window_seconds

    def _key(self, user_id: int | str) -> str:
        return f"ratelimit:{user_id}"

    async def is_allowed(self, user_id: int | str) -> bool:
        """
        Verifica si el usuario puede realizar una petición ahora.

        Registra la petición si está permitida.

        Returns:
            True si la petición está dentro del límite, False si debe bloquearse.
        """
        result = await self.check(user_id)
        return result.is_allowed

    async def check(self, user_id: int | str) -> RateLimitResult:
        """
        Verificación completa con conteo, registro y metadatos.

        Returns:
            RateLimitResult con is_allowed, remaining y reset_at.
        """
        now      = time.time()
        key      = self._key(user_id)
        window_start = now - self._window
        entry    = str(now)  # Identificador único de esta petición

        async with self._redis.pipeline(transaction=True) as pipe:
            # 1. Eliminar entradas fuera de la ventana deslizante
            pipe.zremrangebyscore(key, 0, window_start)
            # 2. Contar peticiones vigentes (ANTES de añadir la actual)
            pipe.zcard(key)
            # 3. Añadir esta petición con timestamp como score
            pipe.zadd(key, {entry: now})
            # 4. Asegurar que la clave expira (evita memory leaks en Redis)
            pipe.expire(key, self._window + 1)

            results = await pipe.execute()

        current_count = results[1]  # zcard ANTES de zadd

        is_allowed = current_count < self._max
        remaining  = max(0, self._max - current_count - 1) if is_allowed else 0
        reset_at   = now + self._window

        # Si NO está permitida, deshacer el zadd (no registrar la petición bloqueada)
        if not is_allowed:
            await self._redis.zrem(key, entry)

        return RateLimitResult(
            is_allowed=is_allowed,
            remaining=remaining,
            reset_at=reset_at,
        )

    async def get_remaining(self, user_id: int | str) -> int:
        """
        Retorna cuántas peticiones le quedan al usuario en la ventana actual.
        NO registra ninguna petición.
        """
        now = time.time()
        key = self._key(user_id)
        window_start = now - self._window

        async with self._redis.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            results = await pipe.execute()

        current_count = results[1]
        return max(0, self._max - current_count)

    async def reset(self, user_id: int | str) -> None:
        """Reinicia el contador del usuario (útil para tests y administración)."""
        await self._redis.delete(self._key(user_id))
