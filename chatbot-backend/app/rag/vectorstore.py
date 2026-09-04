"""
app/rag/vectorstore.py — Vector Store con ChromaDB.

FASE 2: Inicialización y operaciones básicas del vector store.
FASE 3: Se completará con chunking estructurado y filtros por metadatos
        (año_academico, carrera) para el pipeline RAG completo.

COLECCIÓN: "academic_docs"
  Metadatos requeridos por documento:
    - source:       nombre del archivo PDF de origen
    - año_academico: string (ej. "2026")
    - carrera:      string (ej. "Ingeniería Informática")
    - chunk_index:  int (posición del chunk en el documento)

FILTRADO ESTRICTO (Fase 3):
  Todas las consultas deben filtrarse por año_academico y carrera para
  evitar que el LLM use información de otros planes de estudio o años.
"""
import logging
from typing import Optional, Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "academic_docs"


class VectorStore:
    """
    Wrapper sobre ChromaDB para el vector store del chatbot académico.

    Args:
        host: Host de ChromaDB (para modo cliente HTTP).
        port: Puerto de ChromaDB.
    """

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        settings = get_settings()
        _host = host or settings.chroma_host
        _port = port or settings.chroma_port

        self._client = chromadb.HttpClient(
            host=_host,
            port=_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """Obtiene o crea la colección principal de documentos académicos."""
        try:
            collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # Métrica: similitud coseno
            )
            logger.info(
                "ChromaDB colección '%s' lista. Documentos: %d",
                COLLECTION_NAME,
                collection.count(),
            )
            return collection
        except Exception as exc:
            logger.error("Error conectando a ChromaDB: %s", exc)
            raise

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Busca los documentos más similares al embedding dado.

        Args:
            query_embedding: Vector de consulta (lista de floats).
            n_results:       Número de resultados a retornar.
            where:           Filtros de metadatos.
                             Si tiene 2+ claves, se convierte automáticamente
                             al formato $and de ChromaDB para evitar errores.
                             Ej: {"año_academico": "2026", "carrera": "Informática"}
                             →   {"$and": [{"año_academico": ...}, {"carrera": ...}]}

        Returns:
            Lista de dicts con 'document', 'metadata', 'distance' y 'score'.
        """
        count = self._collection.count()
        if count == 0:
            return []

        # ChromaDB requiere $and para filtros con múltiples claves
        chroma_where = None
        if where:
            if len(where) == 1:
                chroma_where = where
            else:
                chroma_where = {"$and": [{k: v} for k, v in where.items()]}

        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results":        min(n_results, count),
            "include":          ["documents", "metadatas", "distances"],
        }
        if chroma_where:
            kwargs["where"] = chroma_where

        results = self._collection.query(**kwargs)

        # Aplanar la estructura anidada de ChromaDB
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        return [
            {
                "document": doc,
                "metadata": meta,
                "distance": dist,
                "score":    round(1.0 - dist, 4),  # similitud coseno
            }
            for doc, meta, dist in zip(docs, metas, distances)
        ]

    def upsert(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        ids: list[str],
    ) -> None:
        """
        Añade o actualiza (upsert) documentos en el vector store.
        ChromaDB hace upsert automático cuando el ID ya existe.
        """
        self._collection.upsert(
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info("Upsert de %d chunks en ChromaDB.", len(documents))

    def get(self, where: dict[str, Any] | None = None, include: list[str] | None = None) -> dict[str, Any]:
        """
        Retrieves documents matching metadata filters.
        """
        _include = include or ["metadatas", "documents"]
        chroma_where = None
        if where:
            if "$and" in where or "$or" in where:
                chroma_where = where
            elif len(where) == 1:
                chroma_where = where
            elif len(where) > 1:
                chroma_where = {"$and": [{k: v} for k, v in where.items()]}

        kwargs: dict = {"include": _include}
        if chroma_where:
            kwargs["where"] = chroma_where
        return self._collection.get(**kwargs)

    def delete_by_source(self, source: str) -> int:
        """
        Elimina todos los chunks de un documento por nombre de archivo.
        Útil para re-ingestar documentos actualizados.

        Args:
            source: Nombre del archivo (ej. 'reglamento_2026.pdf').

        Returns:
            Número de chunks eliminados.
        """
        results = self._collection.get(
            where={"source": source},
            include=["metadatas"],
        )
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
            logger.info("Eliminados %d chunks de '%s'.", len(ids), source)
        return len(ids)

    def purge(self) -> None:
        """Elimina la colección completa. Útil para migraciones de esquema de metadata."""
        try:
            self._client.delete_collection(COLLECTION_NAME)
            logger.warning("Colección '%s' eliminada completamente.", COLLECTION_NAME)
            self._collection = self._get_or_create_collection()
        except Exception as e:
            logger.error("Error al purgar colección: %s", e)

    def count(self) -> int:
        """Retorna el número total de documentos en la colección."""
        return self._collection.count()

    def is_available(self) -> bool:
        """Verifica si ChromaDB responde correctamente."""
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Retorna la instancia singleton del vector store."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
