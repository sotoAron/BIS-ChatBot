import sys
sys.path.insert(0, '/app')
from app.rag.vectorstore import get_vector_store
from app.rag.retriever import extract_exam_summary

vs = get_vector_store()
results = vs._collection.get(where=None)
docs = []
for i, doc in enumerate(results['documents']):
    meta = results['metadatas'][i]
    if meta.get('chunk_index') in [32, 34, 35, 37, 39]:
        docs.append({"document": doc})

print('--- EXAM SUMMARY OUTPUT ---')
print(extract_exam_summary(docs))
