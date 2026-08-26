"""
app/rag/tools.py — Sistema de Tools y Ejecución.

Contiene la lógica para ejecutar herramientas en el backend basadas en 
la intención detectada, y retornar los resultados como contexto para el LLM.
"""
import logging
import json
from typing import Any, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from app.rag.moodle_sync import sync_course_pdf
from app.services.moodle_client import get_moodle_client

logger = logging.getLogger(__name__)

class ToolExecutor:
    """
    Ejecuta acciones en Moodle y otros servicios basándose en la intención
    y los parámetros extraídos.
    """

    @classmethod
    async def resolve_course_id(cls, user_id: int, search_term: str) -> Optional[int]:
        """Busca el ID de un curso basado en una abreviatura o nombre corto."""
        client = get_moodle_client()
        try:
            courses = await client.get_user_courses(user_id)
            if not courses:
                return None
            search_term = search_term.lower()
            for c in courses:
                if search_term in c.get("shortname", "").lower() or search_term in c.get("fullname", "").lower():
                    return c.get("id")
            return None
        except Exception as e:
            logger.error("Tool Error (resolve_course_id): %s", e)
            return None


    @classmethod
    async def get_my_courses(cls, user_id: int) -> str:
        """Consulta los cursos en los que el usuario está inscripto."""
        client = get_moodle_client()
        try:
            courses = await client.get_user_courses(user_id)
            if not courses:
                return "No estás inscripto en ningún curso en este momento."
            
            result = []
            for c in courses:
                c_name = c.get("fullname")
                c_short = c.get("shortname")
                if c_name:
                    result.append(f"- {c_name} ({c_short})")
            
            if not result:
                return "No se encontraron cursos con nombre válido."
            return "Estás inscripto en los siguientes cursos:\n" + "\n".join(result)
        except Exception as e:
            logger.error("Tool Error (get_my_courses): %s", e)
            return "Ocurrió un error al consultar tus cursos en Moodle."

    @classmethod
    async def get_pending_assignments(cls, user_id: int) -> str:
        """Consulta tareas pendientes combinando mod_assign y calendario."""
        client = get_moodle_client()
        try:
            # 1. Obtener eventos de calendario
            cal_data = await client.get_calendar_events()
            events = cal_data.get("events", [])
            
            # 2. Obtener assignments puros
            assign_data = await client.get_course_assignments()
            courses_assign = assign_data.get("courses", [])
            
            if not events and not courses_assign:
                return "No tienes tareas o eventos pendientes registrados."
                
            result_set = set()
            tz = ZoneInfo("America/Argentina/Buenos_Aires")
            
            # Procesar eventos de calendario
            for event in events:
                e_name = event.get("name", "Evento")
                c_name = event.get("course", {}).get("fullname", "General")
                due = event.get("timestart", 0)
                due_date = datetime.fromtimestamp(due, tz=tz).strftime('%Y-%m-%d %H:%M') if due else "Sin fecha"
                result_set.add(f"- {c_name}: {e_name} (Fecha: {due_date})")
                
            # Procesar assignments
            for course in courses_assign:
                c_name = course.get("fullname", f"Curso {course.get('id')}")
                for assign in course.get("assignments", []):
                    a_name = assign.get("name", "Tarea")
                    due = assign.get("duedate", 0)
                    due_date = datetime.fromtimestamp(due, tz=tz).strftime('%Y-%m-%d %H:%M') if due else "Sin fecha"
                    result_set.add(f"- {c_name}: {a_name} (Fecha: {due_date})")
            
            if not result_set:
                return "No tienes tareas o eventos pendientes."
            
            # Ordenar para consistencia
            result_list = sorted(list(result_set))
            return "Tareas y eventos pendientes:\n" + "\n".join(result_list)
        except Exception as e:
            logger.error("Tool Error (get_pending_assignments): %s", e)
            return "Ocurrió un error al consultar las tareas en Moodle."

    @classmethod
    async def get_my_grades(cls, user_id: int, course_id: Optional[int] = None) -> str:
        """Consulta calificaciones del usuario. Si course_id es None, busca en todos sus cursos."""
        client = get_moodle_client()
        try:
            courses = []
            if course_id:
                courses.append({"id": course_id, "fullname": "Materia especificada"})
            else:
                courses = await client.get_user_courses(user_id)
                if not courses:
                    return "No estás inscripto en ningún curso para consultar calificaciones."
            
            result = []
            for course in courses:
                cid = course.get("id")
                cname = course.get("fullname", f"Curso {cid}")
                data = await client.get_user_grades(user_id, cid)
                
                if data and "usergrades" in data:
                    course_grades = []
                    for ugrade in data["usergrades"]:
                        for item in ugrade.get("gradeitems", []):
                            itemname = item.get("itemname")
                            grade = item.get("gradeformatted")
                            if itemname and grade and grade != "-":
                                course_grades.append(f"  - {itemname}: {grade}")
                    
                    if course_grades:
                        result.append(f"**{cname}**:")
                        result.extend(course_grades)
            
            if not result:
                return "Aún no hay calificaciones registradas para ti."
            return "Tus calificaciones en el sistema:\n" + "\n".join(result)
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
