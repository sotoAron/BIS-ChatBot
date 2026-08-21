"""
app/rag/ingest.py — Pipeline de ingesta de documentos para el vector store RAG.

SOPORTA: PDF, TXT, DOCX
ESTRATEGIA DE CHUNKING: Sliding Window con solapamiento fijo en caracteres.
  - Respeta límites de párrafo/heading (no corta oraciones abruptamente).
  - Overlap configurable para preservar contexto entre chunks contiguos.

METADATOS POR CHUNK (obligatorios para filtrado estricto):
  - source:        nombre del archivo original
  - año_academico: string (ej. "2026")
  - carrera:       string (ej. "Ingeniería Informática")
  - module:        módulo/sección del documento (opcional)
  - chunk_index:   posición del chunk en el documento (para trazabilidad)
  - total_chunks:  número total de chunks del documento

IDs DE CHUNKS: {source_slug}_{año}_{carrera_slug}_{chunk_index}
  Formato determinista para poder re-ingestar (upsert) sin duplicados.
"""
import asyncio
import hashlib
import inspect
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

try:
    from pypdf import PdfReader as _PdfReader  # type: ignore
except ImportError:
    _PdfReader = None  # type: ignore

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Modelos de datos
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChunkingConfig:
    """Configuración del pipeline de chunking."""
    chunk_size: int    = 512    # Tamaño máximo de un chunk en caracteres
    chunk_overlap: int = 64     # Solapamiento con el chunk anterior en caracteres
    min_chunk_length: int = 40  # Longitud mínima para que un chunk sea válido


