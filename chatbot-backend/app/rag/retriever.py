"""
app/rag/retriever.py — Retriever semántico con filtros estrictos por metadatos.

RESPONSABILIDADES:
  1. Embeber la query del usuario.
  2. Consultar ChromaDB con filtros obligatorios (año_academico + carrera).
  3. Filtrar resultados por umbral mínimo de similitud (min_score).
  4. Construir el system prompt integrando el contexto RAG recuperado.

ANTI-ALUCINACIONES:
  - Si no hay contexto suficiente (docs vacíos o bajo umbral), se inyecta
    NO_CONTEXT_MESSAGE en el prompt para que el LLM declare explícitamente
    que no tiene información en lugar de inventarla.

FILTRADO ESTRICTO (spec § 2 & § 3):
  Todas las consultas pasan los filtros:
    where={"año_academico": <año>, "carrera": <carrera>}
  Esto garantiza aislamiento completo entre cohortes y planes de estudio.
"""
import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Constante de sistema — mensaje cuando no hay contexto RAG ─────────────────
NO_CONTEXT_MESSAGE = (
    "No tengo información específica sobre esto en los documentos académicos disponibles. "
    "Te recomiendo consultar directamente con la secretaría académica o revisar el portal "
    "oficial de la facultad."
)

# Límite máximo de caracteres de contexto para no saturar la ventana del LLM
# Qwen 2.5 3B: ~4096 tokens ≈ 16000 caracteres
MAX_CONTEXT_CHARS = 6000


# ══════════════════════════════════════════════════════════════════════════════
# Función pública: build_rag_prompt
# ══════════════════════════════════════════════════════════════════════════════

