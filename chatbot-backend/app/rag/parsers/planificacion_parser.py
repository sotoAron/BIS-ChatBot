"""
app/rag/parsers/planificacion_parser.py — Parser estructural para Planificaciones Anuales UTN.

Detecta las 13 secciones numeradas del template institucional (mandado por
Rectorado UTN) usando regex/reglas sobre el texto extraído. NO usa LLM.

SECCIONES DEL TEMPLATE:
   1. Datos Descriptivos
   2. Estructura de la cátedra
   3. Fundamentación
   4. Resultados de Aprendizaje previos requeridos
   5. Competencias y Capacidades vinculadas
   6. Programa Analítico, Unidades Temáticas
   7. Propuesta de Enseñanza-Aprendizaje (tabla RA x Unidad x Estrategias)
   8. Recomendaciones para el estudio (incluye subsección IA responsable)
   9. Detalle y cronograma de trabajo de campo/pasantías
  10. Sistema de Acreditación (10.1 Aprobación Directa, 10.2 Aprobación de Cursada)
  11. Cronograma (tabla semana a semana)
  12. Bibliografía según Normas APA
  13. Anexo

REGLAS DE CHUNKING (por tipo de sección):
  - Secciones cortas (1, 3, 8, 9): 1 chunk completo
  - Secciones con tabla por fila (2, 4, 5, 7, 11): 1 chunk por fila/entrada
  - Secciones con sub-bloques (6, 10, 12, 13): 1 chunk por sub-bloque
"""
import logging
import re
from typing import Optional

from app.rag.models import ChunkMetadata
from app.rag.parsers.base import DocumentParser

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Regex para detectar las 13 secciones del template UTN
# ══════════════════════════════════════════════════════════════════════════════

# Patrón tolerante: número (1-13), punto o paréntesis opcional, separador,
# y el título de la sección (parcial, para tolerar variaciones de OCR).
_SECTION_PATTERNS = [
    (1,  "datos_descriptivos",      r"(?:1\W+)(?:datos\s+descriptivos|identificaci[oó]n)"),
    (2,  "estructura_catedra",      r"(?:2\W+)(?:estructura\s+(?:de\s+la\s+)?c[aá]tedra)"),
    (3,  "fundamentacion",          r"(?:3\W+)(?:fundamentaci[oó]n)"),
    (4,  "ra_previos",              r"(?:4\W+)(?:resultados\s+de\s+aprendizaje\s+previos)"),
    (5,  "competencias",            r"(?:5\W+)(?:competencias\s+y?\s*capacidades)"),
    (6,  "programa_analitico",      r"(?:6\W+)(?:programa\s+anal[ií]tico|unidades?\s+tem[aá]ticas?)"),
    (7,  "propuesta_ensenanza",     r"(?:7\W+)(?:propuesta\s+para\s+el\s+desarrollo|procesos?\s+de\s+ense[ñn]anza)"),
    (8,  "recomendaciones_estudio", r"(?:8\W+)(?:recomendaciones?\s+para\s+el\s+estudio)"),
    (9,  "trabajo_campo",           r"(?:9\W+)(?:detalle\s+y?\s*cronograma\s+de\s+trabajo|trabajo\s+de\s+campo|pasant[ií]as?)"),
    (10, "sistema_acreditacion",    r"(?:10\W+)(?:sistema\s+de\s+acreditaci[oó]n)"),
    (11, "cronograma",              r"(?:11\W+)(?:cronograma)"),
    (12, "bibliografia",            r"(?:12\W+)(?:bibliograf[ií]a)"),
    (13, "anexo",                   r"(?:13\W+)(?:anexo)"),
]

# Subsecciones de la sección 10
_SUBSECTION_10_PATTERNS = [
    ("10.1_aprobacion_directa",   r"(?:10\W*1\W+)(?:aprobaci[oó]n\s+directa|promoci[oó]n)"),
    ("10.2_aprobacion_cursada",   r"(?:10\W*2\W+)(?:aprobaci[oó]n\s+(?:de\s+)?cursada|regularizaci[oó]n)"),
]

# Límite de tamaño para decidir si subdividir un chunk
_MAX_CHUNK_CHARS = 800


