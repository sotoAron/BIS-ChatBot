import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.core.config import get_settings
from app.rag.embeddings import load_model
from app.rag.vectorstore import VectorStore
from app.services.llm import OllamaClient
from app.rag.intent_router import Intent
from app.rag.catalog import get_catalog
from app.rag.query_rewriter import rewrite_query
from app.rag.retriever import get_retriever

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
    materia = found_materias[0] if found_materias else None
    print(f"Materia encontrada: {materia}")
    
    retriever = get_retriever(vs)
    # The retriever method `retrieve_with_prompt` takes `is_exams=...`
    result = await retriever.retrieve_with_prompt(
        query=rewritten_query,
        año_academico="2026",
        carrera="isi",
        is_exams=(intent == Intent.EXAMS),
        materia_id=materia
    )
    
    print(f"Docs retrieved: {len(result.docs)}")
    print("--- System Prompt ---")
    print(result.system_prompt[:500] + "...\n(TRUNCATED)\n")
    
    # Let's ask Ollama
    print("--- LLM Response ---")
    response_stream = ollama.generate_stream(
        prompt=question,
        system_prompt=result.system_prompt
    )
    
    full_resp = ""
    async for chunk in response_stream:
        full_resp += chunk
        print(chunk, end="", flush=True)
    print("\n----------------------")

if __name__ == "__main__":
    asyncio.run(test_query("cuando son los examenes de agilidad avanzada?"))
