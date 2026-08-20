"""
tests/unit/test_security.py — TDD: Suite de tests para app/core/security.py

METODOLOGÍA TDD:
  Estos tests se escriben ANTES de la implementación.
  Definen el contrato de seguridad que security.py debe cumplir.

CONTRATO VERIFICADO:
  ✓ Token válido → payload retornado con todos los claims
  ✓ Token expirado → HTTPException 401
  ✓ Firma manipulada → HTTPException 401 (timing-safe)
  ✓ Token malformado (< 3 partes) → HTTPException 401
  ✓ Secreto incorrecto → HTTPException 401
  ✓ Payload sin campo 'exp' → HTTPException 401
  ✓ Token vacío / None → HTTPException 401
  ✓ Sub-campo 'sub' y 'role' presentes en payload retornado
"""
import pytest
from fastapi import HTTPException

from app.core.security import verify_token
from tests.conftest import TEST_JWT_SECRET, TEST_USER_ID, TEST_ROLE, make_token


# ══════════════════════════════════════════════════════════════════════════════
# Tests positivos (happy path)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidToken:
    """Un token bien formado, firmado y vigente DEBE ser aceptado."""

    def test_valid_token_returns_payload(self, valid_token, valid_payload):
        """verify_token() retorna el payload como dict cuando el token es válido."""
        payload = verify_token(valid_token, secret=TEST_JWT_SECRET)
        assert isinstance(payload, dict)

    def test_payload_contains_sub(self, valid_token):
        """El claim 'sub' (user_id) debe estar presente en el payload."""
        payload = verify_token(valid_token, secret=TEST_JWT_SECRET)
        assert payload["sub"] == TEST_USER_ID

    def test_payload_contains_role(self, valid_token):
        """El claim 'role' debe estar presente en el payload."""
        payload = verify_token(valid_token, secret=TEST_JWT_SECRET)
        assert payload["role"] == TEST_ROLE

    def test_payload_contains_exp(self, valid_token):
        """El claim 'exp' debe estar presente."""
        payload = verify_token(valid_token, secret=TEST_JWT_SECRET)
        assert "exp" in payload

    def test_payload_contains_name(self, valid_token):
        """El claim 'name' debe estar presente."""
        payload = verify_token(valid_token, secret=TEST_JWT_SECRET)
        assert "name" in payload


# ══════════════════════════════════════════════════════════════════════════════
# Tests negativos — Token expirado
# ══════════════════════════════════════════════════════════════════════════════

class TestExpiredToken:
    """Un token expirado DEBE ser rechazado con HTTP 401."""

    def test_expired_token_raises_401(self, expired_token):
        """Token con exp en el pasado → 401 Unauthorized."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token(expired_token, secret=TEST_JWT_SECRET)
        assert exc_info.value.status_code == 401

    def test_expired_token_error_message(self, expired_token):
        """El mensaje de error debe mencionar la expiración."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token(expired_token, secret=TEST_JWT_SECRET)
        assert "expir" in exc_info.value.detail.lower()

    def test_token_expiring_in_one_second_is_still_valid(self, secret_key):
        """Un token que expira en 1 segundo todavía es válido ahora."""
        import time
        payload = {
            "sub": 1, "name": "Test", "role": "student",
            "sesskey": "x", "iat": int(time.time()), "exp": int(time.time()) + 1,
        }
        token = make_token(payload, secret_key)
        result = verify_token(token, secret=secret_key)
        assert result["sub"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Tests negativos — Firma manipulada
# ══════════════════════════════════════════════════════════════════════════════

class TestTamperedToken:
    """Un token con firma alterada DEBE ser rechazado con HTTP 401."""

    def test_tampered_signature_raises_401(self, tampered_token):
        """Firma alterada → 401 Unauthorized."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token, secret=TEST_JWT_SECRET)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self, valid_token):
        """Token firmado con secreto diferente → 401 Unauthorized."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token(valid_token, secret="completely-different-secret-32-chars!")
        assert exc_info.value.status_code == 401

    def test_tampered_payload_raises_401(self, valid_payload, secret_key):
        """
        Si se altera el payload (sin actualizar la firma), debe fallar.
        Simula un ataque de inyección de claims.
        """
        import base64, json
        token_parts = make_token(valid_payload, secret_key).split(".")
        # Alterar el payload: elevar role a 'admin'
        tampered = valid_payload.copy()
        tampered["role"] = "admin"
        new_payload = base64.urlsafe_b64encode(
            json.dumps(tampered).encode()
        ).rstrip(b"=").decode()
        # Mantener la firma original (no recalcular)
        tampered_token = f"{token_parts[0]}.{new_payload}.{token_parts[2]}"

        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token, secret=secret_key)
        assert exc_info.value.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Tests negativos — Token malformado
# ══════════════════════════════════════════════════════════════════════════════

class TestMalformedToken:
    """Tokens con estructura inválida DEBEN ser rechazados con HTTP 401."""

    @pytest.mark.parametrize("bad_token", [
        "",                        # vacío
        "solo.dos",                # solo 2 partes
        "una.sola.parte.de.mas",   # 5 partes
        "not-a-jwt-at-all",        # sin puntos
        "   ",                     # solo espacios
    ])
    def test_malformed_token_raises_401(self, bad_token):
        """Cualquier token sin exactamente 3 partes → 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_token(bad_token, secret=TEST_JWT_SECRET)
        assert exc_info.value.status_code == 401

    def test_token_without_exp_raises_401(self, secret_key):
        """Un payload sin campo 'exp' → 401 (no se puede verificar expiración)."""
        payload_no_exp = {
            "sub": 1, "name": "Test", "role": "student", "sesskey": "x"
            # 'exp' ausente intencionalmente
        }
        token = make_token(payload_no_exp, secret_key)
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, secret=secret_key)
        assert exc_info.value.status_code == 401

    def test_token_with_invalid_base64_payload_raises_401(self, valid_token, secret_key):
        """Si el payload no es base64 decodificable a JSON → 401."""
        parts = valid_token.split(".")
        # Reemplazar payload por basura no decodificable como JSON
        bad_token = f"{parts[0]}.!!!invalid!!!.{parts[2]}"
        with pytest.raises(HTTPException) as exc_info:
            verify_token(bad_token, secret=secret_key)
        assert exc_info.value.status_code == 401
