"""
app/rag/resync_cli.py

Script CLI para forzar la resincronización de los documentos de un curso
desde Moodle hacia ChromaDB. Utiliza el pipeline completo (descarga, 
conversión a Markdown con pymupdf4llm, partición jerárquica con table-awareness,
embeddings e indexación).

Uso:
  python -m app.rag.resync_cli --course-id 2 --anio 2026 --carrera "Sistemas"
"""
import asyncio
import argparse
import logging
from app.rag.tools import ToolExecutor

# Configurar logging para ver el progreso en consola
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    parser = argparse.ArgumentParser(description="Forzar resincronización de PDFs de un curso desde Moodle.")
    parser.add_argument("--course-id", type=int, required=True, help="ID del curso en Moodle (ej. 2)")
    parser.add_argument("--anio", type=str, required=True, help="Año académico (ej. 2026)")
    parser.add_argument("--carrera", type=str, required=True, help="Nombre de la carrera")
    
    args = parser.parse_args()
    
    print(f"\n[🔄] Iniciando resincronización para el curso ID: {args.course_id} (Año: {args.anio}, Carrera: {args.carrera})")
    print("-" * 70)
    
    # Utilizar la herramienta existente que hace el pipeline completo
    result = await ToolExecutor.sync_course_syllabus(
        course_id=args.course_id, 
        año=args.anio, 
        carrera=args.carrera
    )
    
    print("-" * 70)
    print(f"[✅] Resultado: {result}\n")

if __name__ == "__main__":
    asyncio.run(main())
