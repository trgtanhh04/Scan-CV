from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def setup_qdrant(collection_name, embedding, path, embedding_size):
    client = QdrantClient(path=path)
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
