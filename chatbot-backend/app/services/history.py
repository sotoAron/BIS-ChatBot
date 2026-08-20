"""
app/services/history.py — Historial Conversacional en Redis.

Mantiene los últimos N turnos de conversación de un usuario.
El LLM utiliza este contexto para respuestas dependientes del turno anterior.
"""
import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ConversationHistory:
    """
    Gestiona el historial de chat de los usuarios en Redis.
    """

    PREFIX = "history:user:"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        settings = get_settings()
        self._max_turns = settings.history_max_turns
        self._ttl = settings.history_ttl

    async def get_history(self, user_id: int) -> list[dict[str, str]]:
        """
        Retorna el historial del usuario como lista de mensajes
        compatibles con Ollama: [{"role": "user", "content": "..."}]
        """
        key = f"{self.PREFIX}{user_id}"
        raw_list = await self._redis.lrange(key, 0, -1)
        history = []
        for raw in raw_list:
            try:
                msg = json.loads(raw)
                history.append(msg)
            except json.JSONDecodeError:
                continue
        return history

    async def add_turn(self, user_id: int, user_message: str, assistant_response: str) -> None:
        """
        Agrega un turno (user + assistant) al historial y mantiene el límite.
        """
        key = f"{self.PREFIX}{user_id}"
        
        turn = [
            json.dumps({"role": "user", "content": user_message}),
            json.dumps({"role": "assistant", "content": assistant_response})
        ]
        
        async with self._redis.pipeline() as pipe:
            # Añadir mensajes a la lista
            pipe.rpush(key, *turn)
            # Recortar la lista para mantener max_turns * 2 (por par user/assistant)
            pipe.ltrim(key, -(self._max_turns * 2), -1)
            # Renovar TTL
            if self._ttl > 0:
                pipe.expire(key, self._ttl)
            await pipe.execute()

    async def clear(self, user_id: int) -> None:
        """Limpia el historial de un usuario."""
        await self._redis.delete(f"{self.PREFIX}{user_id}")
