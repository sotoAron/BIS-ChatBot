"""
app/rag/intent_router.py — Clasificador de intenciones O(1).

Usa un clasificador basado en expresiones regulares y palabras clave
para detectar la intención del usuario de forma inmediata y determinista,
sin depender del LLM ni añadir latencia de inferencia.

JERARQUÍA ESTRICTA:
1. CALENDAR_WRITE: Prioridad máxima. Si dice "agendar tarea", debe ir a calendario.
2. SYNC: Acción de sistema.
3. GRADES: Consulta de notas.
4. ASSIGNMENTS: Consulta de tareas.
5. RAG: Búsqueda general (fallback).
"""
import re
from enum import Enum


class Intent(str, Enum):
    CALENDAR_WRITE = "CALENDAR_WRITE"
    SYNC = "SYNC"
    COURSES = "COURSES"
    GRADES = "GRADES"
    ASSIGNMENTS = "ASSIGNMENTS"
    RAG = "RAG"


class IntentRouter:
    # Orden estricto de evaluación (del mayor impacto al menor)
    # Se usa re.IGNORECASE por defecto.
    RULES = [
        (
            Intent.CALENDAR_WRITE,
            r"\b(agendar|agenda|añadir al calendario|agregar al calendario|anotar|anota|anotá|al calendario|en mi calendario|recordatorio)\b"
        ),
        (
            Intent.SYNC,
            r"\b(sincronizar|sincroniza|sincronización|leer pdf|cargar pdf|descargar planificación|actualizar programa)\b"
        ),
        (
            Intent.COURSES,
            r"\b(mis cursos|qué cursos|estoy inscripto|estoy matriculado|materias|qué materias)\b"
        ),
        (
            Intent.GRADES,
            r"\b(mis notas|calificaciones|nota|calificación|qué me saqué|aprobé)\b"
        ),
        (
            Intent.ASSIGNMENTS,
            r"\b(mis tareas|tareas|entrega|vencimiento|pendientes|trabajo práctico)\b"
        ),
    ]

    DESTINATIONS = {
        Intent.CALENDAR_WRITE: "Tool: Moodle Calendar (core_calendar_create_calendar_events)",
        Intent.SYNC: "Tool: Moodle Sync (Descarga y Vectorización de PDF en ChromaDB)",
        Intent.COURSES: "Tool: Moodle Courses (core_enrol_get_users_courses)",
        Intent.GRADES: "Tool: Moodle Grades (gradereport_user_get_grade_items)",
        Intent.ASSIGNMENTS: "Tool: Moodle Assignments (mod_assign_get_assignments)",
        Intent.RAG: "Motor RAG (Búsqueda Vectorial en ChromaDB + Inyección de Contexto)",
    }

    @classmethod
    def get_destination(cls, intent: Intent) -> str:
        """Retorna la descripción legible del destino o herramienta a la que se envía la consulta."""
        return cls.DESTINATIONS.get(intent, "Desconocido")

    @classmethod
    def classify(cls, text: str) -> Intent:
        """
        Clasifica el texto en una intención basada en jerarquía estricta.
        Retorna Intent.RAG si no hace match con nada (fallback).
        """
        for intent, pattern in cls.RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return intent
        return Intent.RAG
