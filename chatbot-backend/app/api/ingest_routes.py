"""
app/api/ingest_routes.py — Endpoints de administración para ingesta de documentos RAG.

ENDPOINTS:
  POST /api/admin/ingest     → Ingestar un documento (PDF/TXT/DOCX) al vector store
  DELETE /api/admin/document → Eliminar todos los chunks de un documento por nombre
  GET  /api/admin/stats      → Estadísticas del vector store

SEGURIDAD:
  - Estos endpoints requieren JWT con role='teacher' o role='admin'.
  - No son accesibles desde el widget del alumno.
  - En producción, añadir también IP allowlist o API key interna.
"""
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.core.security import get_current_user
from app.rag.embeddings import embed_text
from app.rag.ingest import ChunkingConfig, DocumentChunker, DocumentMetadata

logger = logging.getLogger(__name__)
admin_router = APIRouter(prefix="/api/admin", tags=["Administration"])

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
MAX_FILE_SIZE_MB = 50


def _require_teacher(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia: requiere role teacher o admin en el JWT."""
    role = user.get("role", "student")
    if role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los docentes pueden ingestar documentos.",
        )
    return user


@admin_router.post("/ingest")
async def ingest_document(
    request: Request,
    file: UploadFile = File(..., description="Documento a ingestar (PDF, TXT, DOCX, MD)"),
    año_academico: str = Form(..., description="Año académico (ej. 2026)"),
    carrera: str = Form(..., description="Nombre de la carrera"),
    module: str = Form("", description="Módulo o sección del documento (opcional)"),
    chunk_size: int = Form(512, description="Tamaño máximo de cada chunk en caracteres"),
    chunk_overlap: int = Form(64, description="Solapamiento entre chunks en caracteres"),
    _user: dict = Depends(_require_teacher),
):
    """
    Ingesta un documento al vector store de ChromaDB.

    El documento se procesa en chunks, se generan embeddings locales con
    sentence-transformers y se indexa con metadatos (año_academico, carrera).

    Retorna el número de chunks indexados.
    """
    # Validar extensión
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Formato no soportado: '{suffix}'. Permitidos: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Leer contenido y verificar tamaño
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archivo demasiado grande ({size_mb:.1f} MB). Máximo: {MAX_FILE_SIZE_MB} MB.",
        )

    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ChromaDB no está disponible.",
        )

    # Guardar en archivo temporal para procesarlo con pypdf/docx
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        metadata = DocumentMetadata(
            source=file.filename or "unknown",
            año_academico=año_academico,
            carrera=carrera,
            module=module,
        )
        config = ChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunker = DocumentChunker(
            vector_store=vector_store,
            embedder=embed_text,
            config=config,
        )
        count = await chunker.ingest(tmp_path, metadata)

    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(
        "Ingesta completada: %s → %d chunks (año=%s, carrera='%s')",
        file.filename, count, año_academico, carrera,
    )
    return {
        "status":        "ok",
        "filename":      file.filename,
        "chunks":        count,
        "año_academico": año_academico,
        "carrera":       carrera,
    }


@admin_router.delete("/document")
async def delete_document(
    request: Request,
    source: str,
    _user: dict = Depends(_require_teacher),
):
    """
    Elimina todos los chunks de un documento del vector store por nombre de archivo.
    Útil para re-ingestar una versión actualizada del documento.
    """
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(status_code=503, detail="ChromaDB no disponible.")

    deleted = vector_store.delete_by_source(source)
    return {"status": "ok", "deleted_chunks": deleted, "source": source}


@admin_router.get("/stats")
async def vector_store_stats(
    request: Request,
    _user: dict = Depends(_require_teacher),
):
    """Retorna estadísticas del vector store (número total de chunks)."""
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        return {"status": "unavailable", "total_chunks": 0}

    return {
        "status":        "ok",
        "total_chunks":  vector_store.count(),
        "is_available":  vector_store.is_available(),
    }
