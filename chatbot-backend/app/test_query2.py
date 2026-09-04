import asyncio
import os
import sys
import re

sys.path.insert(0, os.path.abspath("."))
from app.core.config import get_settings
from app.rag.embeddings import load_model
from app.rag.vectorstore import VectorStore
from app.services.llm import OllamaClient
from app.rag.intent_router import IntentRouter, Intent
from app.rag.catalog import get_catalog
from app.rag.query_rewriter import rewrite_query

async def test_query(question: str):
    print(f"\n--- TEST QUERY: {question} ---")
    settings = get_settings()
    load_model(settings.embedding_model)
    vs = VectorStore(host=settings.chroma_host, port=settings.chroma_port)
    ollama = OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model)
    catalog = get_catalog()

    # 1. Rewrite Query
    rewritten_query, intent_val, _ = await rewrite_query(question, [])
    intent = Intent(intent_val)
    print(f"Rewritten: {rewritten_query} | Intent: {intent}")

    # 2. Extract Materia
    found_materias = catalog.find_materias_in_text(rewritten_query)
    print(f"Materias encontradas en la consulta: {found_materias}")
    
    from app.rag.retriever import Retriever
    retriever = Retriever(vs)
    docs = await retriever.retrieve(
        query=rewritten_query,
        año_academico="2026",
        carrera_id="isi",
        materia_id=found_materias[0] if found_materias else None,
        intent=intent
    )
    print(f"Docs retrieved using retriever: {len(docs)}")
    for d in docs:
        print(f"- Source: {d.get('metadata', {}).get('source')} | Materia: {d.get('metadata', {}).get('materia_id')} | Length: {len(d.get('document', ''))}")
        print("  Snippet: " + d.get('document', '').replace('\n', ' ')[:300])
    
    # We removed _extract_exams_from_docs, so we don't call it here anymore.

if __name__ == "__main__":
    asyncio.run(test_query("cuando son los examenes de agilidad avanzada?"))
