"""
app/rag/catalog.py — Catálogo maestro de normalización de entidades.

Mantiene una tabla de carreras y materias con IDs canónicos, nombres
completos, siglas y variantes conocidas. Se usa para:

  1. Normalizar nombres de entidades al ingestar documentos.
  2. Cruzar información entre planificaciones y boletines.
  3. Resolver acrónimos en las queries del usuario (ej. "AACSW" → id canónico).

El catálogo se persiste como JSON editable en `data/catalog.json` y se
carga al inicio. Es de bajo volumen y cambia con poca frecuencia.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ruta al archivo de catálogo (relativa a la raíz del backend)
_CATALOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalog.json"

# ══════════════════════════════════════════════════════════════════════════════
# Modelos internos
# ══════════════════════════════════════════════════════════════════════════════

class CarreraEntry:
    """Entrada del catálogo para una carrera."""
    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.nombre: str = data["nombre"]
        self.siglas: list[str] = [s.lower() for s in data.get("siglas", [])]
        self.variantes: list[str] = [v.lower() for v in data.get("variantes", [])]

    def matches(self, text: str) -> bool:
        """Verifica si el texto coincide con esta carrera."""
        t = text.lower().strip()
        if t == self.id:
            return True
        if t == self.nombre.lower():
            return True
        if t in self.siglas:
            return True
        return any(v in t or t in v for v in self.variantes)


class MateriaEntry:
    """Entrada del catálogo para una materia."""
    def __init__(self, data: dict):
        self.id: str = data["id"]
        self.nombre: str = data["nombre"]
        self.siglas: list[str] = [s.lower() for s in data.get("siglas", [])]
        self.variantes: list[str] = [v.lower() for v in data.get("variantes", [])]
        self.carreras: list[str] = data.get("carreras", [])
        self.nivel: int = data.get("nivel", 0)

    def matches(self, text: str) -> bool:
        """Verifica si el texto coincide con esta materia."""
        t = text.lower().strip()
        if t == self.id:
            return True
        if t == self.nombre.lower():
            return True
        if t in self.siglas:
            return True
        return any(v in t or t in v for v in self.variantes)


# ══════════════════════════════════════════════════════════════════════════════
# Catálogo principal (singleton)
# ══════════════════════════════════════════════════════════════════════════════

class Catalog:
    """Catálogo maestro de carreras y materias."""

    def __init__(self, catalog_path: Path | None = None):
        self._path = catalog_path or _CATALOG_PATH
        self.carreras: list[CarreraEntry] = []
        self.materias: list[MateriaEntry] = []
        self._load()

    def _load(self) -> None:
        """Carga el catálogo desde el archivo JSON."""
        if not self._path.exists():
            logger.warning(
                "Catálogo no encontrado en %s. Usando catálogo vacío.", self._path
            )
            return

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.carreras = [CarreraEntry(c) for c in data.get("carreras", [])]
            self.materias = [MateriaEntry(m) for m in data.get("materias", [])]

            logger.info(
                "Catálogo cargado: %d carreras, %d materias desde %s",
                len(self.carreras), len(self.materias), self._path,
            )
        except Exception as e:
            logger.error("Error cargando catálogo desde %s: %s", self._path, e)

    def reload(self) -> None:
        """Recarga el catálogo desde disco (útil tras editar el JSON)."""
        self.carreras.clear()
        self.materias.clear()
        self._load()

    # ── Normalización ─────────────────────────────────────────────────────────

    def normalize_carrera(self, text: str) -> Optional[str]:
        """
        Normaliza un texto a un ID canónico de carrera.
        Retorna None si no se encuentra coincidencia.
        """
        if not text:
            return None
        for c in self.carreras:
            if c.matches(text):
                return c.id
        return None

    def normalize_materia(self, text: str) -> Optional[str]:
        """
        Normaliza un texto a un ID canónico de materia.
        Retorna None si no se encuentra coincidencia.
        """
        if not text:
            return None
        for m in self.materias:
            if m.matches(text):
                return m.id
        return None

    def get_carrera(self, carrera_id: str) -> Optional[CarreraEntry]:
        """Obtiene una carrera por su ID canónico."""
        for c in self.carreras:
            if c.id == carrera_id:
                return c
        return None

    def get_materia(self, materia_id: str) -> Optional[MateriaEntry]:
        """Obtiene una materia por su ID canónico."""
        for m in self.materias:
            if m.id == materia_id:
                return m
        return None

    def find_materias_in_text(self, text: str) -> list[str]:
        """
        Busca todas las materias mencionadas en un texto.
        Útil para sub-chunking de boletines que mencionan varias materias.
        Retorna lista de materia_ids canónicos.
        """
        found = []
        text_lower = text.lower()
        for m in self.materias:
            # Buscar por nombre completo primero (más específico)
            if m.nombre.lower() in text_lower:
                if m.id not in found:
                    found.append(m.id)
                continue
            # Buscar por siglas (solo si es palabra completa para evitar falsos positivos)
            matched = False
            for sigla in m.siglas:
                if re.search(rf"\b{re.escape(sigla)}\b", text_lower):
                    matched = True
                    break
            if not matched:
                # Buscar por variantes
                for var in m.variantes:
                    if var.lower() in text_lower:
                        matched = True
                        break
            
            if matched and m.id not in found:
                found.append(m.id)
        return found

    def find_carreras_in_text(self, text: str) -> list[str]:
        """
        Busca todas las carreras mencionadas en un texto.
        Retorna lista de carrera_ids canónicos.
        """
        found = []
        text_lower = text.lower()
        for c in self.carreras:
            for sigla in c.siglas:
                if re.search(rf"\b{re.escape(sigla)}\b", text_lower):
                    if c.id not in found:
                        found.append(c.id)
                    break
        return found


# ══════════════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════════════

_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    """Retorna la instancia singleton del catálogo."""
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
