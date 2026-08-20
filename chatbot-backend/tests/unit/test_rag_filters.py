"""
tests/unit/test_rag_filters.py — TDD: Suite de tests para filtros de metadatos RAG.

METODOLOGÍA TDD:
  Escritos ANTES de la implementación del Retriever.
  Definen el contrato de aislamiento estricto por metadatos.

CONTRATO VERIFICADO (spec § 2 & § 3):
  ✓ Filtro por año_academico excluye documentos de otros años
  ✓ Filtro por carrera excluye documentos de otras carreras
  ✓ Filtro combinado (año + carrera) devuelve solo documentos coincidentes
  ✓ Consulta sin documentos coincidentes retorna lista vacía (no alucinaciones)
  ✓ Umbral mínimo de similitud (RETRIEVER_MIN_SCORE) filtra resultados irrelevantes
  ✓ build_rag_prompt integra el contexto correctamente
  ✓ build_rag_prompt maneja el caso "sin contexto" con mensaje explícito
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.rag.retriever import Retriever, build_rag_prompt, NO_CONTEXT_MESSAGE


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures — Vector store en memoria (sin ChromaDB real)
# ══════════════════════════════════════════════════════════════════════════════

def _make_doc(text: str, año: str, carrera: str, score: float) -> dict:
    """Helper: construye un resultado de VectorStore.query()."""
    return {
        "document": text,
        "metadata": {
            "source":        "test.pdf",
            "año_academico": año,
            "carrera":       carrera,
            "chunk_index":   0,
            "module":        "Módulo 1",
        },
        "distance": 1.0 - score,  # ChromaDB: distancia coseno = 1 - similitud
    }


@pytest.fixture
def mock_vectorstore():
    """VectorStore mockeado — devuelve documentos configurables."""
    return MagicMock()


@pytest.fixture
def mock_embedder():
    """Embedder mockeado — devuelve siempre el mismo vector unitario."""
    async def _embed(text: str) -> np.ndarray:
        return np.ones(384) / np.sqrt(384)
    return _embed


@pytest.fixture
def retriever(mock_vectorstore, mock_embedder):
    """Retriever con dependencias mockeadas."""
    return Retriever(
        vector_store=mock_vectorstore,
        embedder=mock_embedder,
        min_score=0.70,
        n_results=5,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Filtrado estricto por metadatos
# ══════════════════════════════════════════════════════════════════════════════

class TestMetadataFiltering:
    """El retriever DEBE respetar los filtros de año_academico y carrera."""

    @pytest.mark.asyncio
    async def test_filter_by_año_academico_excludes_other_years(
        self, retriever, mock_vectorstore
    ):
        """
        Documentos de otros años NO deben aparecer aunque sean similares.
        El VectorStore debe recibir el filtro where={'año_academico': '2026'}.
        """
        mock_vectorstore.query.return_value = []

        await retriever.retrieve(
            query="¿Cuántas materias tiene el plan?",
            año_academico="2026",
            carrera="Informática",
        )

        call_kwargs = mock_vectorstore.query.call_args[1]
        assert "where" in call_kwargs
        assert call_kwargs["where"].get("año_academico") == "2026"

    @pytest.mark.asyncio
    async def test_filter_by_carrera_excludes_other_careers(
        self, retriever, mock_vectorstore
    ):
        """Documentos de otra carrera NO deben aparecer en resultados."""
        mock_vectorstore.query.return_value = []

        await retriever.retrieve(
            query="Plan de estudios",
            año_academico="2026",
            carrera="Contabilidad",
        )

        call_kwargs = mock_vectorstore.query.call_args[1]
        where = call_kwargs.get("where", {})
        assert where.get("carrera") == "Contabilidad"

    @pytest.mark.asyncio
    async def test_combined_filter_passes_both_fields(
        self, retriever, mock_vectorstore
    ):
        """El filtro combinado debe incluir ambos: año_academico y carrera."""
        mock_vectorstore.query.return_value = []

        await retriever.retrieve(
            query="Reglamento",
            año_academico="2025",
            carrera="Sistemas",
        )

        where = mock_vectorstore.query.call_args[1].get("where", {})
        assert "año_academico" in where
        assert "carrera" in where
        assert where["año_academico"] == "2025"
        assert where["carrera"] == "Sistemas"


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Umbral mínimo de similitud
# ══════════════════════════════════════════════════════════════════════════════

class TestMinScoreThreshold:
    """El retriever debe filtrar resultados por debajo del umbral min_score."""

    @pytest.mark.asyncio
    async def test_results_above_threshold_are_returned(
        self, retriever, mock_vectorstore
    ):
        """Resultados con score ≥ min_score deben ser incluidos."""
        mock_vectorstore.query.return_value = [
            _make_doc("Texto relevante", "2026", "Informática", score=0.85),
        ]

        results = await retriever.retrieve("pregunta", "2026", "Informática")
        assert len(results) == 1
        assert results[0]["document"] == "Texto relevante"

    @pytest.mark.asyncio
    async def test_results_below_threshold_are_excluded(
        self, retriever, mock_vectorstore
    ):
        """
        Resultados con score < min_score DEBEN ser filtrados.
        Esto evita que el LLM use contexto irrelevante (alucinaciones).
        """
        mock_vectorstore.query.return_value = [
            _make_doc("Texto poco relevante", "2026", "Informática", score=0.50),
        ]

        results = await retriever.retrieve("pregunta", "2026", "Informática")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_exact_threshold_is_included(self, retriever, mock_vectorstore):
        """Score exactamente igual al umbral debe ser incluido (≥, no >)."""
        mock_vectorstore.query.return_value = [
            _make_doc("En el límite", "2026", "Informática", score=0.70),
        ]
        results = await retriever.retrieve("pregunta", "2026", "Informática")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_matching_documents_returns_empty(
        self, retriever, mock_vectorstore
    ):
        """Sin documentos coincidentes → lista vacía (no excepción)."""
        mock_vectorstore.query.return_value = []
        results = await retriever.retrieve("pregunta inexistente", "2026", "Informática")
        assert results == []

    @pytest.mark.asyncio
    async def test_mixed_scores_returns_only_valid(
        self, retriever, mock_vectorstore
    ):
        """Con resultados mixtos, solo los que superan el umbral se retornan."""
        mock_vectorstore.query.return_value = [
            _make_doc("Muy relevante",   "2026", "Informática", score=0.90),
            _make_doc("Poco relevante",  "2026", "Informática", score=0.40),
            _make_doc("Algo relevante",  "2026", "Informática", score=0.75),
        ]

        results = await retriever.retrieve("pregunta", "2026", "Informática")
        assert len(results) == 2
        texts = [r["document"] for r in results]
        assert "Muy relevante" in texts
        assert "Algo relevante" in texts
        assert "Poco relevante" not in texts


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Construcción del prompt RAG
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRagPrompt:
    """build_rag_prompt() debe construir el prompt del sistema con contexto RAG."""

    def test_prompt_includes_context_text(self):
        """El prompt debe contener el texto de los documentos recuperados."""
        docs = [
            {"document": "El plan tiene 32 materias.", "metadata": {}, "distance": 0.1},
            {"document": "El reglamento permite recursada.", "metadata": {}, "distance": 0.2},
        ]
        prompt = build_rag_prompt(docs)
        assert "32 materias" in prompt
        assert "recursada" in prompt

    def test_prompt_with_no_context_returns_no_context_message(self):
        """
        Sin documentos recuperados, el prompt debe incluir un mensaje
        explícito indicando que no hay contexto.
        Esto evita que el LLM invente información académica.
        """
        prompt = build_rag_prompt([])
        assert NO_CONTEXT_MESSAGE in prompt

    def test_prompt_labels_sources(self):
        """El prompt debe marcar claramente el inicio del contexto recuperado."""
        docs = [{"document": "Texto de prueba", "metadata": {"source": "reglamento.pdf"}, "distance": 0.1}]
        prompt = build_rag_prompt(docs)
        # Debe haber alguna sección que identifique el contexto RAG
        assert any(keyword in prompt.upper() for keyword in ["CONTEXTO", "CONTEXT", "FUENTE", "DOCUMENTO"])

    def test_prompt_limits_context_length(self):
        """
        El prompt no debe exceder un límite de caracteres razonable para
        no saturar la ventana de contexto del LLM (Qwen 2.5 3B: ~4096 tokens).
        """
        # 10 documentos largos
        docs = [
            {"document": "A" * 1000, "metadata": {}, "distance": 0.1}
            for _ in range(10)
        ]
        prompt = build_rag_prompt(docs)
        # El prompt resultante no debe exceder ~8000 chars (≈2000 tokens)
        assert len(prompt) <= 8000
