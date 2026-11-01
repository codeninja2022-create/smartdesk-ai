"""ChromaDB access shared by ingestion and retrieval.

Embeddings are computed by SmartDesk (OpenAI) and passed in explicitly, so the
collection is created without a Chroma embedding function. Distances are
cosine distances (1 - cosine similarity).
"""

from dataclasses import dataclass

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from smartdesk.config import Settings


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    text: str
    metadata: dict
    similarity: float  # 1 - cosine distance; a ranking score, not a probability


def get_client(settings: Settings) -> ClientAPI:
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection(client: ClientAPI, name: str) -> Collection:
    return client.get_or_create_collection(
        name, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
    )


def search(
    collection: Collection, query_embedding: list[float], k: int = 5, where: dict | None = None
) -> list[SearchHit]:
    if collection.count() == 0:
        return []
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(k, collection.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return [
        SearchHit(chunk_id, text, dict(meta), round(1.0 - distance, 4))
        for chunk_id, text, meta, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]
