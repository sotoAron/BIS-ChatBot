"""
app/rag/parsers/boletin_parser.py — Parser para boletines y documentos no estructurados.

Implementa heurísticas de segmentación por bloques temáticos y
sub-chunking por entidades (carreras/materias) mencionadas en el texto,
usando el catálogo maestro de normalización.
"""
import logging
import re
from typing import Optional

from app.rag.models import ChunkMetadata
from app.rag.parsers.base import DocumentParser
from app.rag.catalog import get_catalog

logger = logging.getLogger(__name__)

# Límite de caracteres para dividir bloques largos
_MAX_CHUNK_CHARS = 1000

class BoletinParser(DocumentParser):
    """
    Parser para boletines académicos.
    
    Estrategia:
      1. Dividir el documento en bloques temáticos usando heurísticas 
         (encabezados Markdown, títulos en negrita).
      2. Para cada bloque, detectar qué carreras/materias se mencionan
         (usando el catálogo maestro).
      3. Generar 1 chunk por bloque. Si menciona múltiples entidades, 
         se asocia a la lista correspondiente en la metadata.
    """

    def parse(
        self,
        text: str,
        source: str,
        carrera_id: Optional[str] = None,
        materia_id: Optional[str] = None,
        ciclo_lectivo: int = 2026,
        comision_id: Optional[str] = None,
        nivel: Optional[int] = None,
        cuatrimestre: Optional[str] = None,
        extra_metadata: Optional[dict] = None,
    ) -> list[ChunkMetadata]:
        
        # Metadata extra típica de boletines
        extra = extra_metadata or {}
        fecha_pub = extra.get("fecha_publicacion")
        vigente = extra.get("vigente_hasta")
        
        # 1. Segmentación en bloques temáticos
        blocks = self._split_into_blocks(text)
        
        if not blocks:
            logger.warning("BoletinParser: No se detectaron bloques en '%s'. Fallback a un solo chunk.", source)
            blocks = [text]
            
        catalog = get_catalog()
        chunks: list[ChunkMetadata] = []
        
        for i, block_text in enumerate(blocks):
            if len(block_text.strip()) < 30:
                continue
                
            # 2. Detectar entidades (carreras, materias) en este bloque
            materias = catalog.find_materias_in_text(block_text)
            carreras = catalog.find_carreras_in_text(block_text)
            
            # Si el documento tiene un alcance global asignado, añadirlo
            if carrera_id and carrera_id not in carreras:
                carreras.append(carrera_id)
            if materia_id and materia_id not in materias:
                materias.append(materia_id)
                
            # Determinar alcance
            alcance = "facultad"
            if carreras and not materias:
                alcance = "carrera"
            elif materias:
                alcance = "materia"
                
            # 3. Subdividir si es muy largo
            if len(block_text) > _MAX_CHUNK_CHARS:
                sub_blocks = self._split_by_paragraphs(block_text)
            else:
                sub_blocks = [block_text]
                
            for j, sub_text in enumerate(sub_blocks):
                subseccion = f"bloque_{i+1}"
                if len(sub_blocks) > 1:
                    subseccion += f"_parte_{j+1}"
                    
                cm = ChunkMetadata(
                    document_type="boletin",
                    source=source,
                    ciclo_lectivo=ciclo_lectivo,
                    seccion="contenido_boletin",
                    subseccion=subseccion,
                    alcance=alcance,
                    carreras_relacionadas=carreras,
                    materias_relacionadas=materias,
                    fecha_publicacion=fecha_pub,
                    vigente_hasta=vigente,
                    texto_original=sub_text,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)
                
        logger.info(
            "BoletinParser: '%s' → %d bloques iniciales, %d chunks generados.",
            source, len(blocks), len(chunks),
        )
        return chunks

    def _split_into_blocks(self, text: str) -> list[str]:
        """
        Divide el texto en bloques usando heurísticas:
          - Encabezados Markdown (##, ###)
          - Líneas cortas completamente en MAYÚSCULAS
          - Líneas en **negrita**
        """
        # Expresión regular combinada:
        # 1. Encabezados MD: ^\s*#{2,4}\s+.+
        # 2. Negrita completa: ^\s*\*\*.+\*\*\s*$
        # 3. Mayúsculas (mínimo 10 chars, sin minúsculas): ^\s*[A-ZÁÉÍÓÚÑ\s\-\.]{10,}\s*$
        
        pattern = r"(?:^|\n)(?:\s*#{2,4}\s+.+|\s*\*\*.+\*\*\s*|\s*[A-ZÁÉÍÓÚÑ0-9\s\-\.]{10,}\s*)(?=\n|$)"
        
        # Encontrar divisiones
        splits = list(re.finditer(pattern, text))
        
        if not splits:
            return [text.strip()]
            
        blocks = []
        
        # Texto antes del primer encabezado
        if splits[0].start() > 0:
            pre_text = text[:splits[0].start()].strip()
            if pre_text:
                blocks.append(pre_text)
                
        for i, match in enumerate(splits):
            start = match.start()
            # El texto del bloque incluye el encabezado
            end = splits[i+1].start() if i+1 < len(splits) else len(text)
            block = text[start:end].strip()
            if block:
                blocks.append(block)
                
        return blocks

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """Divide un texto largo en párrafos."""
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks = []
        current_parts = []
        current_len = 0
        
        for para in paragraphs:
            if current_len + len(para) + 2 > _MAX_CHUNK_CHARS and current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_len = 0
                
            current_parts.append(para)
            current_len += len(para) + 2
            
        if current_parts:
            chunks.append("\n\n".join(current_parts))
            
        return chunks
