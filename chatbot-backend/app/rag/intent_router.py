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
            Intent.GRADES,
            r"\b(mis notas|calificaciones|nota|calificación|qué me saqué|aprobé)\b"
        ),
        (
            Intent.ASSIGNMENTS,
            r"\b(mis tareas|tareas|entrega|vencimiento|pendientes|trabajo práctico)\b"
        ),
    ]

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
