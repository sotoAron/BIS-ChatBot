import asyncio
import logging
from pprint import pprint
import os

from app.services.moodle_client import get_moodle_client
from app.rag.moodle_sync import sync_course_pdf
from app.rag.vectorstore import get_vector_store
from app.rag.retriever import get_retriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pipeline_test")

async def run_pipeline():
    print("="*60)
    print(" PIPELINE DE DIAGNÓSTICO: MOODLE -> CHUNK -> CHROMA -> RAG ")
    print("="*60)
    
    print("\n--- 1. Testing Moodle Connection and Courses ---")
    client = get_moodle_client()
    user_id = 2  # Asumiendo que 2 es el admin o un usuario válido de prueba
    try:
        courses = await client.get_user_courses(user_id)
        print(f"✅ Cursos obtenidos para usuario {user_id}: {len(courses)}")
        for c in courses:
            print(f"  - ID: {c.get('id')} | Nombre: {c.get('fullname')} | Corto: {c.get('shortname')}")
    except Exception as e:
        print(f"❌ Error conectando a Moodle o sin cursos: {e}")
        return

    if not courses:
        print("❌ No hay cursos. Deteniendo pipeline.")
        return
        
    course = courses[0]
    course_id = course["id"]
    course_name = course.get("shortname", "Unknown")
    print(f"\n✅ Usaremos el curso: {course_name} (ID: {course_id})")

    print("\n--- 2. Buscando un PDF en los contenidos del curso ---")
    try:
        contents = await client.get_course_contents(course_id)
        pdf_url = None
        pdf_filename = None
        for section in contents:
            for module in section.get("modules", []):
                if module.get("modname") == "resource":
                    for content in module.get("contents", []):
                        if content.get("mimetype") == "application/pdf":
                            pdf_url = content.get("fileurl")
                            pdf_filename = content.get("filename")
                            break
                if pdf_url: break
            if pdf_url: break
            
        if not pdf_url:
            print("⚠️ No se encontró ningún PDF en el curso. (Asegúrate de haber subido uno en Moodle).")
        else:
            print(f"✅ PDF encontrado: {pdf_filename} | URL: {pdf_url}")
            
            print("\n--- 3. Descargando y Vectorizando PDF ---")
            año_academico = "2026"
            carrera = "Ingeniería Informática"
            print(f"Sincronizando PDF (año={año_academico}, carrera={carrera})...")
            try:
                chunks = await sync_course_pdf(course_id, pdf_url, pdf_filename, año_academico, carrera)
                print(f"✅ PDF sincronizado. Chunks indexados: {chunks}")
            except Exception as e:
                print(f"❌ Error sincronizando PDF: {e}")
    except Exception as e:
        print(f"❌ Error obteniendo contenidos: {e}")

    print("\n--- 4. Comprobando qué hay en ChromaDB ---")
    vs = get_vector_store()
    try:
        col = vs._collection
        count = col.count()
        print(f"✅ Total de documentos en ChromaDB (colección {col.name}): {count}")
        if count > 0:
            sample = col.peek(2)
            print("\nEjemplo de Metadatos en ChromaDB:")
            for meta in sample.get("metadatas", []):
                pprint(meta)
    except Exception as e:
        print(f"❌ Error accediendo a ChromaDB: {e}")
        
    print("\n--- 5. Probando el Retriever (Simulando consulta del usuario) ---")
    retriever = get_retriever()
    query = f"¿Cuándo es el parcial de {course_name}?"
    año_academico = "2026"
    carrera = "Ingeniería Informática"
    print(f"Pregunta: '{query}'")
    print(f"Filtros: año={año_academico}, carrera={carrera}")
    try:
        results = await retriever.retrieve(query, año_academico, carrera)
        print(f"✅ Resultados que superan el umbral (min_score={retriever._min_score}): {len(results)}")
        for i, res in enumerate(results):
            print(f"\n--- Resultado {i+1} (Score: {res.get('score')}) ---")
            print(res.get("document", "")[:300] + "...\n")
    except Exception as e:
         print(f"❌ Error en la recuperación: {e}")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
