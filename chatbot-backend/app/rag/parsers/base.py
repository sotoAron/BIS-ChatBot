"""
app/rag/parsers/base.py — Clase base y factory para parsers de documentos.

Patrón Strategy: cada document_type tiene su propio parser que implementa
la interfaz `parse()`, pero todos producen el mismo esquema de salida
(list[ChunkMetadata]).
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.rag.models import ChunkMetadata

logger = logging.getLogger(__name__)


class DocumentParser(ABC):
    """Interfaz base para parsers de documentos."""

    @abstractmethod
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
        """
        Parsea un documento y retorna una lista de chunks con metadata.

        Args:
            text:           Texto completo del documento (ya extraído del PDF).
            source:         Nombre del archivo original.
            carrera_id:     ID canónico de la carrera (para planificaciones).
            materia_id:     ID canónico de la materia (para planificaciones).
            ciclo_lectivo:  Año del ciclo lectivo.
            comision_id:    ID de la comisión (si aplica).
            nivel:          Nivel/año de la materia en el plan.
            cuatrimestre:   "1ro" | "2do" | "anual" | None.
            extra_metadata: Metadata adicional del contexto de ingesta.

        Returns:
            Lista de ChunkMetadata con texto original, contextualizado y metadata.
        """
        ...


class FallbackParser(DocumentParser):
    """
    Parser de fallback para tipos de documento no reconocidos.

    Usa chunking por párrafos con overlap, similar al approach original
    pero generando ChunkMetadata con el nuevo esquema. Loggea un WARNING
    para que se note que se está usando el fallback.
    """

    MAX_CHUNK_CHARS = 1500
    MIN_CHUNK_CHARS = 50

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
        logger.warning(
            "Usando FallbackParser para '%s'. Considere implementar un parser "
            "específico para este tipo de documento.", source
        )

        import re
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

        chunks: list[ChunkMetadata] = []
        current_parts: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 2 > self.MAX_CHUNK_CHARS and current_parts:
                chunk_text = "\n\n".join(current_parts)
                if len(chunk_text) >= self.MIN_CHUNK_CHARS:
                    cm = ChunkMetadata(
                        document_type=extra_metadata.get("document_type", "otro") if extra_metadata else "otro",
                        source=source,
                        carrera_id=carrera_id,
                        materia_id=materia_id,
                        ciclo_lectivo=ciclo_lectivo,
                        comision_id=comision_id,
                        nivel=nivel,
                        cuatrimestre=cuatrimestre,
                        seccion="general",
                        subseccion=f"parte_{len(chunks) + 1}",
                        texto_original=chunk_text,
                    )
                    cm.generate_contextualized_text()
                    cm.generate_chunk_id()
                    chunks.append(cm)
                current_parts = []
                current_len = 0

            current_parts.append(para)
            current_len += len(para) + 2

        # Último chunk
        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            if len(chunk_text) >= self.MIN_CHUNK_CHARS:
                cm = ChunkMetadata(
                    document_type=extra_metadata.get("document_type", "otro") if extra_metadata else "otro",
                    source=source,
                    carrera_id=carrera_id,
                    materia_id=materia_id,
                    ciclo_lectivo=ciclo_lectivo,
                    comision_id=comision_id,
                    nivel=nivel,
                    cuatrimestre=cuatrimestre,
                    seccion="general",
                    subseccion=f"parte_{len(chunks) + 1}",
                    texto_original=chunk_text,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)

        return chunks


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════

def get_parser(document_type: str) -> DocumentParser:
    """
    Factory: retorna el parser adecuado según el tipo de documento.

    Si no hay un parser específico para el tipo, retorna FallbackParser
    con un log de warning.
    """
    from app.rag.parsers.planificacion_parser import PlanificacionParser
    from app.rag.parsers.boletin_parser import BoletinParser

    parsers: dict[str, type[DocumentParser]] = {
        "planificacion": PlanificacionParser,
        "boletin": BoletinParser,
    }

    parser_cls = parsers.get(document_type)
    if parser_cls is None:
        logger.warning(
            "No hay parser específico para document_type='%s'. Usando FallbackParser.",
            document_type,
        )
        return FallbackParser()

    return parser_cls()
