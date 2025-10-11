import sys
from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import QDRANT_URL, QDRANT_API_KEY


def _make_qdrant_client():
    try:
        kwargs = dict(url=QDRANT_URL or "http://localhost:6333", prefer_grpc=False, timeout=60, check_compatibility=False)
        if QDRANT_API_KEY:
            kwargs["api_key"] = QDRANT_API_KEY
        client = QdrantClient(**kwargs)
        client.get_collections()
        return client
    except Exception:
        # fallback to localhost without API key
        return QdrantClient(url="http://localhost:6333", prefer_grpc=False, timeout=60, check_compatibility=False)


def setup_qdrant(collection_name, embedding, path, embedding_size):
    client = _make_qdrant_client()
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=embedding_size, distance=Distance.COSINE)
    )
    return Qdrant(
        client=client,
        collection_name=collection_name,
        embeddings=embedding,
    )

def add_to_vector_store(vectorstore, documents):
    vectorstore.add_documents(documents)
