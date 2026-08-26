import chromadb
from chromadb.config import Settings as ChromaSettings
from app.core.config import get_settings
from app.rag.vectorstore import COLLECTION_NAME

def purge_chroma():
    settings = get_settings()
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    
    try:
        client.delete_collection(name=COLLECTION_NAME)
        print(f"Collection {COLLECTION_NAME} deleted successfully.")
    except Exception as e:
        print(f"Failed to delete collection: {e}")

if __name__ == "__main__":
    purge_chroma()