@dataclass
class DocumentMetadata:
    """Metadatos de un documento a ingestar."""
    source:        str          # Nombre del archivo
    año_academico: str          # Ej: "2026"
    carrera:       str          # Ej: "Informática"
    module:        str = ""     # Módulo o sección (opcional)

    def to_chunk_meta(self, chunk_index: int, total_chunks: int) -> dict:
        """Genera el dict de metadatos para un chunk específico."""
        return {
            "source":        self.source,
            "año_academico": self.año_academico,
            "carrera":       self.carrera,
            "module":        self.module,
            "chunk_index":   chunk_index,
            "total_chunks":  total_chunks,
        }


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
# Chunking semántico
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_whitespace(text: str) -> str:
    """Normaliza espacios múltiples y saltos de línea excesivos."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def chunk_text(text: str, config: ChunkingConfig) -> list[str]:
    """
    Divide un texto en chunks con solapamiento usando Sliding Window.

    ESTRATEGIA:
      1. Normalizar espacios y saltos de línea.
      2. Dividir por párrafos (doble salto de línea).
      3. Acumular párrafos hasta alcanzar chunk_size.
      4. Al emitir un chunk, retroceder chunk_overlap caracteres para el siguiente.

    Args:
        text:   Texto a segmentar.
        config: Configuración del chunking.

    Returns:
        Lista de strings — cada uno es un chunk listo para embedding.
    """
    if not text or not text.strip():
        return []

    text = _normalize_whitespace(text)
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        # Si el párrafo solo no cabe en un chunk, dividirlo por oraciones
        if para_len > config.chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if current_len + len(sent) + 1 > config.chunk_size and current:
                    chunk = " ".join(current)
                    if len(chunk) >= config.min_chunk_length:
                        chunks.append(chunk)
                    # Overlap: conservar los últimos chars
                    overlap_text = chunk[-config.chunk_overlap:] if config.chunk_overlap > 0 else ""
                    current = [overlap_text] if overlap_text.strip() else []
                    current_len = len(overlap_text)
                current.append(sent)
                current_len += len(sent) + 1
        else:
            if current_len + para_len + 2 > config.chunk_size and current:
                chunk = " ".join(current)
                if len(chunk) >= config.min_chunk_length:
                    chunks.append(chunk)
                overlap_text = chunk[-config.chunk_overlap:] if config.chunk_overlap > 0 else ""
                current = [overlap_text] if overlap_text.strip() else []
                current_len = len(overlap_text)

            current.append(para)
            current_len += para_len + 2

    # Emitir el último chunk
    if current:
        chunk = " ".join(current).strip()
        if len(chunk) >= config.min_chunk_length:
            chunks.append(chunk)

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# Generación de IDs deterministas
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Convierte texto a slug ASCII para usarlo en IDs."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)[:30]


def make_chunk_id(source: str, año: str, carrera: str, index: int) -> str:
    """
    Genera un ID determinista para un chunk.
    Formato: {source_slug}_{año}_{carrera_slug}_{index:04d}

    Determinista: re-ingestar el mismo documento produce los mismos IDs
    → ChromaDB hace upsert automático (sin duplicados).
    """
    src = _slugify(Path(source).stem)
    car = _slugify(carrera)
    return f"{src}_{año}_{car}_{index:04d}"


# ══════════════════════════════════════════════════════════════════════════════
# Chunking Jerárquico por Encabezados Markdown (Fase 4)
# ══════════════════════════════════════════════════════════════════════════════

_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)

# Parámetros del chunker jerárquico Markdown
_MD_MAX_CHARS   = 3000   # Aumentado para evitar cortar tablas Markdown
_MD_OVERLAP     = 300    # Solapamiento aproximado en caracteres
_MD_MIN_LENGTH  = 50     # Longitud mínima de un chunk


def chunk_markdown_text(md_text: str) -> list[str]:
    """
    Divisor jerárquico por encabezados Markdown.

    ESTRATEGIA:
      1. Identifica los encabezados (# … ######) como delimitadores de sección.
      2. Acumula el texto bajo cada encabezado como un bloque.
      3. Inyecta el título de la sección al inicio de cada chunk (para no
         perder el contexto del bloque en preguntas de recuperación).
      4. Si un bloque supera _MD_MAX_CHARS (1500 chars), lo re-divide
         con solapamiento de _MD_OVERLAP (250 chars) respetando oraciones.

    Args:
        md_text: Texto completo en formato Markdown (salida de pymupdf4llm).

    Returns:
        Lista de strings — cada uno es un chunk con contexto de sección.
    """
    md_text = _normalize_whitespace(md_text)
    lines = md_text.split("\n")

    # Separar el texto en bloques por encabezados
    sections: list[tuple[str, str]] = []  # (heading_prefix, block_text)
    current_heading = ""                   # título de la sección en curso
    current_lines: list[str] = []

    for line in lines:
        m = _MD_HEADER_RE.match(line)
        if m:
            # Cerrar el bloque anterior
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.strip()   # e.g. "## Cronograma"
            current_lines = []
        else:
            current_lines.append(line)

    # Cerrar el último bloque
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    chunks: list[str] = []

    for heading, body in sections:
        if not body.strip():
            continue

        # Prefijo de contexto: inyectar el encabezado al inicio del chunk
        prefix = f"{heading}\n" if heading else ""
        full_block = f"{prefix}{body}"

        if len(full_block) <= _MD_MAX_CHARS:
            if len(full_block) >= _MD_MIN_LENGTH:
                chunks.append(full_block)
        else:
            # Re-dividir bloques largos (ej. tablas con muchas filas)
            sub_chunks = _split_long_block(full_block, prefix)
            chunks.extend(sub_chunks)

    return chunks


def _split_long_block(text: str, section_prefix: str) -> list[str]:
    """
    Divide un bloque largo en sub-chunks de tamaño <= _MD_MAX_CHARS,
    dividiendo por líneas (\n) para no romper la sintaxis Markdown de las tablas.
    Inyecta section_prefix al inicio de cada sub-chunk.
    """
    lines = text.split("\n")
    sub_chunks: list[str] = []
    current_parts: list[str] = []
    current_len = len(section_prefix)

    for line in lines:
        if current_len + len(line) + 1 > _MD_MAX_CHARS and current_parts:
            chunk = section_prefix + "\n".join(current_parts)
            if len(chunk) >= _MD_MIN_LENGTH:
                sub_chunks.append(chunk)
            
            # Solapamiento: conservar las últimas 3 líneas
            overlap_lines = current_parts[-3:] if len(current_parts) >= 3 else current_parts
            current_parts = overlap_lines
            current_len = len(section_prefix) + sum(len(l) + 1 for l in current_parts)
            
        current_parts.append(line)
        current_len += len(line) + 1

    # Último bloque residual
    if current_parts:
        chunk = section_prefix + "\n".join(current_parts)
        # Solo agregar si tiene contenido real más allá del prefix y overlap
        if len(chunk) > len(section_prefix) + 20:
            sub_chunks.append(chunk)

    return sub_chunks


# ══════════════════════════════════════════════════════════════════════════════
# DocumentChunker — Orquestador del pipeline
# ══════════════════════════════════════════════════════════════════════════════

class DocumentChunker:
    """
    Pipeline completo: extracción de texto → chunking → embedding → indexación.

    Args:
        vector_store: Instancia de VectorStore (ChromaDB wrapper).
        embedder:     Función async(text) → list[float].
        config:       Configuración del chunking. Por defecto: 512/64 chars.
    """

    def __init__(
        self,
        vector_store,
        embedder: Callable,
        config: ChunkingConfig | None = None,
    ) -> None:
        self._store    = vector_store
        self._embedder = embedder
        self._config   = config or ChunkingConfig()

    async def ingest(self, path: Path, metadata: DocumentMetadata) -> int:
        """
        Ingesta un documento completo al vector store.

        Pasos:
          1. Extraer texto del documento (PDF/TXT/DOCX).
          2. Segmentar en chunks con overlap.
          3. Generar embeddings para cada chunk (en paralelo).
          4. Indexar en ChromaDB con metadatos.

        Args:
            path:     Ruta al archivo a ingestar.
            metadata: Metadatos del documento.

        Returns:
            Número de chunks efectivamente indexados.
        """
        logger.info("Iniciando ingesta: %s (%s / %s)", path.name, metadata.carrera, metadata.año_academico)

        # 1. Extraer texto
        raw_text = extract_text(path)
        if not raw_text.strip():
            logger.warning("Documento vacío o sin texto extraíble: %s", path.name)
            return 0

        # 2. Chunking
        chunks = chunk_text(raw_text, self._config)
        if not chunks:
            logger.warning("Ningún chunk generado para: %s", path.name)
            return 0

        total = len(chunks)
        logger.info("Chunks generados: %d para %s", total, path.name)

        # 3. Embeddings en paralelo
        # IMPORTANTE: asyncio.to_thread es para funciones SÍNCRONAS (CPU-bound).
        # Si el embedder YA es async, se llama directo para que gather lo awaitee.
        # Si es síncrono (np, cpu), se envuelve en to_thread para no bloquear el loop.
        embeddings = await asyncio.gather(
            *[
                self._embedder(chunk) if inspect.iscoroutinefunction(self._embedder)
                else asyncio.to_thread(self._embedder, chunk)
                for chunk in chunks
            ]
        )

        # Normalizar embeddings a listas de float
        processed_embeddings = []
        for emb in embeddings:
            if hasattr(emb, "tolist"):
                processed_embeddings.append(emb.tolist())
            else:
                processed_embeddings.append(list(emb))

        # 4. Preparar para ChromaDB
        ids       = [make_chunk_id(metadata.source, metadata.año_academico, metadata.carrera, i) for i in range(total)]
        metadatas = [metadata.to_chunk_meta(i, total) for i in range(total)]

        # 5. Indexar (batch para eficiencia)
        self._store.add(
            documents=chunks,
            embeddings=processed_embeddings,
            metadatas=metadatas,
            ids=ids,
        )

        logger.info("Indexados %d chunks de '%s' en ChromaDB.", total, path.name)
        return total


# ═══════════════════════════════════════════════════════════════════════════════
# Backward compatibility: clase PDFIngestor (alias de DocumentChunker)
# ═══════════════════════════════════════════════════════════════════════════════

class PDFIngestor(DocumentChunker):
    """
    Alias de DocumentChunker para compatibilidad con código existente.
    Acepta los parámetros originales del stub de Fase 2.
    """

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
        meta = DocumentMetadata(
            source=pdf_path.name,
            año_academico=año_academico,
            carrera=carrera,
            module=module,
        )
        return await super().ingest(pdf_path, meta)
