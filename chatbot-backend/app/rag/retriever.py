"""
app/rag/retriever.py — Retriever semántico con filtros estrictos por metadatos.

Actualizado para la arquitectura de Chunking Estructural (Fase 4).
"""
import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.core.prompts import NO_CONTEXT_MESSAGE
from app.rag.catalog import get_catalog

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 4000



def build_rag_prompt(docs: list[dict[str, Any]], base_system_prompt: str = "", max_context_chars: int = 10000) -> str:
    """Construye el system prompt integrando el contexto RAG recuperado."""
    base = base_system_prompt or (
        "Eres un asistente académico de la Facultad. Responde siempre en español, "
        "de forma clara y concisa. Basa tus respuestas ÚNICAMENTE en el contexto "
        "académico proporcionado a continuación."
    )

    if not docs:
        return f"{base}\n\n{NO_CONTEXT_MESSAGE}"

    # ── Flujo normal (no exámenes pre-parseados, todo se pasa al LLM) ─────────────────
    context_parts = []
    total_chars = 0

    for i, doc in enumerate(docs, start=1):
        text     = doc.get("document", "").strip()
        metadata = doc.get("metadata", {})
        source   = metadata.get("source", "documento")
        doc_type = metadata.get("document_type", "documento")
        seccion  = metadata.get("seccion", "")

        if not text:
            continue

        label = f"[{i}] {source} ({doc_type})"
        if seccion:
            label += f" - {seccion}"

        entry = f"DOCUMENTO {label}:\n{text}"

        if total_chars + len(entry) > max_context_chars:
            remaining = max_context_chars - total_chars
            if remaining > 100:
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
        f"Responde a la consulta del usuario basándote estrictamente en el contexto anterior."
    )


@dataclass
class RetrieverResult:
    docs: list[dict[str, Any]]
    system_prompt: str
    cache_hit: bool = False


class Retriever:
    """Retriever semántico con filtros de metadatos estructurales."""

    def __init__(
        self,
        vector_store,
        embedder: Callable,
        min_score: float = 0.20,
        n_results: int = 15,
        base_system_prompt: str = "",
        max_context_chars: int = 10000,
        **kwargs: Any,
    ) -> None:
        self._store = vector_store
        self._embedder = embedder
        self._min_score = min_score
        self._n_results = n_results
        self._base_prompt = base_system_prompt
        self._max_context_chars = max_context_chars

    async def retrieve(
        self,
        query: str,
        año_academico: str,
        carrera: str,
        secciones: list[str] | None = None,
        materia_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recupera documentos usando la nueva metadata estructural."""
        embedding = await self._embed(query)
        embedding_list = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

        catalog = get_catalog()
        carrera_id = catalog.normalize_carrera(carrera)
        
        # Filtro básico por ciclo lectivo
        ciclo = 2026
        if año_academico and año_academico.isdigit():
            ciclo = int(año_academico)
            
        where_filter = {"ciclo_lectivo": ciclo}
        
        if secciones:
            # Filtro estricto por sección si se solicita (hard filtering)
            if len(secciones) == 1:
                where_filter["seccion"] = secciones[0]
            else:
                where_filter["seccion"] = {"$in": secciones}

        if materia_id:
            where_filter["materia_id"] = materia_id
        raw_results = self._store.query(
            query_embedding=embedding_list,
            n_results=100, 
            where=where_filter,
        )

        if not raw_results:
            return []
            
        docs_formatted = []
        for doc in raw_results:
            distance = doc.get("distance", 1.0)
            score = round(1.0 - distance, 4)
            d = {
                "document": doc.get("document", ""),
                "metadata": doc.get("metadata", {}),
                "dense_score": score,
            }
            
            # Post-filtrado en Python (más seguro que confiar en sintaxis compleja de ChromaDB antiguo)
            meta = d["metadata"]
            
            is_valid = False
            # 0. Aplica por defecto si el usuario no tiene carrera asignada (wildcard)
            if not carrera_id:
                is_valid = True
            # 1. Aplica si es de toda la facultad
            elif meta.get("alcance") == "facultad":
                is_valid = True
            # 2. Aplica si es de la carrera exacta (planificaciones)
            elif meta.get("carrera_id") == carrera_id:
                is_valid = True
            # 3. Aplica si la carrera está relacionada (boletines)
            elif carrera_id and carrera_id in meta.get("carreras_relacionadas", ""):
                is_valid = True
            # 4. Fallbacks (si no tiene carrera específica)
            elif not meta.get("carrera_id") and not meta.get("carreras_relacionadas"):
                is_valid = True
                
            if is_valid and score > 0.15:
                docs_formatted.append(d)
        
        if not docs_formatted:
            return []

        # Reciprocal Rank Fusion con BM25
        try:
            from app.rag.bm25 import BM25Retriever
            bm25_docs = [{"page_content": d["document"]} for d in docs_formatted]
            bm25_retriever = BM25Retriever(bm25_docs)
            bm25_scores = bm25_retriever.get_scores(query)

            for i, doc in enumerate(docs_formatted):
                doc["bm25_score"] = bm25_scores[i]

            docs_formatted.sort(key=lambda x: x["dense_score"], reverse=True)
            for rank, doc in enumerate(docs_formatted):
                doc["dense_rank"] = rank + 1
                
            docs_formatted.sort(key=lambda x: x["bm25_score"], reverse=True)
            for rank, doc in enumerate(docs_formatted):
                doc["bm25_rank"] = rank + 1

            k = 60
            for doc in docs_formatted:
                doc["rrf_score"] = (1.0 / (k + doc["dense_rank"])) + (1.0 / (k + doc["bm25_rank"]))

            docs_formatted.sort(key=lambda x: x["rrf_score"], reverse=True)
            
            filtered = []
            for doc in docs_formatted[:self._n_results]:
                doc["score"] = round(doc["rrf_score"], 4)
                filtered.append(doc)
        except Exception as e:
            logger.warning("Fallo en BM25, usando solo Dense: %s", e)
            docs_formatted.sort(key=lambda x: x["dense_score"], reverse=True)
            filtered = []
            for doc in docs_formatted[:self._n_results]:
                doc["score"] = doc["dense_score"]
                filtered.append(doc)

        logger.info(
            "RAG Retrieve: query='%s…' ciclo=%s carrera_id='%s' → %d docs | Scores: [%s]",
            query[:40], ciclo, carrera_id, len(filtered),
            ", ".join(f"{d.get('score', 0):.4f}" for d in filtered) or "ninguno",
        )

        return filtered

    async def retrieve_with_prompt(
        self,
        query: str,
        año_academico: str,
        carrera: str,
        is_exams: bool = False,
        secciones: list[str] | None = None,
        materia_id: str | None = None,
    ) -> RetrieverResult:
        docs = await self.retrieve(query, año_academico, carrera, secciones=secciones, materia_id=materia_id)
        prompt = build_rag_prompt(docs, self._base_prompt, max_context_chars=self._max_context_chars)
        return RetrieverResult(docs=docs, system_prompt=prompt)

    async def _embed(self, text: str):
        if inspect.iscoroutinefunction(self._embedder):
            return await self._embedder(text)
        return await asyncio.to_thread(self._embedder, text)


_retriever: Retriever | None = None

def get_retriever(vector_store=None, embedder=None) -> Retriever:
    global _retriever
    if _retriever is None:
        from app.rag.embeddings import embed_text
        from app.rag.vectorstore import get_vector_store
        _retriever = Retriever(
            vector_store=vector_store or get_vector_store(),
            embedder=embedder or embed_text,
        )
    return _retriever