def build_rag_prompt(docs: list[dict[str, Any]], base_system_prompt: str = "") -> str:
    """
    Construye el system prompt del LLM integrando el contexto RAG recuperado.

    Si no hay documentos (lista vacía), el prompt incluye NO_CONTEXT_MESSAGE
    para que el modelo declare explícitamente que no tiene información.

    Args:
        docs:              Lista de resultados del Retriever.
                           Cada elemento: {"document": str, "metadata": dict, "distance": float}
        base_system_prompt: System prompt base a prefijar (opcional).

    Returns:
        str: System prompt completo con contexto RAG inyectado.
    """
    base = base_system_prompt or (
        "Eres un asistente académico de la Facultad. Responde siempre en español, "
        "de forma clara y concisa. Basa tus respuestas ÚNICAMENTE en el contexto "
        "académico proporcionado a continuación."
    )

    if not docs:
        return f"{base}\n\n{NO_CONTEXT_MESSAGE}"

    # Construir el bloque de contexto con numeración y fuente
    context_parts = []
    total_chars = 0

    for i, doc in enumerate(docs, start=1):
        text     = doc.get("document", "").strip()
        metadata = doc.get("metadata", {})
        source   = metadata.get("source", "documento")
        module   = metadata.get("module", "")

        if not text:
            continue

        # Etiquetar con fuente para trazabilidad
        label   = f"[{i}] {source}" + (f" — {module}" if module else "")
        entry   = f"DOCUMENTO {label}:\n{text}"

        # Respetar el límite de contexto
        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            # Truncar el último fragmento si es necesario
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 100:  # Solo añadir si queda espacio significativo
                context_parts.append(entry[:remaining] + "…")
            break

        context_parts.append(entry)
        total_chars += len(entry) + 1

    if not context_parts:
        return f"{base}\n\n{NO_CONTEXT_MESSAGE}"

    context_block = "\n\n---\n\n".join(context_parts)

    return (
        f"{base}\n\n"
        f"═══ CONTEXTO ACADÉMICO RECUPERADO ═══\n\n"
        f"{context_block}\n\n"
        f"═══════════════════════════════════\n\n"
        f"Responde basándote ÚNICAMENTE en el contexto anterior. "
        f"Si la información no está en el contexto, indica explícitamente que no tienes esa información."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Retriever
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetrieverResult:
    """Resultado de una búsqueda del retriever."""
    docs:         list[dict[str, Any]]   # Documentos recuperados (filtrados)
    system_prompt: str                    # System prompt con contexto RAG inyectado
    cache_hit:    bool = False            # True si vino de la caché semántica


class Retriever:
    """
    Retriever semántico con filtros de metadatos y umbral de similitud.

    Args:
        vector_store: Instancia de VectorStore (ChromaDB wrapper).
        embedder:     Función async(text: str) → np.ndarray | list[float].
        min_score:    Similitud coseno mínima para incluir un documento.
                      ChromaDB con cosine space devuelve distancias en [0, 2].
                      score = 1.0 - distance  (0.0 = opuesto, 1.0 = idéntico)
                      Valores típicos para documentos relevantes: 0.3 – 0.7.
                      Default conservador: 0.40 (excluye solo docs muy irrelevantes).
        n_results:    Número máximo de documentos a recuperar de ChromaDB.
    """

    def __init__(
        self,
        vector_store,
        embedder: Callable,
        min_score: float = 0.40,   # Bajado de 0.70: distancias coseno reales son altas
        n_results: int = 5,
        base_system_prompt: str = "",
    ) -> None:
        self._store        = vector_store
        self._embedder     = embedder
        self._min_score    = min_score
        self._n_results    = n_results
        self._base_prompt  = base_system_prompt

    async def retrieve(
        self,
        query: str,
        año_academico: str,
        carrera: str,
    ) -> list[dict[str, Any]]:
        """
        Recupera documentos relevantes para la query con filtros estrictos.

        El filtro where={año_academico, carrera} garantiza que el LLM solo
        reciba información del año y carrera correctos (aislamiento total).

        Args:
            query:         Pregunta del usuario.
            año_academico: Año del plan de estudios del usuario.
            carrera:       Carrera del usuario.

        Returns:
            Lista de documentos filtrados por similitud ≥ min_score.
            Lista vacía si no hay resultados relevantes.
        """
        # 1. Embedding de la query
        embedding = await self._embed(query)
        embedding_list = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

        # 2. Filtro obligatorio de metadatos
        where_filter = {
            "año_academico": año_academico,
            "carrera":       carrera,
        }

        # 3. Consulta al vector store
        raw_results = self._store.query(
            query_embedding=embedding_list,
            n_results=self._n_results,
            where=where_filter,
        )

        # 4. Filtrar por umbral mínimo de similitud
        # ChromaDB con hnsw:space=cosine devuelve DISTANCIAS en [0, 2]:
        #   distancia 0.0 = vectores idénticos
        #   distancia 1.0 = vectores ortogonales (sin relación)
        #   distancia 2.0 = vectores opuestos
        # Conversión: score = 1.0 - distance  → rango [-1.0, 1.0]
        # Para embeddings normalizados (paraphrase-multilingual), las distancias
        # de documentos relevantes suelen caer en [0.30, 0.65] → score [0.35, 0.70]
        filtered = []
        for doc in raw_results:
            distance = doc.get("distance", 1.0)
            score    = round(1.0 - distance, 4)
            logger.debug(
                "RAG candidate: score=%.4f (distance=%.4f) | source='%s' | text='%s…'",
                score, distance,
                doc.get("metadata", {}).get("source", "?"),
                doc.get("document", "")[:60],
            )
            if score >= self._min_score:
                filtered.append({**doc, "score": score})

        logger.info(
            "RAG retrieve: query='%s…' año=%s carrera='%s' → %d/%d docs sobre umbral %.2f | "
            "scores: [%s]",
            query[:40], año_academico, carrera, len(filtered), len(raw_results), self._min_score,
            ", ".join(f"{d.get('score', 0):.3f}" for d in filtered) or "ninguno",
        )

        return filtered

    async def retrieve_with_prompt(
        self,
        query: str,
        año_academico: str,
        carrera: str,
    ) -> RetrieverResult:
        """
        Recupera documentos y construye el system prompt RAG en un solo paso.

        Convenience method para usar directamente en los endpoints SSE.

        Returns:
            RetrieverResult con docs filtrados y system_prompt listo para el LLM.
        """
        docs = await self.retrieve(query, año_academico, carrera)
        prompt = build_rag_prompt(docs, self._base_prompt)
        return RetrieverResult(docs=docs, system_prompt=prompt)

    async def _embed(self, text: str):
        """Genera embedding respetando si el embedder es sync o async."""
        if inspect.iscoroutinefunction(self._embedder):
            return await self._embedder(text)
        return await asyncio.to_thread(self._embedder, text)


# ══════════════════════════════════════════════════════════════════════════════
# Singleton para la app
# ══════════════════════════════════════════════════════════════════════════════

_retriever: Retriever | None = None


def get_retriever(vector_store=None, embedder=None) -> Retriever:
    """
    Retorna la instancia singleton del Retriever.
    Se inicializa en el lifespan de FastAPI (main.py).
    """
    global _retriever
    if _retriever is None:
        from app.rag.embeddings import embed_text
        from app.rag.vectorstore import get_vector_store
        _retriever = Retriever(
            vector_store=vector_store or get_vector_store(),
            embedder=embedder or embed_text,
        )
    return _retriever
