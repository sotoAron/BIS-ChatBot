"""
app/core/config.py — Configuración centralizada con Pydantic Settings.

Todas las variables se leen desde el entorno (o archivo .env).
Las claves sensibles (JWT_SECRET) NUNCA tienen valores por defecto seguros;
se exige que estén definidas explícitamente.
"""
from functools import lru_cache
# pyrefly: ignore [missing-import]
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Seguridad JWT ─────────────────────────────────────────────────────────
    # En producción DEBE estar definida en .env o variable de entorno.
    # El valor por defecto permite arrancar localmente para tests y /docs,
    # pero es INSEGURO y no debe usarse en producción.
    jwt_secret: str = "dev-only-insecure-secret-change-in-production"

    # ── Servicios de infraestructura ──────────────────────────────────────────
    redis_url: str = "redis://redis:6379"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:3b"
    chroma_host: str = "chromadb"
    chroma_port: int = 8000

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # ── Rate Limiting (Sliding Window por user_id) ────────────────────────────
    rate_limit_requests: int = 5        # Máx peticiones por ventana
    rate_limit_window_seconds: int = 60  # Duración de la ventana en segundos

    # ── Caché Semántica ───────────────────────────────────────────────────────
    semantic_cache_threshold: float = 0.92   # Similitud coseno mínima para cache hit
    semantic_cache_ttl: int = 3600           # TTL en segundos (0 = sin expiración)

    # ── Entorno ───────────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"

    # ── RAG: valores por defecto para filtros de metadatos ─────────────────────────────
    # Usados como fallback cuando el widget/JWT no envían carrera/año.
    # Definir en .env para la facultad: DEFAULT_CARRERA="Ingeniería Informática"
    default_año_academico: str = "2026"
    default_carrera: str = ""   # Vacío = sin filtro de carrera (busca en todas)

    # ── Moodle REST API (Fase 4) ────────────────────────────────────────────────────
    moodle_base_url: str = "http://moodle:80"
    # Token de solo lectura — obligatorio para las tools de lectura.
    # Vacío = Moodle tools deshabilitado (el chatbot responde normalmente sin tools).
    moodle_ws_token: str = ""
    # Token separado con permiso de escritura (solo calendar).
    # Puede ser el mismo que moodle_ws_token si el servicio tiene ambos permisos.
    moodle_ws_token_write: str = ""
    # Feature flag de escritura: CALENDAR_WRITE_ENABLED=false (default).
    # Habilitar solo después de validar todas las tools de lectura.
    calendar_write_enabled: bool = False
    # Timeout para llamadas HTTP a Moodle (en segundos)
    moodle_timeout: float = 10.0

    # ── Historial Conversacional Redis (Fase 4) ───────────────────────────────────────
    history_max_turns: int = 5      # Últimos N turnos a conservar por usuario
    history_ttl: int = 3600         # TTL de la lista en Redis (segundos)

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retorna la instancia singleton de Settings.
    Usar como dependency: settings = Depends(get_settings).
    """
    return Settings()