class PlanificacionParser(DocumentParser):
    """
    Parser determinístico para Planificaciones Anuales UTN.

    Detecta las 13 secciones del template institucional usando regex,
    luego aplica reglas de chunking diferenciadas por tipo de sección.
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

        # 1. Detectar las secciones en el texto
        sections = self._detect_sections(text)

        # 2. Validar que se encontraron secciones
        found_nums = [num for num, _, _, _ in sections]
        missing = [n for n in range(1, 14) if n not in found_nums]
        if missing:
            logger.warning(
                "PlanificacionParser: Secciones faltantes en '%s': %s (encontradas: %s)",
                source, missing, found_nums,
            )
        if not sections:
            logger.error(
                "PlanificacionParser: No se detectó NINGUNA sección en '%s'. "
                "Verificar que el documento sea una planificación UTN válida.",
                source,
            )
            # Fallback: usar chunking por párrafos
            return self._chunk_by_paragraphs(
                text.strip(),
                document_type="planificacion",
                source=source,
                carrera_id=carrera_id,
                materia_id=materia_id,
                ciclo_lectivo=ciclo_lectivo,
                comision_id=comision_id,
                nivel=nivel,
                cuatrimestre=cuatrimestre,
                seccion="documento_completo"
            )

        # 3. Aplicar reglas de chunking por tipo de sección
        all_chunks: list[ChunkMetadata] = []

        for sec_num, sec_id, sec_title, sec_text in sections:
            sec_text = sec_text.strip()
            if not sec_text or len(sec_text) < 30:
                continue

            base_kwargs = dict(
                document_type="planificacion",
                source=source,
                carrera_id=carrera_id,
                materia_id=materia_id,
                ciclo_lectivo=ciclo_lectivo,
                comision_id=comision_id,
                nivel=nivel,
                cuatrimestre=cuatrimestre,
                seccion=sec_id,
            )

            if sec_num in (1, 3, 9):
                # Secciones cortas → 1 chunk completo
                chunks = self._chunk_single(sec_text, **base_kwargs)
            elif sec_num == 2:
                # Estructura de cátedra → 1 chunk por docente/fila
                chunks = self._chunk_table_rows(sec_text, sec_id, **base_kwargs)
            elif sec_num in (4, 5):
                # Correlativas / Competencias → 1 chunk por fila
                chunks = self._chunk_table_rows(sec_text, sec_id, **base_kwargs)
            elif sec_num == 6:
                # Programa Analítico → 1 chunk por Unidad Temática
                chunks = self._chunk_by_units(sec_text, **base_kwargs)
            elif sec_num == 7:
                # Propuesta de Enseñanza → 1 chunk por RA (fila completa)
                chunks = self._chunk_table_rows(sec_text, sec_id, **base_kwargs)
            elif sec_num == 8:
                # Recomendaciones → 1 chunk general + 1 chunk IA responsable
                chunks = self._chunk_recomendaciones(sec_text, **base_kwargs)
            elif sec_num == 10:
                # Sistema Acreditación → sub-secciones 10.1 y 10.2
                chunks = self._chunk_acreditacion(sec_text, **base_kwargs)
            elif sec_num == 11:
                # Cronograma → 1 chunk por semana/fila
                chunks = self._chunk_cronograma(sec_text, **base_kwargs)
            elif sec_num == 12:
                # Bibliografía → 1 chunk básica + 1 recursos digitales
                chunks = self._chunk_bibliografia(sec_text, **base_kwargs)
            elif sec_num == 13:
                # Anexo → 1 chunk por sub-bloque
                chunks = self._chunk_by_subheadings(sec_text, **base_kwargs)
            else:
                chunks = self._chunk_single(sec_text, **base_kwargs)

            all_chunks.extend(chunks)

        logger.info(
            "PlanificacionParser: '%s' → %d secciones detectadas, %d chunks generados.",
            source, len(sections), len(all_chunks),
        )
        return all_chunks

    # ══════════════════════════════════════════════════════════════════════════
    # Detección de secciones
    # ══════════════════════════════════════════════════════════════════════════

    def _detect_sections(self, text: str) -> list[tuple[int, str, str, str]]:
        """
        Detecta las 13 secciones en el texto.

        Returns:
            Lista de (num, section_id, title_match, section_text) ordenada por
            posición en el texto.
        """
        # Encontrar las posiciones de cada sección
        matches: list[tuple[int, str, int, int]] = []  # (num, id, start, title_end)

        for sec_num, sec_id, pattern in _SECTION_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                matches.append((sec_num, sec_id, m.start(), m.end()))

        if not matches:
            return []

        # Ordenar por posición en el texto
        matches.sort(key=lambda x: x[2])

        # Extraer el texto de cada sección (desde el final del título hasta el inicio de la siguiente)
        sections = []
        for i, (sec_num, sec_id, start, title_end) in enumerate(matches):
            # El texto de la sección va desde el final del título hasta el inicio de la siguiente sección
            if i + 1 < len(matches):
                next_start = matches[i + 1][2]
                sec_text = text[title_end:next_start]
            else:
                sec_text = text[title_end:]

            # Obtener el título original
            title = text[start:title_end].strip()
            sections.append((sec_num, sec_id, title, sec_text))

        return sections

    # ══════════════════════════════════════════════════════════════════════════
    # Estrategias de chunking por tipo de sección
    # ══════════════════════════════════════════════════════════════════════════

    def _chunk_single(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """1 chunk con todo el contenido de la sección."""
        # Si es demasiado largo, dividir por párrafos
        if len(text) > _MAX_CHUNK_CHARS:
            return self._chunk_by_paragraphs(text, **kwargs)

        cm = ChunkMetadata(texto_original=text, **kwargs)
        cm.generate_contextualized_text()
        cm.generate_chunk_id()
        return [cm]

    def _chunk_table_rows(self, text: str, sec_id: str, **kwargs) -> list[ChunkMetadata]:
        """
        1 chunk por fila de tabla Markdown.
        Si no hay tabla, fallback a chunk_single.
        """
        # Buscar tabla Markdown
        table_lines = [l for l in text.split("\n") if l.strip().startswith("|")]

        if len(table_lines) < 3:  # header + separator + al menos 1 fila
            return self._chunk_single(text, **kwargs)

        # Separar header de la tabla
        header_line = table_lines[0]
        separator = table_lines[1] if re.match(r"^\|[\s\-:|]+\|", table_lines[1]) else None
        data_rows = table_lines[2:] if separator else table_lines[1:]

        # Texto antes de la tabla
        pre_table_text = text[:text.find(header_line)].strip()

        chunks: list[ChunkMetadata] = []

        # Si hay texto previo a la tabla, incluirlo como chunk de contexto
        if pre_table_text and len(pre_table_text) >= 30:
            cm = ChunkMetadata(
                texto_original=pre_table_text,
                subseccion="encabezado",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        # 1 chunk por fila de datos, incluyendo el header de la tabla para contexto
        table_header = f"{header_line}\n{separator}" if separator else header_line
        for i, row in enumerate(data_rows):
            if not row.strip() or row.strip() == "|":
                continue
            row_with_header = f"{table_header}\n{row}"
            cm = ChunkMetadata(
                texto_original=row_with_header,
                subseccion=f"fila_{i + 1}",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_by_units(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        1 chunk por Unidad Temática (Sección 6 - Programa Analítico).
        Detecta encabezados como "Unidad I:", "Unidad 1:", "UNIDAD TEMÁTICA 1", etc.
        """
        unit_pattern = r"(?:^|\n)\s*(?:unidad\s+(?:tem[aá]tica\s+)?(?:[IVX]+|\d+)[\.\:\s\-])"
        splits = re.split(unit_pattern, text, flags=re.IGNORECASE)

        if len(splits) <= 1:
            # No se encontraron unidades, intentar por headings markdown
            return self._chunk_by_subheadings(text, **kwargs)

        # Reconstuir con los delimitadores
        unit_matches = list(re.finditer(unit_pattern, text, re.IGNORECASE))
        chunks: list[ChunkMetadata] = []

        # Texto antes de la primera unidad
        pre_text = text[:unit_matches[0].start()].strip() if unit_matches else ""
        if pre_text and len(pre_text) >= 30:
            cm = ChunkMetadata(
                texto_original=pre_text,
                subseccion="introduccion",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        for i, match in enumerate(unit_matches):
            start = match.start()
            end = unit_matches[i + 1].start() if i + 1 < len(unit_matches) else len(text)
            unit_text = text[start:end].strip()

            if len(unit_text) < 30:
                continue

            cm = ChunkMetadata(
                texto_original=unit_text,
                subseccion=f"unidad_{i + 1}",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_recomendaciones(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Sección 8: 1 chunk general + 1 chunk separado para "Uso responsable
        y ético de la IA" (si existe).
        """
        ia_pattern = r"(?:uso\s+responsable\s+y?\s*[eé]tico\s+de\s+la\s+i\.?a\.?|inteligencia\s+artificial)"
        ia_match = re.search(ia_pattern, text, re.IGNORECASE)

        chunks: list[ChunkMetadata] = []

        if ia_match:
            general = text[:ia_match.start()].strip()
            ia_text = text[ia_match.start():].strip()

            if general and len(general) >= 30:
                cm = ChunkMetadata(
                    texto_original=general,
                    subseccion="recomendaciones_generales",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)

            if ia_text and len(ia_text) >= 30:
                cm = ChunkMetadata(
                    texto_original=ia_text,
                    subseccion="uso_etico_ia",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)
        else:
            chunks = self._chunk_single(text, **kwargs)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_acreditacion(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Sección 10: texto general + 1 chunk para 10.1 + 1 chunk para 10.2.
        """
        chunks: list[ChunkMetadata] = []

        # Buscar subsecciones 10.1 y 10.2
        sub_matches = []
        for sub_id, sub_pattern in _SUBSECTION_10_PATTERNS:
            m = re.search(sub_pattern, text, re.IGNORECASE)
            if m:
                sub_matches.append((sub_id, m.start(), m.end()))

        if not sub_matches:
            return self._chunk_single(text, **kwargs)
        sub_matches.sort(key=lambda x: x[1])

        # Texto general antes de la primera subsección
        general = text[:sub_matches[0][1]].strip()
        if general and len(general) >= 30:
            cm = ChunkMetadata(
                texto_original=general,
                subseccion="reglas_generales",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        # Cada subsección
        for i, (sub_id, start, title_end) in enumerate(sub_matches):
            end = sub_matches[i + 1][1] if i + 1 < len(sub_matches) else len(text)
            sub_text = text[start:end].strip()

            if len(sub_text) < 30:
                continue

            cm = ChunkMetadata(
                texto_original=sub_text,
                subseccion=sub_id,
                **{k: v for k, v in kwargs.items() if k != "seccion"},
                seccion="sistema_acreditacion",
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_cronograma(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Sección 11: Cronograma completo en un solo chunk.
        Retornar toda la tabla junta es vital para que el RAG pueda ver 
        todas las fechas de parciales sin omitir semanas.
        Transfoma la tabla Markdown a viñetas para ayudar a LLMs pequeños (Qwen 3B).
        """
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line_str = line.strip()
            if line_str.startswith('|'):
                cols = [c.strip() for c in line_str.split('|')[1:-1]]
                if len(cols) >= 3 and not set(cols[0]).issubset({'-', ' '}):
                    # Evitamos asumir qué columna es cuál. Simplemente unimos el contenido.
                    # El RAG leerá este chunk entero.
                    if "Semana" in cols[0] or "Per" in cols[1] or "NA" in cols[0]:
                        continue # Skip header
                        
                    joined_cols = " | ".join(c for c in cols if c)
                    cleaned_lines.append(f"- {joined_cols}")
            else:
                cleaned_lines.append(line)
        
        parsed_text = "\n".join(cleaned_lines)

        cm = ChunkMetadata(texto_original=parsed_text, **kwargs)
        cm.generate_contextualized_text()
        cm.generate_chunk_id()
        return [cm]

    def _chunk_bibliografia(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Sección 12: 1 chunk para bibliografía básica + 1 para recursos digitales.
        """
        # Buscar separador entre bibliografía básica y recursos digitales
        digital_pattern = r"(?:recursos?\s+digitales?|recursos?\s+en\s+l[ií]nea|enlaces?\s+web|sitios?\s+web|bibliograf[ií]a\s+complementaria)"
        m = re.search(digital_pattern, text, re.IGNORECASE)

        chunks: list[ChunkMetadata] = []

        if m:
            basica = text[:m.start()].strip()
            digital = text[m.start():].strip()

            if basica and len(basica) >= 30:
                cm = ChunkMetadata(
                    texto_original=basica,
                    subseccion="bibliografia_basica",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)

            if digital and len(digital) >= 30:
                cm = ChunkMetadata(
                    texto_original=digital,
                    subseccion="recursos_digitales",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)
        else:
            chunks = self._chunk_single(text, **kwargs)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_by_subheadings(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Divide por sub-encabezados Markdown (##, ###) o por líneas en negrita.
        Fallback genérico para secciones que no tienen un parser más específico.
        """
        heading_pattern = r"(?:^|\n)\s*(?:#{2,4}\s+.+|(?:\*\*|__).+(?:\*\*|__))"
        splits = list(re.finditer(heading_pattern, text))

        if not splits:
            return self._chunk_by_paragraphs(text, **kwargs)

        chunks: list[ChunkMetadata] = []

        for i, match in enumerate(splits):
            start = match.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            block = text[start:end].strip()

            if len(block) < 30:
                continue

            cm = ChunkMetadata(
                texto_original=block,
                subseccion=f"bloque_{i + 1}",
                **kwargs,
            )
            cm.generate_contextualized_text()
            cm.generate_chunk_id()
            chunks.append(cm)

        return chunks if chunks else self._chunk_single(text, **kwargs)

    def _chunk_by_paragraphs(self, text: str, **kwargs) -> list[ChunkMetadata]:
        """
        Divide por párrafos respetando el límite de caracteres.
        Nunca corta a mitad de oración.
        """
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks: list[ChunkMetadata] = []
        current_parts: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 2 > _MAX_CHUNK_CHARS and current_parts:
                chunk_text = "\n\n".join(current_parts)
                cm = ChunkMetadata(
                    texto_original=chunk_text,
                    subseccion=f"parte_{len(chunks) + 1}",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)
                current_parts = []
                current_len = 0

            current_parts.append(para)
            current_len += len(para) + 2

        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            if len(chunk_text) >= 30:
                cm = ChunkMetadata(
                    texto_original=chunk_text,
                    subseccion=f"parte_{len(chunks) + 1}",
                    **kwargs,
                )
                cm.generate_contextualized_text()
                cm.generate_chunk_id()
                chunks.append(cm)

        return chunks
