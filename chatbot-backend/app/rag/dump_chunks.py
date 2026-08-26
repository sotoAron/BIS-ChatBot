import asyncio
import json
from app.rag.vectorstore import get_vector_store

def dump_chunks():
    vs = get_vector_store()
    results = vs.get()
    
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    
    chunks = []
    for i in range(len(docs)):
        chunks.append({
            "metadata": metas[i],
            "document": docs[i]
        })
        
    with open("/tmp/chunks_dump.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
        
    print(f"Dumped {len(chunks)} chunks to /tmp/chunks_dump.json")

if __name__ == "__main__":
    dump_chunks()
