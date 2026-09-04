"""
app/rag/ingest.py — Pipeline de ingesta de documentos para el vector store RAG.

SOPORTA: PDF, TXT, DOCX
ESTRATEGIA DE CHUNKING: Estructural (por tipo de documento).

El chunker ahora delega la segmentación a un parser específico según el 
document_type (ej. PlanificacionParser, BoletinParser). Si el tipo es
desconocido, usa un fallback de chunking por tamaño (Sliding Window).
"""
import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

try:
    from pypdf import PdfReader as _PdfReader  # type: ignore
except ImportError:
    _PdfReader = None  # type: ignore

from app.rag.models import ChunkMetadata
from app.rag.parsers.base import get_parser
from app.rag.catalog import get_catalog

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Modelos de datos
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChunkingConfig:
    """Configuración del pipeline de chunking (usada principalmente para fallback)."""
    chunk_size: int = 1500
    chunk_overlap: int = 256
    min_chunk_length: int = 40


@dataclass
class DocumentMetadata:
    """Metadatos de un documento a ingestar."""
    source: str
    año_academico: str
    carrera: str
    module: str = ""
    # Nuevos campos:
    document_type: str = "planificacion"
    materia_id: str | None = None
    carrera_id: str | None = None
    nivel: int | None = None
    cuatrimestre: str | None = None
    comision_id: str | None = None
    fecha_publicacion: str | None = None
    vigente_hasta: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Extracción de texto por formato
# ══════════════════════════════════════════════════════════════════════════════

def extract_text_from_pdf(path: Path) -> str:
    """
    Extrae texto de un archivo PDF.
    Intenta pymupdf4llm (Markdown, preserva tablas); fallback a pypdf.
    """
    try:
        import pymupdf4llm  # type: ignore
        import pymupdf       # type: ignore
        doc = pymupdf.open(str(path))
        md = pymupdf4llm.to_markdown(doc)
        if md and md.strip():
            return md
    except Exception:
        pass

    # Fallback pypdf
    if _PdfReader is None:
        raise ImportError("pypdf no está instalado y pymupdf4llm falló")
    reader = _PdfReader(str(path))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text.strip())
    return "\n\n".join(pages_text)


def extract_text_from_txt(path: Path) -> str:
    """Extrae texto de un archivo TXT (UTF-8 con fallback a latin-1)."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def extract_text_from_docx(path: Path) -> str:
    """Extrae texto de un archivo DOCX respetando el orden de párrafos."""
    try:
        # pyrefly: ignore [missing-import]
        from docx import Document  # type: ignore  # python-docx
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as exc:
        logger.error("Error leyendo DOCX %s: %s", path.name, exc)
        return ""


def extract_text(path: Path) -> str:
    """Dispatcher: extrae texto según la extensión del archivo."""
    suffix = path.suffix.lower()
    extractors = {
        ".pdf":  extract_text_from_pdf,
        ".txt":  extract_text_from_txt,
        ".md":   extract_text_from_txt,
        ".docx": extract_text_from_docx,
    }
    extractor = extractors.get(suffix)
    if extractor is None:
        raise ValueError(f"Formato no soportado: {suffix}. Use PDF, TXT, DOCX o MD.")
    return extractor(path)


# ══════════════════════════════════════════════════════════════════════════════
# Orquestador del pipeline
# ══════════════════════════════════════════════════════════════════════════════

class DocumentChunker:
    """
    Pipeline completo: extracción de texto → chunking estructural → embedding → indexación.
    """

    def __init__(
        self,
        vector_store: Any,
        embedder: Callable,
        config: ChunkingConfig | None = None,
    ) -> None:
        self._store    = vector_store
        self._embedder = embedder
        self._config   = config or ChunkingConfig()

    async def ingest(self, path: Path, metadata: DocumentMetadata) -> int:
        logger.info("Iniciando ingesta: %s (%s)", path.name, metadata.document_type)

        # 1. Extraer texto
        raw_text = extract_text(path)
        if not raw_text.strip():
            logger.warning("Documento vacío o sin texto extraíble: %s", path.name)
            return 0

        # Normalizar carrera si viene como string libre
        catalog = get_catalog()
        if not metadata.carrera_id and metadata.carrera:
            metadata.carrera_id = catalog.normalize_carrera(metadata.carrera)

        # 2. Chunking Estructural
        parser = get_parser(metadata.document_type)
        
        # Extra metadata para el parser
        extra_metadata = {
            "document_type": metadata.document_type,
            "fecha_publicacion": metadata.fecha_publicacion,
            "vigente_hasta": metadata.vigente_hasta,
            "module": metadata.module,
        }

        chunks_meta = parser.parse(
            text=raw_text,
            source=metadata.source,
            carrera_id=metadata.carrera_id,
            materia_id=metadata.materia_id,
            ciclo_lectivo=int(metadata.año_academico) if metadata.año_academico.isdigit() else 2026,
            comision_id=metadata.comision_id,
            nivel=metadata.nivel,
            cuatrimestre=metadata.cuatrimestre,
            extra_metadata=extra_metadata,
        )

        if not chunks_meta:
            logger.warning("Ningún chunk generado para: %s", path.name)
            return 0

        total = len(chunks_meta)
        logger.info("Chunks generados: %d para %s", total, path.name)

        # 3. Embeddings en paralelo (sobre el texto contextualizado)
        texts_to_embed = [c.texto_contextualizado for c in chunks_meta]
        
        embeddings = await asyncio.gather(
            *[
                self._embedder(text) if inspect.iscoroutinefunction(self._embedder)
                else asyncio.to_thread(self._embedder, text)
                for text in texts_to_embed
            ]
        )

        processed_embeddings = []
        for emb in embeddings:
            if hasattr(emb, "tolist"):
                processed_embeddings.append(emb.tolist())
            else:
                processed_embeddings.append(list(emb))

        # 4. Preparar para ChromaDB
        documents = texts_to_embed
        ids = [c.chunk_id for c in chunks_meta]
        metadatas = [c.to_chroma_metadata() for c in chunks_meta]

        # 5. Indexar (batch)
        self._store.upsert(
            documents=documents,
            embeddings=processed_embeddings,
            metadatas=metadatas,
            ids=ids,
        )

        logger.info("Indexados %d chunks de '%s' en ChromaDB.", total, path.name)
        return total


# ═══════════════════════════════════════════════════════════════════════════════
# Backward compatibility
# ═══════════════════════════════════════════════════════════════════════════════

class PDFIngestor(DocumentChunker):
    """
    Alias de DocumentChunker para compatibilidad con código antiguo.
    """
    import warnings
    warnings.warn("PDFIngestor is deprecated. Use DocumentChunker.", DeprecationWarning)

    async def ingest(  # type: ignore[override]
        self,
        pdf_path: Path,
        año_academico: str,
        carrera: str,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        module: str = "",
    ) -> int:
        self._config = ChunkingConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        
        # Adivinar document_type (heuristic fallback for old code)
        doc_type = "planificacion"
        if "bolet" in pdf_path.name.lower():
            doc_type = "boletin"
            
        meta = DocumentMetadata(
            source=pdf_path.name,
            año_academico=año_academico,
            carrera=carrera,
            module=module,
            document_type=doc_type
        )
        return await super().ingest(pdf_path, meta)
