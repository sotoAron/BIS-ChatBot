import pytest
from app.rag.intent_router import IntentRouter, Intent

def test_intent_router_calendar_write():
    queries = [
        "Anotá el examen en mi calendario",
        "agendar tarea para mañana",
        "añadir al calendario esta entrega",
        "recordatorio del parcial"
    ]
    for q in queries:
        assert IntentRouter.classify(q) == Intent.CALENDAR_WRITE

def test_intent_router_sync():
    queries = [
        "sincronizar el plan del curso",
        "por favor leer pdf de planificación",
        "actualizar programa",
        "descargar planificación de la materia"
    ]
    for q in queries:
        assert IntentRouter.classify(q) == Intent.SYNC

def test_intent_router_grades():
    queries = [
        "cuáles son mis notas?",
        "qué calificación saqué en el parcial?",
        "notas finales del curso"
    ]
    for q in queries:
        assert IntentRouter.classify(q) == Intent.GRADES

def test_intent_router_assignments():
    queries = [
        "qué tareas tengo para esta semana?",
        "mis tareas pendientes",
        "cuándo es el vencimiento del tp?"
    ]
    for q in queries:
        assert IntentRouter.classify(q) == Intent.ASSIGNMENTS

def test_intent_router_rag_fallback():
    queries = [
        "cómo se promociona la materia?",
        "qué pasa si falto a clase?",
        "hola, cómo estás?"
    ]
    for q in queries:
        assert IntentRouter.classify(q) == Intent.RAG

def test_intent_router_hierarchy():
    # Debería priorizar CALENDAR_WRITE sobre ASSIGNMENTS
    q1 = "agendar en mi calendario el vencimiento de mis tareas"
    assert IntentRouter.classify(q1) == Intent.CALENDAR_WRITE
    
    # Debería priorizar SYNC sobre RAG
    q2 = "leer pdf del reglamento y sincronizar"
    assert IntentRouter.classify(q2) == Intent.SYNC
