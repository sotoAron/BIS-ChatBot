"""
app/rag/models.py — Modelos de datos unificados para el pipeline de chunking estructural.

Define el esquema de metadata por chunk que soporta tanto planificaciones
(con materia_id singular) como boletines (con arrays de carreras/materias).

Todos los tipos de documento vuelcan al mismo esquema; los campos no
aplicables se dejan en None/vacío.
"""
from dataclasses import dataclass, field
from typing import Optional
import hashlib
import re
import unicodedata


# ══════════════════════════════════════════════════════════════════════════════
# Esquema unificado de metadata por chunk
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChunkMetadata:
    """
    Metadata completa de un chunk para el vector store.

    Soporta planificaciones (materia_id singular, comision_id) y
    boletines/documentos sin template (arrays de carreras/materias,
    alcance, vigencia temporal).
    """
    # ── Identificación ────────────────────────────────────────────────────────
    chunk_id: str = ""                       # Se genera automáticamente si vacío

    # ── Clasificación de documento ────────────────────────────────────────────
    document_type: str = "planificacion"     # "planificacion" | "boletin" | "reglamento" | ...
    source: str = ""                         # Nombre archivo original (trazabilidad)

    # ── Ubicación institucional ───────────────────────────────────────────────
    facultad: str = "UTN-FRRe"              # Facultad (hardcoded por ahora)
    carrera_id: Optional[str] = None         # ID canónico para planificaciones (singular)
    materia_id: Optional[str] = None         # ID canónico para planificaciones (singular)
    nivel: Optional[int] = None              # Año/nivel de la materia en el plan
    ciclo_lectivo: int = 2026
    cuatrimestre: Optional[str] = None       # "1ro" | "2do" | "anual" | None
    comision_id: Optional[str] = None        # Para planificaciones con múltiples comisiones

    # ── Estructura del documento ──────────────────────────────────────────────
    seccion: str = ""                        # "cronograma" | "fundamentacion" | ...
    subseccion: Optional[str] = None         # "semana_9" | "10.1_aprobacion_directa" | ...

    # ── Campos específicos de boletines ───────────────────────────────────────
    alcance: Optional[str] = None            # "facultad" | "carrera" | "materia"
    carreras_relacionadas: list[str] = field(default_factory=list)
    materias_relacionadas: list[str] = field(default_factory=list)
    comision_tipo: Optional[str] = None      # "CPC" | "CR" | "integrada"
    fecha_publicacion: Optional[str] = None
    vigente_hasta: Optional[str] = None

    # ── Contenido ─────────────────────────────────────────────────────────────
    texto_original: str = ""
    texto_contextualizado: str = ""

    def generate_chunk_id(self) -> str:
        """
        Genera un ID determinista basado en el contenido y la posición estructural.

        Formato: {doc_type}_{materia_id|source}_{seccion}_{subseccion}_{hash6}
        Determinista: re-ingestar el mismo documento produce los mismos IDs.
        """
        key_parts = [
            self.document_type,
            self.materia_id or _slugify(self.source),
            self.seccion,
            self.subseccion or "",
            self.comision_id or "",
        ]
        key_str = "|".join(str(p) for p in key_parts)
        content_hash = hashlib.md5(
            (key_str + "|" + self.texto_original[:200]).encode("utf-8")
        ).hexdigest()[:8]

        slug_parts = [
            self.document_type[:4],
            _slugify(self.materia_id or self.source)[:20],
            _slugify(self.seccion)[:20],
        ]
        if self.subseccion:
            slug_parts.append(_slugify(self.subseccion)[:15])
        slug_parts.append(content_hash)

        self.chunk_id = "_".join(p for p in slug_parts if p)
        return self.chunk_id

    def generate_contextualized_text(self) -> str:
        """
        Genera una síntesis semántica para el texto que será embebido.
        Esto agrega alto valor semántico frente a un log crudo, 
        mejorando el ranking de recuperación (RAG).
        """
        if not self.texto_original:
            return ""

        parts = []
        if self.document_type == "planificacion":
            materia_str = f"de la materia {self.materia_id} " if self.materia_id else ""
            carrera_str = f"({self.carrera_id}) " if self.carrera_id else ""
            comision_str = f"comisión {self.comision_id} " if self.comision_id else ""
            
            parts.append(f"Este fragmento corresponde a la Planificación Anual {materia_str}{carrera_str}{comision_str}para el Ciclo Lectivo {self.ciclo_lectivo}.")
            
            if self.seccion:
                sec_desc = {
                    "cronograma": "Contiene el calendario semana a semana con fechas de clases y exámenes.",
                    "sistema_acreditacion": "Contiene los criterios y reglas para aprobar, regularizar y promocionar la materia.",
                    "bibliografia": "Contiene los libros y referencias recomendadas para la cursada.",
                    "fundamentacion": "Contiene los motivos y el propósito general de la asignatura en la carrera.",
                }.get(self.seccion, f"Pertenece a la sección '{self.seccion}'.")
                parts.append(sec_desc)

        elif self.document_type == "boletin":
            parts.append(f"Este fragmento corresponde a un Boletín Académico (Ciclo Lectivo {self.ciclo_lectivo}).")
            if self.carreras_relacionadas or self.materias_relacionadas:
                c = ", ".join(self.carreras_relacionadas) if self.carreras_relacionadas else "varias"
                m = ", ".join(self.materias_relacionadas) if self.materias_relacionadas else "varias"
                parts.append(f"Aplica a las carreras: {c} y materias: {m}.")
            if self.vigente_hasta:
                parts.append(f"Esta información es válida hasta {self.vigente_hasta}.")
        else:
            parts.append(f"Documento institucional de tipo {self.document_type}.")
            if self.seccion:
                parts.append(f"Sección: {self.seccion}.")

        header = " ".join(parts)
        self.texto_contextualizado = f"{header}\n\nContenido a continuación:\n{self.texto_original}"
        return self.texto_contextualizado

    def to_chroma_metadata(self) -> dict:
        """
        Convierte a dict plano para ChromaDB.
        ChromaDB solo soporta str, int, float, bool como valores de metadata.
        Las listas se serializan como strings separados por coma.
        """
        meta = {
            "document_type": self.document_type,
            "source": self.source,
            "facultad": self.facultad,
            "ciclo_lectivo": self.ciclo_lectivo,
            "seccion": self.seccion,
        }

        # Campos opcionales (solo incluir si tienen valor)
        if self.carrera_id:
            meta["carrera_id"] = self.carrera_id
        if self.materia_id:
            meta["materia_id"] = self.materia_id
        if self.nivel is not None:
            meta["nivel"] = self.nivel
        if self.cuatrimestre:
            meta["cuatrimestre"] = self.cuatrimestre
        if self.comision_id:
            meta["comision_id"] = self.comision_id
        if self.subseccion:
            meta["subseccion"] = self.subseccion
        if self.alcance:
            meta["alcance"] = self.alcance
        if self.carreras_relacionadas:
            meta["carreras_relacionadas"] = ",".join(self.carreras_relacionadas)
        if self.materias_relacionadas:
            meta["materias_relacionadas"] = ",".join(self.materias_relacionadas)
        if self.comision_tipo:
            meta["comision_tipo"] = self.comision_tipo
        if self.fecha_publicacion:
            meta["fecha_publicacion"] = self.fecha_publicacion
        if self.vigente_hasta:
            meta["vigente_hasta"] = self.vigente_hasta

        return meta


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Convierte texto a slug ASCII para usarlo en IDs."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)
