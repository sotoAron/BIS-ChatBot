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
    GREETING = "GREETING"
    ESCALATION = "ESCALATION"
    OOD = "OOD"
    RAG = "RAG"


class IntentRouter:
    # Orden estricto de evaluación para atajos rápidos (O(1))
    # Las intenciones complejas ahora se derivan del LLM en query_rewriter
    RULES = [
        (
            Intent.ESCALATION,
            r"\b(hablar con un humano|contacto|ayuda|secretaria|alumnado|profesor|operador|persona)\b"
        ),
        (
            Intent.GREETING,
            r"^(hola|buen dia|buen día|buenas tardes|buenas noches|buenas|saludos)\b"
        ),
    ]

    DESTINATIONS = {
        Intent.CALENDAR_WRITE: "Tool: Moodle Calendar (core_calendar_create_calendar_events)",
        Intent.SYNC: "Tool: Moodle Sync (Descarga y Vectorización de PDF en ChromaDB)",
        Intent.COURSES: "Tool: Moodle Courses (core_enrol_get_users_courses)",
        Intent.GRADES: "Tool: Moodle Grades (gradereport_user_get_grade_items)",
        Intent.ASSIGNMENTS: "Tool: Moodle Assignments (mod_assign_get_assignments)",
        Intent.GREETING: "System: Static Greeting Message",
        Intent.ESCALATION: "System: Static Escalation Message",
        Intent.OOD: "System: Static Out of Domain Message",
        Intent.RAG: "Motor RAG (Búsqueda Vectorial en ChromaDB + Inyección de Contexto)",
    }

    @classmethod
    def get_destination(cls, intent: Intent) -> str:
        """Retorna la descripción legible del destino o herramienta a la que se envía la consulta."""
        return cls.DESTINATIONS.get(intent, "Desconocido")

    @classmethod
    def classify(cls, text: str) -> Intent | None:
        """
        Clasifica atajos rápidos. Si no hace match, retorna None para que evalúe el LLM.
        """
        for intent, pattern in cls.RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return intent
        return None
