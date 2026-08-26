"""
app/services/llm.py — Cliente Ollama para streaming con Qwen 2.5 3B.

DISEÑO:
  - Usa httpx.AsyncClient para peticiones HTTP asíncronas a la API de Ollama.
  - El endpoint /api/generate de Ollama soporta streaming JSON (newline-delimited).
  - Cada línea es un JSON con { "response": "<token>", "done": bool }.
  - Este módulo actúa como generador async: yield token a token.

SEGURIDAD:
  - El LLM NO tiene acceso directo a Moodle ni a la BD.
  - El prompt se construye en app/api/routes.py con contexto controlado.
  - Sin function calling directo al LLM — todo pasa por el backend (Fase 4).
"""
import json
import logging
import time
from typing import AsyncGenerator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OllamaClient:
    """
    Cliente async para la API de Ollama.

    Provee un generador de tokens en streaming compatible con SSE.

    Args:
        base_url:  URL base de Ollama (ej. http://ollama:11434).
        model:     Nombre del modelo Ollama (ej. qwen2.5:3b).
        timeout:   Timeout total en segundos para la respuesta completa.
    """

    GENERATE_ENDPOINT = "/api/generate"
    CHAT_ENDPOINT     = "/api/chat"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        settings      = get_settings()
        self._base_url = base_url or settings.ollama_base_url
        self._model   = model or settings.ollama_model
        self._timeout = httpx.Timeout(timeout, connect=10.0)

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        format: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Genera una respuesta en streaming, token a token.

        Usa el endpoint /api/chat con soporte para historial conversacional.

        Args:
            prompt:        Pregunta o mensaje del usuario.
            system_prompt: Instrucción de sistema (rol, contexto RAG, etc.).
            history:       Lista de turnos anteriores [{"role": ..., "content": ...}].
            temperature:   Temperatura de muestreo (0.0 = determinista).
            max_tokens:    Límite de tokens en la respuesta.
            format:        Fuerza la salida (ej. "json").

        Yields:
            str: Cada fragmento de texto generado por el modelo.

        Raises:
            OllamaConnectionError: Si Ollama no está disponible.
            OllamaModelError: Si el modelo no está cargado.
        """
        messages: list[dict] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":   self._model,
            "messages": messages,
            "stream":  True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 2048,
            },
        }
        if format:
            payload["format"] = format

        t_start = time.perf_counter()
        t_first_token: float | None = None
        token_count = 0

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}{self.CHAT_ENDPOINT}",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise OllamaModelError(
                            f"Ollama respondió con HTTP {response.status_code}: {body.decode()}"
                        )

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Ollama devolvió línea no-JSON: %s", line)
                            continue

                        # Extraer el token del campo message.content
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            if t_first_token is None:
                                t_first_token = time.perf_counter()
                                ttft = t_first_token - t_start
                                logger.info("⏱️ [LLM] Tiempo hasta el primer token (TTFT / Prompt Eval): %.2fs", ttft)
                            token_count += 1
                            yield chunk

                        if data.get("done", False):
                            t_end = time.perf_counter()
                            total_s = t_end - t_start
                            ttft_s = (t_first_token - t_start) if t_first_token else total_s
                            gen_s = (t_end - t_first_token) if t_first_token else 0.0
                            tok_per_sec = (token_count / gen_s) if gen_s > 0 else 0.0

                            # Estadísticas nativas de Ollama (en nanosegundos)
                            prompt_eval_ns = data.get("prompt_eval_duration", 0)
                            eval_ns = data.get("eval_duration", 0)
                            prompt_tokens = data.get("prompt_eval_count", 0)
                            eval_tokens = data.get("eval_count", token_count)

                            logger.info(
                                "⏱️ [LLM STATS] Total: %.2fs | TTFT (Prompt Eval): %.2fs (%d tokens) | Gen: %.2fs (%d tokens @ %.1f tok/s)",
                                total_s, ttft_s, prompt_tokens, gen_s, eval_tokens, tok_per_sec,
                            )
                            break

        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"No se puede conectar a Ollama en {self._base_url}. "
                "¿Está el servicio en ejecución?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaConnectionError(
                f"Timeout esperando respuesta de Ollama ({self._timeout.read}s)."
            ) from exc

    async def is_available(self) -> bool:
        """
        Verifica si Ollama está disponible y el modelo está cargado.

        Returns:
            True si Ollama responde correctamente, False si no.
        """
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                tags = resp.json().get("models", [])
                # Verificar que el modelo esté disponible (prefijo del nombre)
                return any(
                    tag.get("name", "").startswith(self._model.split(":")[0])
                    for tag in tags
                )
        except (httpx.ConnectError, httpx.TimeoutException):
            return False


# ══════════════════════════════════════════════════════════════════════════════
# Excepciones personalizadas
# ══════════════════════════════════════════════════════════════════════════════

class OllamaConnectionError(Exception):
    """Ollama no está disponible o no responde."""


class OllamaModelError(Exception):
    """El modelo solicitado no está cargado o devolvió un error."""


# ══════════════════════════════════════════════════════════════════════════════
# Singleton para el ciclo de vida de la app (FastAPI lifespan)
# ══════════════════════════════════════════════════════════════════════════════

_ollama_client: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    """
    Retorna la instancia singleton del cliente Ollama.
    Se inicializa en el lifespan de FastAPI (app/main.py).
    """
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client
