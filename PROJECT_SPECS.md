# ROL Y OBJETIVO DEL PROYECTO
Actúa como un Desarrollador Full-Stack Senior y Especialista en Inteligencia Artificial Local, Arquitecturas de Moodle y Testing Automatizado (TDD/BDD).
Tu objetivo es desarrollar un Chatbot Asistente Académico local para una facultad (~2000 usuarios potenciales) con costo de infraestructura de **$0 USD mensuales**.
El sistema debe estar integrado de forma nativa en Moodle mediante un plugin local y conectarse con un backend en Python (FastAPI) desacoplado, seguro y cubierto por pruebas automatizadas.

---

## 1. ESPECIFICACIÓN DEL STACK TECNOLÓGICO ($0 USD / LOCAL)
- **Modelo LLM Local:** `Qwen 2.5 3B (Instruct)` ejecutándose vía **Ollama**.
- **Backend API:** **Python (FastAPI)** con streaming en tiempo real vía **Server-Sent Events (SSE)**.
- **Testing:** `pytest`, `pytest-asyncio`, `pytest-bdd` / `behave`.
- **Motor de Embeddings:** `sentence-transformers` en memoria local (`paraphrase-multilingual-MiniLM-L12-v2` o `multilingual-e5-small`).
- **Base de Datos Vectorial (RAG):** **ChromaDB** local/embebido con soporte para filtrado estricto por metadatos.
- **Capa de Control y Memoria:** **Redis** local para:
  1. *Rate Limiting:* Sliding Window por `user_id` (ej. máx 5 peticiones/minuto).
  2. *Caché Semántica:* Búsqueda por similitud vectorial (≥ 92%) sobre preguntas previas en Redis para responder en milisegundos sin invocar a Ollama.
  3. *Historial Conversacional:* Últimos 5 turnos de conversación por usuario.
- **Frontend / LMS:** **Moodle 4.x** (Plugin local PHP + Interfaz en Vanilla JS / CSS nativo de Moodle Boost).

---

## 2. METODOLOGÍA DE DESARROLLO Y TESTING (TDD & BDD)
El proyecto debe desarrollarse siguiendo una disciplina estricta de pruebas:

1. **TDD (Test-Driven Development) para Lógica Determinista y Seguridad:**
   - **Autenticación JWT:** Tests unitarios para validar firma HMAC-SHA256, expiración y rechazo inmediato de tokens manipulados (`401 Unauthorized`).
   - **Rate Limiting:** Tests para verificar bloqueo con `HTTP 429` al exceder el límite de peticiones por minuto.
   - **Caché Semántica:** Tests con mocks para validar que ante una similitud ≥ 0.92, Redis devuelve la respuesta y la función de llamada a Ollama recibe exactamente 0 invocaciones.
   - **Filtros RAG:** Tests para comprobar que el filtrado por metadatos (`año_academico`, `carrera`) excluye estrictamente documentos obsoletos.
   - **Moodle Web Service:** Pruebas para garantizar que las llamadas a la API de Moodle sean exclusivamente de solo lectura (Read-Only).

---

## 3. ARQUITECTURA RAG AVANZADO Y SEGURIDAD
- **Chunking Estructurado:** Segmentación de PDFs respetando encabezados, artículos de normativas y solapamiento (*overlap*).
- **Seguridad:** Aislamiento total del LLM respecto al código o BD de Moodle (patrón Tool/Function Calling estrictamente controlado por el backend).

---

## 4. ESTRUCTURA DEL PROYECTO ESPERADA
```text
moodle-local/
├── moodle_codigo/local/ia_chatbot/   # Plugin Moodle (PHP, JS, CSS)
chatbot-backend/
├── app/
│   ├── api/routes.py                 # Endpoints SSE y chat
│   ├── core/
│   │   ├── config.py                 # Variables de entorno
│   │   └── security.py               # Validación y firma JWT
│   ├── rag/
│   │   ├── embeddings.py             # sentence-transformers
│   │   ├── vectorstore.py            # ChromaDB + Metadatos
│   │   └── ingest.py                 # Ingesta de PDFs
│   ├── services/
│   │   ├── llm.py                    # Cliente Ollama (Qwen 2.5 3B)
│   │   ├── cache.py                  # Caché Semántica con Redis
│   │   ├── rate_limit.py             # Middleware / servicio de rate limit
│   │   └── moodle_tools.py           # Funciones de consulta a Moodle REST
│   └── main.py
├── tests/                            # Suite completa de tests
│   ├── conftest.py                   # Fixtures y mocks
│   ├── unit/                         # Tests unitarios TDD (JWT, Rate Limit, Cache)
│   ├── integration/                  # Tests de endpoints y RAG
│   └── features/                     # Escenarios BDD en Gherkin (roles Alumno/Profesor)
├── Dockerfile
├── requirements.txt
└── docker-compose.yml                # Redis + ChromaDB + Backend

##5. PLAN DE EJECUCIÓN PASO A PASO
Avanzaremos por fases incrementales. Por favor, NO generes todo el código de una sola vez:

Fase 1 (Plugin Moodle): Generar los archivos del plugin local de Moodle (local/ia_chatbot): version.php, lib.php, generación segura del JWT y la inyección del widget flotante (HTML/CSS/JS con SSE).

Fase 2 (Infraestructura Backend & TDD Inicial): Crear el entorno FastAPI con Docker Compose y escribir primero las pruebas unitarias (tests/unit/test_security.py y test_rate_limit.py) antes de implementar el código de JWT y Rate Limiting.

Fase 3 (RAG Avanzado & Embeddings): Tests y desarrollo del pipeline de vectorización con sentence-transformers, ChromaDB y filtros por metadatos.

Fase 4 (Caché Semántica, BDD & Inferencia Ollama): Tests de caché semántica en Redis, escenarios BDD para roles y conexión final con Qwen 2.5 3B.
