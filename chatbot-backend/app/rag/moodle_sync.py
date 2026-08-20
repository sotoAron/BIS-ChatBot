"""
app/rag/moodle_sync.py — Sincronización dinámica de PDFs desde Moodle a ChromaDB.
"""
import io
import logging
from typing import Any

from pypdf import PdfReader

from app.rag.embeddings import embed_text
from app.rag.ingest import ChunkingConfig, DocumentChunker, DocumentMetadata
from app.rag.vectorstore import get_vector_store
from app.services.moodle_client import get_moodle_client

logger = logging.getLogger(__name__)


async def sync_course_pdf(course_id: int, file_url: str, filename: str, año: str, carrera: str) -> int:
    """
    Descarga un PDF de Moodle, extrae su texto, lo divide en chunks y lo indexa
    en ChromaDB, asociado al course_id, año y carrera.
    """
    moodle_client = get_moodle_client()
    
    logger.info("Descargando PDF de Moodle: %s (course_id=%d)", filename, course_id)
    pdf_bytes = await moodle_client.download_file(file_url)
    
    logger.info("Extrayendo texto del PDF (%d bytes)", len(pdf_bytes))
    reader = PdfReader(io.BytesIO(pdf_bytes))
    
    text_content = ""
    for page in reader.pages:
        text_content += page.extract_text() + "\n\n"

    # Preparar VectorStore y eliminar chunks antiguos de este documento (upsert lógico)
    vs = get_vector_store()
    
    # En una impl robusta haríamos un borrado previo si existiera el doc,
    # por simplicidad en Fase 4 agregamos o dejamos que Chroma maneje duplicados
    # basándonos en hashes si se usa el mismo chunker.

    metadata = DocumentMetadata(
        source=f"moodle_{course_id}_{filename}",
        año_academico=año,
        carrera=carrera,
        module=filename,
    )
    
    chunker = DocumentChunker(
        vector_store=vs,
        embedder=embed_text,
        config=ChunkingConfig(chunk_size=512, chunk_overlap=64)
    )

    logger.info("Generando chunks e indexando en ChromaDB...")
    
    # Fake a path to pass to ingest_text (we bypass ingest() since we have text directly)
    # Actually ingest() expects a Path. We will use ingest_text() which is cleaner
    chunks = chunker._chunk_text(text_content)
    await chunker._add_to_vectorstore(chunks, metadata)
    
    logger.info("✅ Sincronización completa: %d chunks indexados para el curso %d", len(chunks), course_id)
    return len(chunks)
