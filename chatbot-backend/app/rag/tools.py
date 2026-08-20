"""
app/rag/tools.py — Sistema de Tools y Ejecución.

Contiene la lógica para ejecutar herramientas en el backend basadas en 
la intención detectada, y retornar los resultados como contexto para el LLM.
"""
import logging
import json
from typing import Any, Optional

from app.rag.moodle_sync import sync_course_pdf
from app.services.moodle_client import get_moodle_client

logger = logging.getLogger(__name__)

class ToolExecutor:
    """
    Ejecuta acciones en Moodle y otros servicios basándose en la intención
    y los parámetros extraídos.
    """

    @classmethod
    async def get_pending_assignments(cls, user_id: int) -> str:
        """Consulta tareas pendientes del usuario."""
        client = get_moodle_client()
        try:
            data = await client.get_course_assignments()
            if not data or "courses" not in data:
                return "No se encontraron tareas pendientes."
                
            result = []
            for course in data["courses"]:
                c_name = course.get("fullname", f"Curso {course.get('id')}")
                for assign in course.get("assignments", []):
                    a_name = assign.get("name", "Tarea")
                    due = assign.get("duedate", 0)
                    result.append(f"- {c_name}: {a_name} (Vence timestamp: {due})")
            
            if not result:
                return "No tienes tareas pendientes."
            return "Tareas pendientes:\n" + "\n".join(result)
        except Exception as e:
            logger.error("Tool Error (get_pending_assignments): %s", e)
            return "Ocurrió un error al consultar las tareas en Moodle."

    @classmethod
    async def get_my_grades(cls, user_id: int, course_id: int) -> str:
        """Consulta calificaciones del usuario en un curso."""
        client = get_moodle_client()
        try:
            data = await client.get_user_grades(user_id, course_id)
            if not data or "usergrades" not in data:
                return "No se encontraron calificaciones."
            
            result = []
            for ugrade in data["usergrades"]:
                for item in ugrade.get("gradeitems", []):
                    itemname = item.get("itemname")
                    grade = item.get("gradeformatted")
                    if itemname and grade and grade != "-":
                        result.append(f"- {itemname}: {grade}")
            
            if not result:
                return "Aún no hay calificaciones registradas para este curso."
            return "Tus calificaciones:\n" + "\n".join(result)
        except Exception as e:
            logger.error("Tool Error (get_my_grades): %s", e)
            return "Ocurrió un error al consultar las calificaciones en Moodle."

    @classmethod
    async def sync_course_syllabus(cls, course_id: int, año: str, carrera: str) -> str:
        """Busca el PDF de planificación del curso y lo sincroniza con ChromaDB."""
        client = get_moodle_client()
        try:
            contents = await client.get_course_contents(course_id)
            pdf_url = None
            pdf_name = None
            
            # Buscar el primer archivo PDF en los recursos del curso
            for section in contents:
                for module in section.get("modules", []):
                    if module.get("modname") == "resource":
                        for content in module.get("contents", []):
                            if content.get("mimetype") == "application/pdf":
                                pdf_url = content.get("fileurl")
                                pdf_name = content.get("filename", "documento.pdf")
                                break
                    if pdf_url:
                        break
                if pdf_url:
                    break
                    
            if not pdf_url:
                return "No se encontró ningún PDF de planificación en los recursos del curso."
                
            chunks = await sync_course_pdf(course_id, pdf_url, pdf_name, año, carrera)
            return f"Sincronización exitosa: se indexaron {chunks} fragmentos del archivo {pdf_name}."
        except Exception as e:
            logger.error("Tool Error (sync_course_syllabus): %s", e)
            return "Ocurrió un error al intentar sincronizar el PDF desde Moodle."

    @classmethod
    async def add_exam_to_calendar(
        cls, user_id: int, course_id: int, event_name: str, description: str, timestamp: int
    ) -> str:
        """Añade un evento al calendario del usuario."""
        client = get_moodle_client()
        try:
            result = await client.create_calendar_event(
                user_id=user_id,
                course_id=course_id,
                name=event_name,
                description=description,
                timestamp=timestamp,
            )
            if "error" in result:
                return f"No se pudo agendar el evento: {result['error']}"
            return "El evento ha sido agendado exitosamente en tu calendario de Moodle."
        except Exception as e:
            logger.error("Tool Error (add_exam_to_calendar): %s", e)
            return "Ocurrió un error al intentar agendar el evento en Moodle."
