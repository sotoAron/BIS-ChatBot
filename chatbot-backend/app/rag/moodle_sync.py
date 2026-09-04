"""
app/rag/moodle_sync.py — Sincronización dinámica de documentos desde Moodle a ChromaDB.

Escanea todos los archivos de un curso (incluyendo secciones ocultas),
determina su tipo de documento según la sección de Moodle, y los
procesa usando el nuevo pipeline de chunking estructural.
"""
import asyncio
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Optional

from app.rag.embeddings import embed_text
from app.rag.ingest import DocumentChunker, DocumentMetadata, ChunkingConfig
from app.rag.vectorstore import get_vector_store
from app.services.moodle_client import get_moodle_client
from app.rag.catalog import get_catalog

logger = logging.getLogger(__name__)


def _extract_pdf_to_text(pdf_bytes: bytes) -> str:
    """Extrae el PDF a texto Markdown usando pymupdf4llm."""
    try:
        import pymupdf4llm  # type: ignore
        import pymupdf       # type: ignore
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        md_text = pymupdf4llm.to_markdown(doc)
        if md_text and md_text.strip():
            return md_text
    except Exception as e:
        logger.warning("pymupdf4llm falló (%s), usando fallback pypdf", e)

    # Fallback pypdf
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _determine_document_type(course_name: str, section_name: str, filename: str = None) -> str | None:
    """
    Determina el tipo de documento basándose en el nombre del curso, sección y nombre de archivo.
    Usa las reglas del catálogo (data/catalog.json).
    """
    catalog_path = Path(__file__).resolve().parent.parent.parent / "data" / "catalog.json"
    rules = {}
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                rules = data.get("document_type_rules", {})
        except Exception:
            pass
            
    # Default rules si el catalog no las tiene
    planificacion_rules = rules.get("planificacion_section_names", ["planificacion", "planificación"])
    chatbot_rules = rules.get("chatbot_course_names", ["material chatbot"])
    ignore_rules = rules.get("ignore_section_names", ["tarea", "tareas", "foro", "foros", "general"])
    
    course_name_lower = course_name.lower().strip() if course_name else ""
    section_name_lower = section_name.lower().strip() if section_name else ""
    filename_lower = filename.lower().strip() if filename else ""
    
    if any(ignore in section_name_lower for ignore in ignore_rules):
        return None
        
    if any(p in section_name_lower for p in planificacion_rules) or (filename_lower and any(p in filename_lower for p in planificacion_rules)):
        return "planificacion"
        
    if any(c in course_name_lower for c in chatbot_rules) or (filename_lower and any(c in filename_lower for c in chatbot_rules)):
        return "boletin"
        
    if filename_lower and ("pa" in filename_lower.split() or "planificacion" in filename_lower or "calendario" in filename_lower):
        return "planificacion"

    return "otro"


async def sync_all_course_documents(
    course_id: int,
    año: str,
    carrera: str,
) -> dict[str, int]:
    """
    Escanea todos los archivos de un curso y los sincroniza.
    
    Returns:
        Diccionario con contadores (ej. {"archivos_procesados": 2, "chunks_indexados": 15})
    """
    moodle_client = get_moodle_client()
    catalog = get_catalog()
    carrera_id = catalog.normalize_carrera(carrera)

    logger.info("Escaneando contenidos del curso ID: %d", course_id)
    
    # Necesitamos el nombre del curso para inferir materias
    courses = await moodle_client.get_user_courses(1)  # Hack: get_courses genérico si es admin
    course_name = ""
    for c in courses:
        if c.get("id") == course_id:
            course_name = c.get("fullname", "")
            break
            
    materia_id = catalog.normalize_materia(course_name)
    contents = await moodle_client.get_course_contents(course_id)
    
    stats = {"archivos_procesados": 0, "archivos_ignorados": 0, "chunks_indexados": 0}
    
    vs = get_vector_store()
    chunker = DocumentChunker(vs, embedder=embed_text, config=ChunkingConfig())

    for section in contents:
        section_name = section.get("name", "")
        # Determinar doc_type de la sección, pero ignorar temporalmente si es None porque algún archivo podría ser útil
        section_doc_type = _determine_document_type(course_name, section_name)
            
        for module in section.get("modules", []):
            if module.get("modname") == "resource":
                for content in module.get("contents", []):
                    # Filtrar por tipos de archivo soportados
                    mime = content.get("mimetype", "")
                    if mime not in ["application/pdf", "text/plain", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
                        continue
                        
                    filename = content.get("filename", "")
                    file_url = content.get("fileurl", "")
                    
                    if not file_url:
                        continue
                        
                    doc_type = section_doc_type
                    if doc_type == "otro" or not doc_type:
                        doc_type = _determine_document_type(course_name, section_name, filename)
                        
                    if not doc_type:
                        logger.info("Ignorando archivo '%s' por reglas de clasificación.", filename)
                        continue

                    logger.info("Descargando archivo: %s (Sección: %s, Tipo: %s)", filename, section_name, doc_type)
                    file_bytes = await moodle_client.download_file(file_url)
                    
                    # Extraer texto temporalmente para usar la interfaz del chunker que espera un Path
                    # Hacemos mock de Path escribiendo un tmp file, pero como el chunker lo va a leer
                    # es más limpio adaptar DocumentChunker para aceptar texto directo, o guardar a disco.
                    # Por simplicidad y eficiencia de memoria, usamos el disco temp.
                    
                    import tempfile
                    from pathlib import Path
                    
                    suffix = ".pdf"
                    if "text/plain" in mime: suffix = ".txt"
                    elif "word" in mime: suffix = ".docx"
                    
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(file_bytes)
                        tmp_path = Path(tmp.name)
                        
                    try:
                        # Extra meta
                        # Intentar extraer vigencia de fechas si es boletin
                        vigente_hasta = None
                        if doc_type == "boletin":
                            # Hack rápido para demo: todo el 2026
                            vigente_hasta = "31-12-2026"
                            
                        # Intentar detectar la materia desde el nombre del archivo si no se pudo por el curso
                        final_materia_id = materia_id
                        if not final_materia_id:
                            materias_en_file = catalog.find_materias_in_text(filename)
                            if materias_en_file:
                                final_materia_id = materias_en_file[0]

                        meta = DocumentMetadata(
                            source=filename,
                            año_academico=año,
                            carrera=carrera,
                            carrera_id=carrera_id,
                            materia_id=final_materia_id,
                            module=section_name,
                            document_type=doc_type,
                            vigente_hasta=vigente_hasta
                        )
                        
                        # Limpiar versión anterior
                        vs.delete_by_source(filename)
                        
                        # Ingestar
                        chunks_count = await chunker.ingest(tmp_path, meta)
                        
                        if chunks_count > 0:
                            stats["archivos_procesados"] += 1
                            stats["chunks_indexados"] += chunks_count
                        else:
                            stats["archivos_ignorados"] += 1
                            
                    finally:
                        tmp_path.unlink(missing_ok=True)
                        
    logger.info("Sincronización del curso %d finalizada: %s", course_id, stats)
    return stats
