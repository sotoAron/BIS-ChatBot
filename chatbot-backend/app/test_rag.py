import asyncio
import json
from datetime import datetime
from app.rag.vectorstore import get_vector_store
from app.rag.retriever import get_retriever
from app.rag.query_rewriter import rewrite_query

async def test_golden():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] --- TEST GOLDEN RAG & INTENT ROUTER ---")
    
    # 1. Test Intent Router & Date Parsing
    print("\n1. Probando Intent Router (Query Rewriter)")
    queries = [
        ("agendar tarea para mañana de aacsw", []),
        ("cuando son los examenes", [{"role": "assistant", "content": "¿Quieres que agende una entrega para mañana?"}]),
        ("que profesores estan en aacsw", [])
    ]
    
    for q, hist in queries:
        rewritten, intent, entities = await rewrite_query(q, hist)
        print(f"\nUser: '{q}'")
        print(f" -> Rewritten: '{rewritten}'")
        print(f" -> Intent: {intent}")
        if entities:
            print(f" -> Entities: {json.dumps(entities, ensure_ascii=False)}")
            
    # 2. Test Retriever
    print("\n2. Probando RAG Retriever (ChromaDB + Table-Aware Chunking)")
    retriever = get_retriever()
    
    rag_queries = [
        "quienes son los profesores de la catedra aacsw??",
        "cuando son los examenes de aacsw?",
        "de que nivel es la materia aacsw?",
        "cual es el programa de la materia aacsw?",
    ]
    
    for q in rag_queries:
        print(f"\n--- RESULTS FOR '{q}' ---")
        docs = await retriever.retrieve(q, año_academico="2026", carrera="")
        for i, doc in enumerate(docs):
            print(f"\nChunk {i+1} (score: {doc.get('score')}):")
            print(doc['document'])
            print("Metadata:", doc['metadata'])

if __name__ == "__main__":
    asyncio.run(test_golden())
