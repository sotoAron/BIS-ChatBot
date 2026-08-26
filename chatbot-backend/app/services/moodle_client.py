"""
app/services/moodle_client.py — Consultas y acciones a la API REST de Moodle.

SEGURIDAD (Principio de menor privilegio):
  - Las herramientas de lectura y sincronización usan `moodle_ws_token`.
  - La escritura (calendario) solo se permite si `CALENDAR_WRITE_ENABLED=True` y 
    requiere explícitamente `moodle_ws_token_write`.
"""
import logging
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MoodleClient:
    """
    Cliente para la API REST de Moodle.
    """

    def __init__(self, base_url: str, ws_token: str, ws_token_write: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._token = ws_token
        self._token_write = ws_token_write
        self._endpoint = f"{self._base_url}/webservice/rest/server.php"
        self._timeout = get_settings().moodle_timeout

    # ── READ: Cursos ──────────────────────────────────────────────────────────

    async def get_user_courses(self, user_id: int) -> list[dict[str, Any]]:
        """
        Retorna los cursos en los que el usuario está matriculado.
        Moodle wsfunction: core_enrol_get_users_courses
        """
        if not self._token:
            return []
            
        data = await self._call("core_enrol_get_users_courses", {"userid": user_id})
        # La API de Moodle retorna una lista de dicts
        return data if isinstance(data, list) else []

    async def get_course_contents(self, course_id: int) -> list[dict[str, Any]]:
        """
        Retorna las secciones, recursos y actividades de un curso.
        Útil para buscar PDFs de planificación.
        Moodle wsfunction: core_course_get_contents
        """
        if not self._token:
            return []
            
        data = await self._call("core_course_get_contents", {"courseid": course_id})
        return data if isinstance(data, list) else []

    # ── READ: Tareas y Notas ──────────────────────────────────────────────────

    async def get_course_assignments(self, course_id: Optional[int] = None) -> dict[str, Any]:
        """
        Retorna las tareas usando mod_assign_get_assignments.
        """
        if not self._token:
            return {}
            
        params = {}
        if course_id:
            params["courseids[0]"] = course_id
            
        return await self._call("mod_assign_get_assignments", params)

    async def get_calendar_events(self) -> dict[str, Any]:
        """
        Retorna las tareas pendientes (action events) ordenadas por fecha para el usuario actual.
        Moodle wsfunction: core_calendar_get_action_events_by_timesort
        """
        if not self._token:
            return {}
            
        import time
        params = {
            "timesortfrom": int(time.time()),  # Desde ahora
            "limitnum": 20  # Límite razonable
        }
        return await self._call("core_calendar_get_action_events_by_timesort", params)

    async def get_user_grades(self, user_id: int, course_id: int) -> dict[str, Any]:
        """
        Retorna las calificaciones del usuario para un curso.
        Moodle wsfunction: gradereport_user_get_grade_items
        """
        if not self._token:
            return {}
            
        return await self._call(
            "gradereport_user_get_grade_items", 
            {"userid": user_id, "courseid": course_id}
        )

    @property
    def _headers(self) -> dict[str, str]:
        # Para evitar que Moodle haga redirect 303 a su wwwroot local (localhost:8080)
        return {"Host": "localhost:8080"}

    # ── WRITE: Calendario ─────────────────────────────────────────────────────

    async def create_calendar_event(
        self, user_id: int, course_id: int, name: str, description: str, timestamp: int
    ) -> dict[str, Any]:
        """
        Añade un evento de usuario al calendario.
        Moodle wsfunction: core_calendar_create_calendar_events
        Requiere CALENDAR_WRITE_ENABLED = True.
        """
        settings = get_settings()
        if not settings.calendar_write_enabled:
            logger.warning("Intento de escritura en calendario rechazado (CALENDAR_WRITE_ENABLED=False)")
            return {"error": "Write operations are disabled."}
            
        if not self._token_write:
            return {"error": "Missing write token."}

        logger.info(
            "WRITE AUDIT: user_id=%s course_id=%s name='%s' ts=%s",
            user_id, course_id, name, timestamp
        )

        params = {
            "events[0][name]": name,
            "events[0][description]": description,
            "events[0][timestart]": timestamp,
            "events[0][eventtype]": "user",
            "events[0][courseid]": course_id,
        }

        # _call no soporta token override, hacemos petición directa
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.post(
                self._endpoint,
                headers=self._headers,
                data={
                    "wstoken": self._token_write,
                    "wsfunction": "core_calendar_create_calendar_events",
                    "moodlewsrestformat": "json",
                    **params,
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── HELPER: Cliente HTTP ──────────────────────────────────────────────────

    async def _call(self, function: str, params: dict) -> Any:
        """
        Realiza una llamada POST (REST API convention in Moodle) para lecturas.
        """
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.post(
                self._endpoint,
                headers=self._headers,
                data={
                    "wstoken": self._token,
                    "wsfunction": function,
                    "moodlewsrestformat": "json",
                    **params,
                },
            )
            resp.raise_for_status()
            
            data = resp.json()
            # Moodle retorna dict con 'exception' en caso de error lógico (token inválido, etc.)
            if isinstance(data, dict) and "exception" in data:
                logger.error("Moodle API Error: %s", data)
            return data

    async def download_file(self, file_url: str) -> bytes:
        """
        Descarga un archivo (PDF) de Moodle usando el token para autenticación.
        Moodle requiere que el token se pase por query: ?token=XYZ
        """
        # Reemplazar localhost:8080 con base_url si viene URL absoluta de Moodle
        url = file_url
        if url.startswith("http://localhost:8080"):
            url = url.replace("http://localhost:8080", self._base_url, 1)

        if "?" in url:
            url = f"{url}&token={self._token}"
        else:
            url = f"{url}?token={self._token}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            return resp.content


def get_moodle_client() -> MoodleClient:
    settings = get_settings()
    return MoodleClient(
        base_url=settings.moodle_base_url,
        ws_token=settings.moodle_ws_token,
        ws_token_write=settings.moodle_ws_token_write
    )
