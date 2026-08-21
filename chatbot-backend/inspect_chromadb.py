"""
inspect_chromadb.py — Herramienta independiente vía REST API para inspeccionar ChromaDB.

Funciona en cualquier versión de Python (usa httpx o urllib nativo sin depender del paquete chromadb).

Muestra:
  1. Colecciones disponibles y conteo total de chunks.
  2. Inspección detallada de cada chunk (ID, metadatos, texto Markdown y embeddings).
  3. Búsqueda por palabra clave o exportación completa a archivo JSON.

Uso:
  python inspect_chromadb.py
  python inspect_chromadb.py --search "evaluación"
  python inspect_chromadb.py --full
  python inspect_chromadb.py --export chunks_dump.json
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from typing import Optional

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _http_get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "ChromaInspector/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ChromaInspector/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def inspect_chroma(
    host: str = "localhost",
    port: int = 8001,
    collection_name: str = "academic_docs",
    search: Optional[str] = None,
    export_path: Optional[str] = None,
    show_full_text: bool = False,
):
    base_url = f"http://{host}:{port}/api/v1"
    print(f"\n📡 Conectando a ChromaDB REST API en {base_url}...")

    try:
        collections = _http_get(f"{base_url}/collections")
        if not isinstance(collections, list):
            print(f"❌ Respuesta inesperada al listar colecciones: {collections}")
            return

        col_dict = {c.get("name"): c.get("id") for c in collections}
        print(f"📚 Colecciones encontradas: {list(col_dict.keys())}")

        if collection_name not in col_dict:
            print(f"❌ La colección '{collection_name}' no existe en ChromaDB.")
            return

        col_id = col_dict[collection_name]
        count = _http_get(f"{base_url}/collections/{col_id}/count")
        print(f"📊 Total de chunks indexados en '{collection_name}': {count} (Collection ID: {col_id})\n")

        if count == 0:
            print("ℹ️ La colección está vacía. No hay documentos indexados.")
            return

        # Consultar todos los chunks con documentos, metadatos y embeddings
        payload = {
            "include": ["metadatas", "documents", "embeddings"],
        }
        data = _http_post(f"{base_url}/collections/{col_id}/get", payload)

        ids = data.get("ids", [])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        embs = data.get("embeddings", [])

        results_to_export = []
        matching_count = 0

        for i in range(len(ids)):
            doc_id = ids[i]
            text = docs[i] if docs and len(docs) > i else ""
            meta = metas[i] if metas and len(metas) > i else {}
            emb = embs[i] if embs is not None and len(embs) > i else []

            # Filtrar si se pasó --search
            if search and search.lower() not in text.lower() and search.lower() not in json.dumps(meta).lower():
                continue

            matching_count += 1
            char_count = len(text)
            emb_dim = len(emb) if emb is not None else 0

            print(f"╔══ [CHUNK {matching_count}/{count}] ID: {doc_id}")
            print(f"║  📁 Origen: {meta.get('source', 'N/A')} | Módulo: {meta.get('module', 'N/A')}")
            print(f"║  🎓 Carrera: {meta.get('carrera', 'N/A')} | Año: {meta.get('año_academico', 'N/A')}")
            print(f"║  🔢 Posición: Chunk {meta.get('chunk_index', '?')} de {meta.get('total_chunks', '?')}")
            print(f"║  📏 Longitud: {char_count} caracteres | Dimensión Vectorial: {emb_dim} floats")
            if emb_dim > 0 and emb:
                print(f"║  📐 Vector Preview: [{emb[0]:.4f}, {emb[1]:.4f}, {emb[2]:.4f}, ...]")
            print("║  📝 Contenido Extraído:")
            
            if show_full_text or len(text) <= 400:
                for line in text.split("\n"):
                    print(f"║     {line}")
            else:
                for line in text[:400].split("\n"):
                    print(f"║     {line}")
                print(f"║     ... [+{char_count - 400} caracteres. Usa --full para ver completo]")
            print("╚" + "═" * 78 + "\n")

            results_to_export.append({
                "id": doc_id,
                "metadata": meta,
                "document": text,
                "embedding_dim": emb_dim,
                "embedding_sample": emb[:5] if emb and len(emb) >= 5 else [],
            })

        if search:
            print(f"🔍 Búsqueda: {matching_count} de {count} chunks coinciden con '{search}'.")

        if export_path:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(results_to_export, f, ensure_ascii=False, indent=2)
            print(f"💾 Chunks exportados con éxito a: {export_path}")

    except urllib.error.URLError as e:
        print(f"❌ Error conectando a ChromaDB ({base_url}): {e}")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspeccionar colecciones, chunks y embeddings en ChromaDB")
    parser.add_argument("--host", default="localhost", help="Host de ChromaDB (default: localhost)")
    parser.add_argument("--port", type=int, default=8001, help="Puerto de ChromaDB expuesto en host (default: 8001)")
    parser.add_argument("--collection", default="academic_docs", help="Nombre de colección (default: academic_docs)")
    parser.add_argument("--search", default=None, help="Filtrar por palabra clave en texto o metadatos")
    parser.add_argument("--export", default=None, help="Ruta de archivo JSON para exportar todos los chunks")
    parser.add_argument("--full", action="store_true", help="Mostrar el texto completo de cada chunk sin truncar")
    args = parser.parse_args()

    inspect_chroma(
        host=args.host,
        port=args.port,
        collection_name=args.collection,
        search=args.search,
        export_path=args.export,
        show_full_text=args.full,
    )
