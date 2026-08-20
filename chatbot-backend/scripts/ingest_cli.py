#!/usr/bin/env python3
"""
scripts/ingest_cli.py — CLI para ingestar documentos directamente en ChromaDB.

USO DESDE DOCKER (recomendado):
    docker compose exec backend python scripts/ingest_cli.py \
        --file /ruta/al/reglamento.pdf \
        --año 2026 \
        --carrera "Ingeniería Informática" \
        --module "Reglamento Académico"

USO LOCAL (requiere ChromaDB accesible en localhost):
    python scripts/ingest_cli.py --file ./reglamento.txt --año 2026 --carrera "Informática"

OPCIONES:
    --file      Ruta al archivo (PDF, TXT, DOCX, MD)
    --año       Año académico para el filtro RAG (ej: 2026)
    --carrera   Nombre de la carrera (ej: "Ingeniería Informática")
    --module    Módulo o sección del documento (opcional)
    --host      Host de ChromaDB (default: localhost)
    --port      Puerto de ChromaDB (default: 8000)
    --chunk-size    Tamaño máximo de cada chunk en chars (default: 512)
    --overlap       Solapamiento entre chunks (default: 64)
    --stats     Solo mostrar estadísticas de ChromaDB sin ingestar
    --list      Listar documentos indexados con filtro de carrera/año
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Añadir el root del proyecto al PYTHONPATH para importar app.*
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_chroma_client(host: str, port: int):
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    return chromadb.HttpClient(
        host=host,
        port=port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


async def do_ingest(args):
    """Ingesta un documento al vector store."""
    from app.rag.embeddings import embed_text, load_model
    from app.rag.ingest import ChunkingConfig, DocumentChunker, DocumentMetadata
    from app.rag.vectorstore import VectorStore

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ Archivo no encontrado: {file_path}")
        sys.exit(1)

    print(f"📂 Archivo:  {file_path.name}  ({file_path.stat().st_size / 1024:.1f} KB)")
    print(f"📅 Año:      {args.año}")
    print(f"🎓 Carrera:  {args.carrera}")
    print(f"📖 Módulo:   {args.module or '(sin módulo)'}")
    print(f"⚙️  Chunks:   tamaño={args.chunk_size}, overlap={args.overlap}")
    print()

    # 1. Cargar modelo de embeddings
    print("🔄 Cargando modelo de embeddings...")
    load_model()
    print("✅ Modelo listo")

    # 2. Conectar a ChromaDB
    print(f"🔗 Conectando a ChromaDB en {args.host}:{args.port}...")
    vector_store = VectorStore(host=args.host, port=args.port)
    docs_antes = vector_store.count()
    print(f"✅ ChromaDB conectado. Documentos actuales: {docs_antes}")

    # 3. Ingestar
    print(f"\n⏳ Procesando {file_path.name} ...")
    config = ChunkingConfig(
        chunk_size=args.chunk_size,
        chunk_overlap=args.overlap,
    )
    metadata = DocumentMetadata(
        source=file_path.name,
        año_academico=args.año,
        carrera=args.carrera,
        module=args.module or "",
    )
    chunker = DocumentChunker(
        vector_store=vector_store,
        embedder=embed_text,
        config=config,
    )
    count = await chunker.ingest(file_path, metadata)

    # 4. Resultado
    docs_despues = vector_store.count()
    print(f"\n✅ Ingesta completada:")
    print(f"   Chunks generados e indexados: {count}")
    print(f"   Total en ChromaDB: {docs_antes} → {docs_despues}")


async def do_stats(args):
    """Muestra estadísticas del vector store."""
    from app.rag.vectorstore import VectorStore

    print(f"🔗 Conectando a ChromaDB en {args.host}:{args.port}...")
    vs = VectorStore(host=args.host, port=args.port)
    total = vs.count()
    available = vs.is_available()

    print(f"\n📊 ChromaDB stats:")
    print(f"   Estado:          {'✅ OK' if available else '❌ No disponible'}")
    print(f"   Total chunks:    {total}")
    if total == 0:
        print("\n⚠️  ChromaDB está vacío. El RAG no funcionará hasta ingestar documentos.")
        print("   Usa: python scripts/ingest_cli.py --file reglamento.pdf --año 2026 --carrera 'Informática'")


def main():
    parser = argparse.ArgumentParser(
        description="CLI de ingesta de documentos para el Chatbot Académico RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file",    help="Ruta al documento (PDF/TXT/DOCX/MD)")
    parser.add_argument("--año",     default="2026",             help="Año académico (default: 2026)")
    parser.add_argument("--carrera", default="",                 help="Carrera del documento")
    parser.add_argument("--module",  default="",                 help="Módulo o sección")
    parser.add_argument("--host",    default="localhost",         help="Host ChromaDB (default: localhost)")
    parser.add_argument("--port",    default=8000, type=int,     help="Puerto ChromaDB (default: 8000)")
    parser.add_argument("--chunk-size", default=512, type=int,   help="Tamaño de chunk en chars")
    parser.add_argument("--overlap",    default=64,  type=int,   help="Overlap entre chunks")
    parser.add_argument("--stats",  action="store_true",          help="Solo mostrar estadísticas")

    args = parser.parse_args()

    if args.stats:
        asyncio.run(do_stats(args))
    elif args.file:
        asyncio.run(do_ingest(args))
    else:
        parser.print_help()
        print("\n⚠️  Debes especificar --file para ingestar o --stats para ver estadísticas.")
        sys.exit(1)


if __name__ == "__main__":
    main()
