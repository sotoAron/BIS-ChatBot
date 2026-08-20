Feature: Chatbot Tool Calling y Acciones de Moodle
  Como alumno
  Quiero que el chatbot pueda leer información personalizada de Moodle y escribir en mi calendario
  Para poder gestionar mi cursada desde el chat sin navegar por Moodle

  Scenario: Alumno consulta tareas pendientes
    Given un alumno con token JWT válido de Moodle
    When el alumno pregunta "qué tareas tengo pendientes?"
    Then el backend clasifica la intención como "ASSIGNMENTS"
    And el chatbot ejecuta la herramienta "get_pending_assignments"
    And la respuesta contiene información sobre la tarea "Trabajo Práctico 1"

  Scenario: Alumno pide agregar examen al calendario sin confirmar
    Given un alumno con token JWT válido de Moodle
    When el alumno pregunta "anotar el parcial en el calendario"
    Then el backend clasifica la intención como "CALENDAR_WRITE"
    And la respuesta del chatbot pide confirmación para agendar el evento

  Scenario: Alumno de Medicina pregunta reglamento de Informática
    Given un alumno con carrera "Medicina"
    When el alumno pregunta "cómo se promociona la materia?"
    Then el backend clasifica la intención como "RAG"
    And la base de conocimiento no retorna documentos (anti-alucinación)
    And la respuesta contiene el mensaje "No dispongo de información"
