"""
tests/conftest.py — Fixtures y mocks globales para toda la suite de tests.

Provee:
  - secret_key: secreto JWT de prueba (32 chars, no real)
  - valid_payload / expired_payload: payloads de prueba
  - make_token(): helper para generar JWTs firmados en tests
  - fake_redis: instancia de fakeredis en memoria (no requiere servidor Redis)
  - app_client: AsyncClient apuntando a la app FastAPI con settings mockeados
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as aioredis_fake
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Constantes de prueba ───────────────────────────────────────────────────────
TEST_JWT_SECRET = "test-secret-key-for-unit-tests-minimum-32-chars!"
TEST_USER_ID    = 42
TEST_USERNAME   = "Ana García"
TEST_ROLE       = "student"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers de JWT (reimplementación inline para ser independientes del SUT)
# ══════════════════════════════════════════════════════════════════════════════

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def make_token(
    payload: dict[str, Any],
    secret: str = TEST_JWT_SECRET,
    tamper_signature: bool = False,
) -> str:
    """
    Genera un JWT firmado con HMAC-SHA256 idéntico al método PHP.

    Args:
        payload:          Claims del token.
        secret:           Clave de firma.
        tamper_signature: Si True, altera el último carácter de la firma.

    Returns:
        str: Compact JWT string.
    """
    header = _b64url_encode(json.dumps({"typ": "JWT", "alg": "HS256"}).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, ensure_ascii=False).encode())
    sig = _b64url_encode(
        hmac.new(secret.encode(), f"{header}.{payload_b64}".encode(), hashlib.sha256).digest()
    )
    if tamper_signature:
        sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    return f"{header}.{payload_b64}.{sig}"


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures base
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def secret_key() -> str:
    return TEST_JWT_SECRET


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    """Payload JWT válido con expiración en 15 minutos."""
    now = int(time.time())
    return {
        "sub":     TEST_USER_ID,
        "name":    TEST_USERNAME,
        "role":    TEST_ROLE,
        "sesskey": "abc123def456",
        "iat":     now,
        "exp":     now + 900,
    }


@pytest.fixture
def expired_payload() -> dict[str, Any]:
    """Payload JWT ya expirado (exp en el pasado)."""
    now = int(time.time())
    return {
        "sub":     TEST_USER_ID,
        "name":    TEST_USERNAME,
        "role":    TEST_ROLE,
        "sesskey": "abc123def456",
        "iat":     now - 1800,
        "exp":     now - 1,      # ← expirado hace 1 segundo
    }


@pytest.fixture
def valid_token(valid_payload, secret_key) -> str:
    return make_token(valid_payload, secret_key)


@pytest.fixture
def expired_token(expired_payload, secret_key) -> str:
    return make_token(expired_payload, secret_key)


@pytest.fixture
def tampered_token(valid_payload, secret_key) -> str:
    return make_token(valid_payload, secret_key, tamper_signature=True)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures Redis (fakeredis — en memoria, sin servidor)
# ══════════════════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def fake_redis():
    """
    Instancia de Redis completamente en memoria.
    Compatible con la API de redis.asyncio — no requiere servidor real.
    """
    client = aioredis_fake.FakeRedis()
    yield client
    await client.aclose()


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures FastAPI (app con settings mockeados)
# ══════════════════════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def app_client(monkeypatch):
    """
    AsyncClient apuntando a la app FastAPI con JWT_SECRET sobreescrita.
    Permite hacer requests HTTP a los endpoints sin levantar un servidor real.
    """
    # Sobreescribir la variable de entorno ANTES de importar la app
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    # Importar aquí para que Settings tome la env var del monkeypatch
    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Limpiar caché de settings para no contaminar otros tests
    get_settings.cache_clear()
