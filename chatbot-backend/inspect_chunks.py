import sys
sys.path.insert(0, '/app')
from app.rag.vectorstore import get_vector_store

vs = get_vector_store()
results = vs._collection.get(where={"chunk_index": {"$in": [11, 35]}})
for i, doc in enumerate(results['documents']):
    meta = results['metadatas'][i]
    idx = meta.get('chunk_index')
    print("=== CHUNK", idx, "===")
    print(doc[:800])
    print()
