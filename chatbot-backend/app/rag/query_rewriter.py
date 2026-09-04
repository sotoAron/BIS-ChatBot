"""
app/rag/query_rewriter.py — Contextualizador de Consultas.

Toma la consulta actual del usuario y el historial de la conversación,
y utiliza un LLM rápido para reescribir la consulta de forma que sea
autocontenida. Esto resuelve pronombres (ej: "y él?"), elipsis (ej: "y los parciales?")
y referencias cruzadas, permitiendo que la búsqueda RAG y BM25 funcione correctamente.
"""
import logging
from typing import List, Dict, Any
from datetime import datetime

from app.services.llm import get_ollama_client

logger = logging.getLogger(__name__)

# Prompt base para reescribir consultas y clasificar intención
def get_rewrite_system_prompt() -> str:
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"Eres un asistente especializado en NLP para un chatbot académico de la UTN. "
        f"HOY ES: {current_date}. Usa esta fecha como referencia ESTRICTA para calcular días relativos como 'mañana', 'próximo martes', etc.\n"
        "Tu tarea es doble:\n"
        "1. Reescribir la consulta del usuario para que sea independiente y autocontenida, resolviendo pronombres y referencias usando el historial. "
        "REGLA CRÍTICA: Si el usuario cambia de tema, NO le heredes la intención de mensajes anteriores. Usa el historial SOLO para desambiguar pronombres o recuperar nombres de materias.\n"
        "REGLA CRÍTICA 2: Si el usuario menciona 'unidad', 'módulo', 'tp', 'clase', 'recuperatorio' o pregunta por 'temas', ES OBLIGATORIO inyectar en la consulta el nombre de la materia de la que se estaba hablando en el historial (ej: 'cuándo se da la unidad 5 de AACSW?').\n"
        "2. Clasificar la intención de la consulta en una de las siguientes categorías:\n"
        "   - CALENDAR_WRITE: SOLO si el usuario EXPLÍCITAMENTE pide 'agendar', 'anotar', o 'agregar' al calendario. No aplica si solo pregunta fechas.\n"
        "   - GRADES: Si el usuario pregunta por sus notas, calificaciones o promedio.\n"
        "   - ASSIGNMENTS: Si el usuario pregunta por sus tareas, entregas pendientes o vencimientos.\n"
        "   - COURSES: ÚNICAMENTE si el usuario pregunta '¿en qué materias estoy inscripto?' o '¿cuáles son mis cursos?'. Si el usuario pregunta por 'unidades', 'módulos', 'temas' o fechas de clases, ES RAG, NUNCA COURSES.\n"
        "   - OOD: Si la pregunta NO ES ACADÉMICA (chistes, clima, deportes, política, recetas, etc.) o está completamente fuera de dominio.\n"
        "   - EXAMS: Si el usuario pregunta por fechas de exámenes, parciales o evaluaciones de una materia.\n"
        "   - RAG: Cualquier otra consulta académica sobre reglamentos, plan de estudio, nivel de la materia, programa de la materia, contenidos, o nombres de profesores.\n\n"
        "SINÓNIMOS Y REGLAS:\n"
        "- 'parcial' = examen sumativo/formativo\n"
        "- 'regularizar' = aprobacion de cursada\n"
        "- 'promocionar' = aprobación directa\n"
        "- Preguntar 'qué profesores están', 'quién da la clase', 'cuándo son los exámenes' -> Intent RAG, NO es COURSES ni CALENDAR_WRITE.\n\n"
        "FORMATO DE SALIDA ESTRICTO EN JSON:\n"
        "Debes devolver ÚNICAMENTE un objeto JSON con las claves 'rewritten_query', 'intent' y opcionalmente 'calendar_entities' (solo si es CALENDAR_WRITE, conteniendo 'materia', 'fecha' (YYYY-MM-DD HH:MM), y 'titulo').\n"
        "Ejemplos de interacciones:\n"
        "Usuario: \"qué tareas tengo pendientes?\"\n"
        "Salida: {\"rewritten_query\": \"¿Qué tareas tengo pendientes?\", \"intent\": \"ASSIGNMENTS\"}\n\n"
        "Usuario: \"en que materias estoy inscripto?\"\n"
        "Salida: {\"rewritten_query\": \"¿En qué materias estoy inscripto?\", \"intent\": \"COURSES\"}\n\n"
        "Historial: Assistant: \"¿Quieres que agende una entrega para mañana?\"\n"
        "Usuario: \"cuando son los examenes??\"\n"
        "Salida: {\"rewritten_query\": \"¿Cuándo son los exámenes? Evaluación Sumativa Formativa\", \"intent\": \"EXAMS\"}\n\n"
        "Usuario: \"que profesores estan en aacsw??\"\n"
        "Salida: {\"rewritten_query\": \"¿Qué profesores están en la materia AACSW?\", \"intent\": \"RAG\"}\n\n"
        "Historial: Assistant: \"¿Quieres que agende una entrega para mañana?\"\n"
        "Usuario: \"si de aacsw\"\n"
        "Salida: {\"rewritten_query\": \"Sí, quiero que agendes una entrega para mañana de la materia AACSW.\", \"intent\": \"CALENDAR_WRITE\", \"calendar_entities\": {\"materia\": \"AACSW\", \"fecha\": \"(Aquí debes calcular la fecha de mañana basada en la fecha actual)\", \"titulo\": \"Entrega\"}}\n"
    )

