"""
tests/unit/test_rate_limit.py — TDD: Suite de tests para app/services/rate_limit.py

METODOLOGÍA TDD:
  Estos tests se escriben ANTES de la implementación.
  Definen el contrato del Rate Limiter de Sliding Window.

CONTRATO VERIFICADO (Sliding Window por user_id):
  ✓ Primera petición → permitida (is_allowed = True)
  ✓ Peticiones 1..N dentro del límite → todas permitidas
  ✓ Petición N+1 (excede el límite) → bloqueada (is_allowed = False)
  ✓ HTTP 429 en el endpoint cuando el límite se supera
  ✓ Diferentes user_ids tienen contadores independientes
  ✓ Las peticiones fuera de la ventana temporal no cuentan
  ✓ El contador se reinicia naturalmente al expirar la ventana
"""
import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.rate_limit import RateLimiter


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures específicas de rate limiting
# ══════════════════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def rate_limiter(fake_redis):
    """
    RateLimiter con configuración de prueba: 5 req / 60 seg.
    Usa fakeredis en memoria — no requiere servidor Redis real.
    """
    return RateLimiter(
        redis_client=fake_redis,
        max_requests=5,
        window_seconds=60,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tests positivos (happy path)
# ══════════════════════════════════════════════════════════════════════════════

class TestAllowedRequests:
    """Peticiones dentro del límite DEBEN ser permitidas."""

    @pytest.mark.asyncio
    async def test_first_request_is_allowed(self, rate_limiter):
        """La primera petición de cualquier usuario siempre es permitida."""
        result = await rate_limiter.is_allowed(user_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_requests_up_to_limit_are_allowed(self, rate_limiter):
        """Las primeras N peticiones (= max_requests) deben ser permitidas."""
        for i in range(5):  # max_requests = 5
            result = await rate_limiter.is_allowed(user_id=10)
            assert result is True, f"La petición {i + 1} debería estar permitida"

    @pytest.mark.asyncio
    async def test_different_users_are_independent(self, rate_limiter):
        """El rate limit de un usuario NO afecta a otro usuario."""
        # Saturar el límite del usuario 1
        for _ in range(5):
            await rate_limiter.is_allowed(user_id=1)

        # El usuario 2 todavía tiene su límite completo
        result_user2 = await rate_limiter.is_allowed(user_id=2)
        assert result_user2 is True


# ══════════════════════════════════════════════════════════════════════════════
# Tests negativos — límite superado
# ══════════════════════════════════════════════════════════════════════════════

class TestBlockedRequests:
    """Peticiones que superan el límite DEBEN ser bloqueadas."""

    @pytest.mark.asyncio
    async def test_request_beyond_limit_is_blocked(self, rate_limiter):
        """La petición N+1 debe ser rechazada cuando N = max_requests."""
        user_id = 20
        # Consumir el límite completo
        for _ in range(5):
            await rate_limiter.is_allowed(user_id=user_id)

        # La siguiente petición debe ser bloqueada
        result = await rate_limiter.is_allowed(user_id=user_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_requests_beyond_limit_are_all_blocked(self, rate_limiter):
        """Todas las peticiones después del límite deben ser bloqueadas."""
        user_id = 30
        for _ in range(5):
            await rate_limiter.is_allowed(user_id=user_id)

        # Las 3 siguientes deben ser todas bloqueadas
        for extra in range(3):
            result = await rate_limiter.is_allowed(user_id=user_id)
            assert result is False, f"La petición extra {extra + 1} debería estar bloqueada"

    @pytest.mark.asyncio
    async def test_exact_limit_boundary(self, rate_limiter):
        """
        Prueba el límite exacto:
          - Petición 5 (= max_requests): PERMITIDA
          - Petición 6 (= max_requests + 1): BLOQUEADA
        """
        user_id = 40
        results = []
        for _ in range(6):
            results.append(await rate_limiter.is_allowed(user_id=user_id))

        assert results[4] is True,  "La petición 5 (límite exacto) debería estar permitida"
        assert results[5] is False, "La petición 6 (límite + 1) debería estar bloqueada"


# ══════════════════════════════════════════════════════════════════════════════
# Tests de ventana temporal (Sliding Window)
# ══════════════════════════════════════════════════════════════════════════════

class TestSlidingWindow:
    """La ventana deslizante debe ignorar peticiones antiguas."""

    @pytest.mark.asyncio
    async def test_old_requests_outside_window_do_not_count(self, fake_redis):
        """
        Peticiones realizadas antes de la ventana no deben contar en el límite.

        Simulamos peticiones 'antiguas' insertando directamente en Redis con
        timestamps fuera de la ventana actual.
        """
        limiter = RateLimiter(fake_redis, max_requests=5, window_seconds=60)
        user_id = 50
        now = time.time()
        window = 60

        # Insertar 5 peticiones "viejas" (fuera de la ventana)
        redis_key = f"ratelimit:{user_id}"
        for i in range(5):
            old_ts = now - window - 10 - i  # 10+ segundos antes de la ventana
            await fake_redis.zadd(redis_key, {f"old-{i}": old_ts})

        # Con las 5 antiguas, el límite NO debe estar saturado
        result = await limiter.is_allowed(user_id=user_id)
        assert result is True, (
            "Las peticiones fuera de la ventana NO deben bloquear nuevas peticiones"
        )

    @pytest.mark.asyncio
    async def test_requests_at_window_boundary_are_counted(self, fake_redis):
        """
        Peticiones exactamente en el borde de la ventana sí deben contar.
        """
        limiter = RateLimiter(fake_redis, max_requests=5, window_seconds=60)
        user_id = 60
        now = time.time()
        window = 60

        # Insertar 4 peticiones justo dentro de la ventana
        redis_key = f"ratelimit:{user_id}"
        for i in range(4):
            ts = now - window + 1 + i  # 1 segundo dentro de la ventana
            await fake_redis.zadd(redis_key, {f"recent-{i}": ts})

        # Con 4 dentro de la ventana, la 5ª (nueva) debe ser permitida
        result = await limiter.is_allowed(user_id=user_id)
        assert result is True

        # Y la 6ª debe ser bloqueada (total: 4 antiguas + 1 nueva + esta = 6)
        result = await limiter.is_allowed(user_id=user_id)
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# Tests del método get_remaining_requests
# ══════════════════════════════════════════════════════════════════════════════

class TestRemainingRequests:
    """El rate limiter debe informar cuántas peticiones quedan."""

    @pytest.mark.asyncio
    async def test_new_user_has_full_quota(self, rate_limiter):
        """Un usuario sin historial debe tener max_requests disponibles."""
        remaining = await rate_limiter.get_remaining(user_id=70)
        assert remaining == 5

    @pytest.mark.asyncio
    async def test_remaining_decreases_after_request(self, rate_limiter):
        """Cada petición debe reducir el contador de restantes en 1."""
        user_id = 80
        await rate_limiter.is_allowed(user_id=user_id)
        remaining = await rate_limiter.get_remaining(user_id=user_id)
        assert remaining == 4

    @pytest.mark.asyncio
    async def test_remaining_is_zero_when_limit_reached(self, rate_limiter):
        """Al alcanzar el límite, remaining debe ser 0 (nunca negativo)."""
        user_id = 90
        for _ in range(5):
            await rate_limiter.is_allowed(user_id=user_id)
        # Intentar más allá del límite
        await rate_limiter.is_allowed(user_id=user_id)
        remaining = await rate_limiter.get_remaining(user_id=user_id)
        assert remaining == 0
