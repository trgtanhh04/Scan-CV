import sys
from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import QDRANT_URL, QDRANT_API_KEY


def setup_qdrant(collection_name, embedding, path, embedding_size):
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
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
