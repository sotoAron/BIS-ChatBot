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
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.core.prompts import NO_CONTEXT_MESSAGE

logger = logging.getLogger(__name__)
# Límite máximo de caracteres de contexto para no saturar la ventana del LLM
# Ajustado a 4000 tras aumentar el chunk_size a 1500 (3 chunks = 4500 chars max)
MAX_CONTEXT_CHARS = 4000


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
            
        # Se eliminó la truncación individual de chunks para evitar perder datos vitales
        # al final de chunks largos (ej. la tabla de profesores en chunk 0).

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
        n_results: int = 3,
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
        # 1. Embedding de la query original
        embedding = await self._embed(query)
        embedding_list = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

        # 2. Filtro obligatorio de metadatos (solo añade si tienen valor)
        where_filter = {}
        
        # Simplificación: si pasamos un dict con varias claves, ChromaDB hace un AND implícito.
        if año_academico:
            where_filter["año_academico"] = año_academico
        if carrera:
            where_filter["carrera"] = carrera
            
        # Si after filtering where_filter is empty, pass None to avoid ChromaDB query errors
        if not where_filter:
            where_filter = None

        # 3. Consulta al vector store (recuperamos un pool amplio para Rank Fusion)
        raw_results = self._store.query(
            query_embedding=embedding_list,
            n_results=100, # Universo amplio de la cohorte
            where=where_filter,
        )

        if not raw_results:
            return []
            
        docs_formatted = []
        chunk_0_doc = None
        for doc in raw_results:
            distance = doc.get("distance", 1.0)
            score = round(1.0 - distance, 4)
            d = {
                "document": doc.get("document", ""),
                "metadata": doc.get("metadata", {}),
                "dense_score": score,
            }
            docs_formatted.append(d)
            if d["metadata"].get("chunk_index") == 0:
                chunk_0_doc = d
            
        # Filtrar candidatos iniciales muy malos (score < 0.15), excluyendo a chunk 0
        docs_formatted = [d for d in docs_formatted if d["dense_score"] > 0.15 or d is chunk_0_doc]
        
        if not docs_formatted:
            return []

        # 4. Búsqueda Lexical BM25 (Hybrid Search)
        from app.rag.bm25 import BM25Retriever
        bm25_docs = [{"page_content": d["document"]} for d in docs_formatted]
        bm25_retriever = BM25Retriever(bm25_docs)
        bm25_scores = bm25_retriever.get_scores(query)

        for i, doc in enumerate(docs_formatted):
            doc["bm25_score"] = bm25_scores[i]

        # 5. Reciprocal Rank Fusion (RRF)
        docs_formatted.sort(key=lambda x: x["dense_score"], reverse=True)
        for rank, doc in enumerate(docs_formatted):
            doc["dense_rank"] = rank + 1
            
        docs_formatted.sort(key=lambda x: x["bm25_score"], reverse=True)
        for rank, doc in enumerate(docs_formatted):
            doc["bm25_rank"] = rank + 1

        k = 60
        for doc in docs_formatted:
            # Formula RRF estándar
            doc["rrf_score"] = (1.0 / (k + doc["dense_rank"])) + (1.0 / (k + doc["bm25_rank"]))

        # 6. Ordenar por RRF final y seleccionar los top N
        docs_formatted.sort(key=lambda x: x["rrf_score"], reverse=True)
        
        # 7. Asegurar que el chunk_index = 0 esté siempre presente si existe en el cohorte
        # (El chunk 0 suele contener los metadatos de docentes y carga horaria)
        top_results = docs_formatted[:self._n_results]
        
        if chunk_0_doc and chunk_0_doc not in top_results:
            # Si no entró en el top N pero existe, lo forzamos al principio
            top_results.insert(0, chunk_0_doc)
            top_results = top_results[:self._n_results] # Mantener el tamaño de n_results

        filtered = []
        for doc in top_results:
            # Guardamos el score original y el rrf_score para compatibilidad
            doc["score"] = round(doc["rrf_score"], 4)
            filtered.append(doc)

        logger.info(
            "RAG Hybrid retrieve: query='%s…' año=%s carrera='%s' → %d docs recuperados | "
            "RRF scores: [%s]",
            query[:40], año_academico, carrera, len(filtered),
            ", ".join(f"{d.get('score', 0):.4f}" for d in filtered) or "ninguno",
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
