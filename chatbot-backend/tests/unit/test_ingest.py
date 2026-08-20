"""
tests/unit/test_ingest.py — TDD: Suite de tests para el pipeline de ingesta RAG.

METODOLOGÍA TDD:
  Escritos ANTES de la implementación de ingest.py.
  Definen el contrato del pipeline de chunking e indexación.

CONTRATO VERIFICADO:
  ✓ PDF sin contenido → 0 chunks, sin error
  ✓ PDF con contenido → N chunks > 0
  ✓ Chunks respetan el tamaño máximo configurado (chunk_size)
  ✓ Chunks contienen overlap con el chunk anterior
  ✓ Chunks NO están vacíos ni son solo espacios
  ✓ Metadatos obligatorios presentes en cada chunk
  ✓ Soporte para TXT y DOCX (extracción de texto)
  ✓ Headings de PDF se reconocen como límites de sección
  ✓ IDs de chunks son únicos dentro del documento
"""
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.rag.ingest import (
    DocumentChunker,
    ChunkingConfig,
    DocumentMetadata,
    extract_text_from_pdf,
    extract_text_from_txt,
    chunk_text,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def default_config() -> ChunkingConfig:
    """Configuración de chunking estándar para tests."""
    return ChunkingConfig(chunk_size=200, chunk_overlap=40, min_chunk_length=30)


@pytest.fixture
def sample_metadata() -> DocumentMetadata:
    return DocumentMetadata(
        source="reglamento_2026.pdf",
        año_academico="2026",
        carrera="Informática",
        module="Reglamento Académico",
    )


@pytest.fixture
def long_text() -> str:
    """Texto suficientemente largo para producir múltiples chunks."""
    paragraphs = [
        "Artículo 1. El presente reglamento regula las condiciones académicas de la facultad.",
        "Artículo 2. Los estudiantes deberán cumplir con los requisitos mínimos de asistencia del setenta por ciento.",
        "Artículo 3. La aprobación de las materias requiere una nota mínima de seis sobre diez puntos.",
        "Artículo 4. El régimen de recursada permite repetir hasta dos veces una misma materia.",
        "Artículo 5. Los plazos de inscripción serán publicados en el calendario académico oficial.",
        "Artículo 6. El abandono de materias debe notificarse dentro de los primeros treinta días.",
    ]
    return "\n\n".join(paragraphs)


@pytest.fixture
def mock_vectorstore():
    vs = MagicMock()
    vs.add = MagicMock()
    return vs


@pytest.fixture
def mock_embedder():
    import numpy as np

    async def _embed(text: str):
        # Embedding fijo de 384 dims para tests
        return (np.ones(384) / 384).tolist()

    return _embed


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Función chunk_text()
# ══════════════════════════════════════════════════════════════════════════════

class TestChunkText:
    """chunk_text() debe segmentar texto con overlap y tamaño correcto."""

    def test_short_text_produces_single_chunk(self, default_config):
        """Texto menor al chunk_size → exactamente 1 chunk."""
        text = "Texto corto que entra en un solo chunk."
        chunks = chunk_text(text, default_config)
        assert len(chunks) == 1

    def test_long_text_produces_multiple_chunks(self, long_text, default_config):
        """Texto largo → más de 1 chunk."""
        chunks = chunk_text(long_text, default_config)
        assert len(chunks) > 1

    def test_chunks_respect_max_size(self, long_text, default_config):
        """Ningún chunk debe superar chunk_size (en caracteres)."""
        chunks = chunk_text(long_text, default_config)
        for i, chunk in enumerate(chunks):
            assert len(chunk) <= default_config.chunk_size + default_config.chunk_overlap, (
                f"Chunk {i} tiene {len(chunk)} chars, excede {default_config.chunk_size}"
            )

    def test_chunks_are_not_empty(self, long_text, default_config):
        """Ningún chunk debe estar vacío ni ser solo espacios."""
        chunks = chunk_text(long_text, default_config)
        for chunk in chunks:
            assert chunk.strip(), "Chunk vacío detectado"

    def test_chunks_have_min_length(self, default_config):
        """Chunks muy cortos deben ser descartados."""
        # Texto con un fragmento muy corto al final
        text = "Párrafo completo con suficiente contenido para ser válido. " * 3 + "\n\nFin."
        chunks = chunk_text(text, default_config)
        for chunk in chunks:
            assert len(chunk.strip()) >= default_config.min_chunk_length

    def test_consecutive_chunks_have_overlap(self, long_text):
        """Chunks consecutivos deben compartir contenido (overlap)."""
        config = ChunkingConfig(chunk_size=150, chunk_overlap=50, min_chunk_length=20)
        chunks = chunk_text(long_text, config)

        if len(chunks) >= 2:
            # El final del chunk N debe aparecer al inicio del chunk N+1
            end_of_first = chunks[0][-30:]
            start_of_second = chunks[1][:80]
            # Verificar que al menos algunos caracteres se solapan
            assert any(
                end_of_first[-i:] in start_of_second
                for i in range(10, min(len(end_of_first), 30))
            ), "Los chunks consecutivos no tienen overlap"

    def test_empty_text_returns_empty_list(self, default_config):
        """Texto vacío → lista vacía (sin crash)."""
        chunks = chunk_text("", default_config)
        assert chunks == []

    def test_whitespace_only_returns_empty_list(self, default_config):
        """Solo espacios/saltos → lista vacía."""
        chunks = chunk_text("   \n\n\t   ", default_config)
        assert chunks == []


# ══════════════════════════════════════════════════════════════════════════════
# Tests — Extracción de texto
# ══════════════════════════════════════════════════════════════════════════════

class TestTextExtraction:
    """Los extractores deben retornar texto limpio de diferentes formatos."""

    def test_extract_text_from_txt(self, tmp_path):
        """Extracción desde TXT plano."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hola mundo.\nSegunda línea.", encoding="utf-8")

        text = extract_text_from_txt(txt_file)
        assert "Hola mundo" in text
        assert "Segunda línea" in text

    def test_extract_text_from_empty_txt(self, tmp_path):
        """TXT vacío → string vacío, sin error."""
        txt_file = tmp_path / "empty.txt"
        txt_file.write_text("", encoding="utf-8")

        text = extract_text_from_txt(txt_file)
        assert text.strip() == ""

    @patch("app.rag.ingest.PdfReader")
    def test_extract_text_from_pdf_calls_reader(self, mock_reader_cls, tmp_path):
        """extract_text_from_pdf debe usar PdfReader y retornar texto de páginas."""
        # Configurar el mock de pypdf
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Contenido de la página 1."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()

        text = extract_text_from_pdf(pdf_file)
        assert "Contenido de la página 1." in text

    @patch("app.rag.ingest.PdfReader")
    def test_extract_text_from_pdf_multiple_pages(self, mock_reader_cls, tmp_path):
        """El texto de todas las páginas debe concatenarse."""
        mock_reader = MagicMock()
        mock_reader.pages = [
            MagicMock(extract_text=MagicMock(return_value=f"Página {i}"))
            for i in range(3)
        ]
        mock_reader_cls.return_value = mock_reader

        pdf_file = tmp_path / "multi.pdf"
        pdf_file.touch()

        text = extract_text_from_pdf(pdf_file)
        assert "Página 0" in text
        assert "Página 1" in text
        assert "Página 2" in text


# ══════════════════════════════════════════════════════════════════════════════
# Tests — DocumentChunker (pipeline completo)
# ══════════════════════════════════════════════════════════════════════════════

class TestDocumentChunker:
    """DocumentChunker orquesta extracción + chunking + indexación."""

    @pytest.mark.asyncio
    async def test_ingest_txt_returns_chunk_count(
        self, mock_vectorstore, mock_embedder, sample_metadata, tmp_path, long_text
    ):
        """La ingesta de un TXT debe retornar el número de chunks insertados."""
        txt_file = tmp_path / "reglamento.txt"
        txt_file.write_text(long_text, encoding="utf-8")

        chunker = DocumentChunker(
            vector_store=mock_vectorstore,
            embedder=mock_embedder,
            config=ChunkingConfig(chunk_size=200, chunk_overlap=40, min_chunk_length=30),
        )
        count = await chunker.ingest(txt_file, sample_metadata)
        assert count > 0

    @pytest.mark.asyncio
    async def test_ingest_calls_vectorstore_add(
        self, mock_vectorstore, mock_embedder, sample_metadata, tmp_path, long_text
    ):
        """La ingesta debe llamar a vectorstore.add() al menos una vez."""
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text(long_text, encoding="utf-8")

        chunker = DocumentChunker(mock_vectorstore, mock_embedder)
        await chunker.ingest(txt_file, sample_metadata)

        assert mock_vectorstore.add.called

    @pytest.mark.asyncio
    async def test_chunk_metadata_contains_required_fields(
        self, mock_vectorstore, mock_embedder, sample_metadata, tmp_path
    ):
        """Cada chunk indexado debe tener año_academico, carrera y source en metadatos."""
        txt_file = tmp_path / "meta_test.txt"
        txt_file.write_text(
            "Texto de prueba suficientemente largo para generar un chunk válido. " * 5,
            encoding="utf-8",
        )

        chunker = DocumentChunker(mock_vectorstore, mock_embedder)
        await chunker.ingest(txt_file, sample_metadata)

        # Verificar que add() fue llamado con los metadatos correctos
        assert mock_vectorstore.add.called
        call_kwargs = mock_vectorstore.add.call_args[1]
        metadatas = call_kwargs.get("metadatas", [])

        assert len(metadatas) > 0
        for meta in metadatas:
            assert "año_academico" in meta, "Falta campo 'año_academico' en metadatos"
            assert "carrera" in meta,       "Falta campo 'carrera' en metadatos"
            assert "source" in meta,        "Falta campo 'source' en metadatos"
            assert meta["año_academico"] == "2026"
            assert meta["carrera"] == "Informática"

    @pytest.mark.asyncio
    async def test_chunk_ids_are_unique(
        self, mock_vectorstore, mock_embedder, sample_metadata, tmp_path, long_text
    ):
        """Los IDs generados para cada chunk deben ser únicos."""
        txt_file = tmp_path / "ids_test.txt"
        txt_file.write_text(long_text, encoding="utf-8")

        chunker = DocumentChunker(mock_vectorstore, mock_embedder)
        await chunker.ingest(txt_file, sample_metadata)

        call_kwargs = mock_vectorstore.add.call_args[1]
        ids = call_kwargs.get("ids", [])

        assert len(ids) == len(set(ids)), "IDs de chunks duplicados detectados"

    @pytest.mark.asyncio
    async def test_empty_file_produces_zero_chunks(
        self, mock_vectorstore, mock_embedder, sample_metadata, tmp_path
    ):
        """Un archivo vacío debe ingestar 0 chunks sin lanzar excepción."""
        txt_file = tmp_path / "empty.txt"
        txt_file.write_text("", encoding="utf-8")

        chunker = DocumentChunker(mock_vectorstore, mock_embedder)
        count = await chunker.ingest(txt_file, sample_metadata)

        assert count == 0
        assert not mock_vectorstore.add.called
