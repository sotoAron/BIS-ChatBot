import asyncio
import sys

sys.path.append("/app")
from app.rag.retriever import get_retriever

async def main():
    print("Iniciando busqueda...")
    retriever = get_retriever()
    
    query = "cronograma evaluaciones formativas calendario parciales cuando son los examenes de aacsw?"
    print(f"Query: {query}")
    
    result = await retriever.retrieve_with_prompt(
        query=query,
        año_academico="2026",
        carrera="ISI",
        is_exams=True,
        secciones=None,  # Sin hard-filter por sección
        materia_id="aacsw",
    )
    
    print("\n--- CHUNKS RECUPERADOS ---")
    for i, doc in enumerate(result.docs):
        meta = doc.get("metadata", {})
        print(f"\n[Chunk {i+1}] Score: {doc.get('score')} | Seccion: {meta.get('seccion')} | Subseccion: {meta.get('subseccion')} | Source: {meta.get('source','')[:50]}")
        print(f"Texto ({len(doc.get('document',''))} chars):")
        print(doc.get("document", "")[:500])
        print("---")
        
    print("\n--- PROMPT FINAL (primeros 3000 chars) ---")
    print(result.system_prompt[:3000])

if __name__ == "__main__":
    asyncio.run(main())
