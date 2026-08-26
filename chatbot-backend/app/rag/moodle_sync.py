"""
app/rag/moodle_sync.py — Sincronización dinámica de PDFs desde Moodle a ChromaDB.

ESTRATEGIA DE EXTRACCIÓN (Fase 4):
  - pymupdf4llm: Extrae PDF a Markdown preservando tablas de cronogramas,
    encabezados de sección y listas. Crucial para tablas de fechas de exámenes.
  - Fallback a pypdf: Si pymupdf4llm falla (PDF escaneado, cifrado, etc.).

ESTRATEGIA DE CHUNKING:
  - chunk_markdown_text(): Divisor jerárquico por encabezados Markdown.
    Los bloques que superan 1500 caracteres se re-dividen con solapamiento.
"""
import asyncio
import inspect
import io
import logging

from app.rag.embeddings import embed_text
from app.rag.ingest import (
    DocumentMetadata,
    chunk_markdown_text,
    make_chunk_id,
)
from app.rag.vectorstore import get_vector_store
from app.services.moodle_client import get_moodle_client

logger = logging.getLogger(__name__)


def _extract_pdf_to_markdown(pdf_bytes: bytes) -> str:
    """
    Extrae el PDF a texto Markdown usando pymupdf4llm.
    Preserva tablas (cronogramas, fechas) como tablas GFM Markdown.
    Fallback a pypdf si falla.
    """
    try:
        import pymupdf4llm  # type: ignore
        import pymupdf       # type: ignore
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        md_text = pymupdf4llm.to_markdown(doc)
        if md_text and md_text.strip():
            logger.info("pymupdf4llm: extracción Markdown exitosa (%d chars)", len(md_text))
            return md_text
        logger.warning("pymupdf4llm devolvió texto vacío, usando fallback pypdf")
    except Exception as e:
        logger.warning("pymupdf4llm falló (%s), usando fallback pypdf", e)

    # Fallback: pypdf texto plano
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


async def sync_course_pdf(
    course_id: int,
    file_url: str,
    filename: str,
    año: str,
    carrera: str,
) -> int:
    """
    Descarga un PDF de Moodle, lo convierte a Markdown con pymupdf4llm,
    aplica chunking jerárquico y lo indexa en ChromaDB.

    Returns:
        Número de chunks efectivamente indexados.
    """
    moodle_client = get_moodle_client()

    logger.info("Descargando PDF de Moodle: %s (course_id=%d)", filename, course_id)
    pdf_bytes = await moodle_client.download_file(file_url)
    logger.info("PDF descargado: %d bytes", len(pdf_bytes))

    # 1. Extracción a Markdown (preserva tablas y secciones)
    md_text = _extract_pdf_to_markdown(pdf_bytes)

    if not md_text.strip():
        logger.warning("El PDF descargado no contiene texto extraíble: %s", filename)
        return 0

    # 2. Chunking jerárquico por encabezados Markdown
    chunks = chunk_markdown_text(md_text)
    total = len(chunks)
    if total == 0:
        logger.warning("Ningún chunk generado para: %s", filename)
        return 0

    logger.info("Chunks generados (jerárquico MD): %d para '%s'", total, filename)

    # 3. Metadatos del documento
    metadata = DocumentMetadata(
        source=f"moodle_{course_id}_{filename}",
        año_academico=año,
        carrera=carrera,
        module=filename,
    )

    # 4. Embeddings en paralelo
    embeddings = await asyncio.gather(
        *[
            embed_text(chunk) if inspect.iscoroutinefunction(embed_text)
            else asyncio.to_thread(embed_text, chunk)
            for chunk in chunks
        ]
    )

    processed_embeddings = []
    for emb in embeddings:
        if hasattr(emb, "tolist"):
            processed_embeddings.append(emb.tolist())
        else:
            processed_embeddings.append(list(emb))

    # 5. IDs deterministas y metadatos por chunk
    ids = [
        make_chunk_id(metadata.source, metadata.año_academico, metadata.carrera, i)
        for i in range(total)
    ]
    metadatas = [metadata.to_chunk_meta(i, total) for i in range(total)]

    # 6. Limpiar versión anterior y Upsert en ChromaDB
    vs = get_vector_store()
    vs.delete_by_source(metadata.source)
    vs.upsert(
        documents=chunks,
        embeddings=processed_embeddings,
        metadatas=metadatas,
        ids=ids,
    )

    logger.info(
        "✅ Sincronización completa: %d chunks indexados para '%s' (course_id=%d)",
        total, filename, course_id,
    )
    return total