async def rewrite_query(current_query: str, history: List[Dict[str, str]]) -> tuple[str, str, dict]:
    """
    Reescribe la consulta actual si hay historial, para hacerla autocontenida, y clasifica su intención.
    
    Returns:
        tuple: (Consulta reescrita, Intent detectado, Entidades de calendario)
    """
    recent_history = history[-4:] if history else []
    history_text = "\n".join([f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}" for msg in recent_history])
    
    prompt = (
        f"{get_rewrite_system_prompt()}\n\n"
        f"--- Historial Reciente ---\n"
        f"{history_text}\n"
        f"--------------------------\n\n"
        f"Consulta actual: {current_query}\n"
    )
    
    try:
        import json
        llm = get_ollama_client()
        
        response_chunks = []
        async for chunk in llm.stream(
            prompt=prompt,
            system_prompt="", 
            history=None,
            max_tokens=150,
            temperature=0.0,
            format="json"
        ):
            response_chunks.append(chunk)
            
        result_text = "".join(response_chunks).strip()
        
        if not result_text:
            return current_query, "RAG", {}
            
        import re
        # Remover bloque markdown si el LLM lo devolvió
        result_text = re.sub(r'^```(?:json)?\s*', '', result_text)
        result_text = re.sub(r'\s*```$', '', result_text).strip()
            
        data = json.loads(result_text)
        rewritten = data.get("rewritten_query", current_query)
        intent = data.get("intent", "RAG").upper()
        calendar_entities = data.get("calendar_entities", {})
        
        valid_intents = ["CALENDAR_WRITE", "GRADES", "ASSIGNMENTS", "COURSES", "OOD", "RAG", "EXAMS"]
        if intent not in valid_intents:
            intent = "RAG"
            
        # Post-procesamiento determinista para corregir errores del LLM pequeño
        programa_keywords = ["programa", "contenido", "unidad", "temario", "syllabus", "planificación", "modulo", "módulo", "tema", "clase"]
        if intent == "COURSES" and any(kw in rewritten.lower() for kw in programa_keywords):
            intent = "RAG"

        # Normalizar acrónimos conocidos para matching semántico y léxico
        rewritten = re.sub(r'\baacsw\b', 'Aspectos Avanzados de Calidad de Software', rewritten, flags=re.IGNORECASE)

        # Refuerzo determinista para búsquedas BM25/Vectorial de exámenes
        if intent == "EXAMS":
            if "sumativa" not in rewritten.lower() and "formativa" not in rewritten.lower():
                rewritten = f"{rewritten} Cronograma Evaluación Sumativa Evaluación Formativa Coloquio Recuperatorio fechas"
        
        # Refuerzo para consultas sobre el programa o contenidos de la materia
        programa_keywords = ["programa", "contenido", "unidad", "temario", "syllabus", "planificación"]
        if intent == "RAG" and any(kw in rewritten.lower() for kw in programa_keywords):
            if "fundamentación" not in rewritten.lower():
                rewritten = f"{rewritten} Unidad temática fundamentación contenidos objetivos"
            
        logger.info("Query & Intent: '%s' -> '%s' [%s]", current_query, rewritten, intent)
        return rewritten, intent, calendar_entities
        
    except Exception as e:
        logger.error(f"Error al reescribir query, usando original: {e}")
        return current_query, "RAG", {}
