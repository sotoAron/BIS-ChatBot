"""
app/core/security.py — Verificación de JWT compatible con la implementación PHP.

DISEÑO:
  - Implementación NATIVA en Python (hmac + hashlib + base64).
    Sin librerías JWT externas para garantizar compatibilidad exacta con el
    jwt_helper.php del plugin Moodle (misma serialización base64url, mismo
    algoritmo HMAC-SHA256).
  - Timing-safe: usa hmac.compare_digest() para prevenir timing attacks.
  - Lanza HTTPException(401) para integrar directamente con FastAPI.

FLUJO DE VERIFICACIÓN:
  1. Descomponer token en header.payload.signature (3 partes).
  2. Recalcular la firma con el secreto compartido.
  3. Comparar firmas en tiempo constante (timing-safe).
  4. Decodificar payload y verificar campo 'exp'.
  5. Retornar payload validado como dict.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Any

# pyrefly: ignore [missing-import]
from fastapi import HTTPException, Security, status
# pyrefly: ignore [missing-import]
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

# Esquema de autenticación Bearer para la documentación automática de FastAPI
_bearer_scheme = HTTPBearer(auto_error=False)


# ══════════════════════════════════════════════════════════════════════════════
# Funciones de codificación Base64URL (RFC 4648 §5)
# DEBEN ser idénticas a las de jwt_helper.php
# ══════════════════════════════════════════════════════════════════════════════

def _b64url_encode(data: bytes) -> str:
    """Base64URL encode sin padding (=). Equivalente a base64url_encode() PHP."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Base64URL decode con padding restaurado. Equivalente a base64url_decode() PHP."""
    # Restaurar el padding necesario
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


# ══════════════════════════════════════════════════════════════════════════════
# Función principal de verificación
# ══════════════════════════════════════════════════════════════════════════════

def verify_token(token: str, secret: str | None = None) -> dict[str, Any]:
    """
    Verifica un JWT firmado con HMAC-SHA256 y retorna su payload decodificado.

    Compatible con la implementación PHP de jwt_helper::verify().

    Args:
        token:  Compact JWT string (header.payload.signature).
        secret: Clave de firma. Si es None, se usa get_settings().jwt_secret.

    Returns:
        dict: Payload decodificado con todos los claims del token.

    Raises:
        HTTPException(401): Token malformado, firma inválida o expirado.
    """
    if secret is None:
        secret = get_settings().jwt_secret

    # ── 1. Estructura ─────────────────────────────────────────────────────────
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token malformado: se esperan 3 partes separadas por '.'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    header_b64, payload_b64, received_sig = parts

    # ── 2. Verificación de firma (timing-safe) ────────────────────────────────
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = _b64url_encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )

    if not hmac.compare_digest(expected_sig, received_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma del token inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── 3. Decodificación del payload ─────────────────────────────────────────
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payload del token no es JSON válido.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── 4. Verificación de expiración ─────────────────────────────────────────
    exp = payload.get("exp")
    if exp is None or int(exp) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado. Recarga la página para obtener uno nuevo.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI Dependency: get_current_user
# ══════════════════════════════════════════════════════════════════════════════

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    token_param: str | None = None,  # Para SSE vía query param
) -> dict[str, Any]:
    """
    FastAPI dependency que extrae y valida el JWT.

    Soporta dos fuentes:
      1. Header 'Authorization: Bearer <token>'  (peticiones REST estándar)
      2. Query param '?token=<token>'            (SSE — EventSource no soporta headers)

    El query param tiene menor prioridad que el header.

    Returns:
        dict: Payload del JWT validado (contiene sub, name, role, exp, etc.)

    Raises:
        HTTPException(401): Si ningún token es proporcionado o el token es inválido.
    """
    token: str | None = None

    if credentials and credentials.credentials:
        token = credentials.credentials
    elif token_param:
        token = token_param

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó token de autenticación.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_token(token)
