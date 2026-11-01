"""Semantic, IT/HR-aware retrieval from ChromaDB.

When the router supplies a domain hint, the search is first restricted to that
domain. If the restricted search returns nothing, or its best hit falls below
`domain_fallback_similarity` (the abstention threshold), the whole KB is
searched instead, so a wrong domain hint cannot by itself cause an escalation.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass

from chromadb.api.models.Collection import Collection

from smartdesk.config import Settings
from smartdesk.kb.documents import Domain
from smartdesk.kb.vectorstore import SearchHit, get_client, get_collection, search
from smartdesk.llm import get_embeddings


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    domain: str
    text: str
    similarity: float  # 1 - cosine distance; a ranking score, not a probability

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "RetrievedChunk":
        meta = hit.metadata
        return cls(
            chunk_id=hit.chunk_id,
            doc_id=str(meta["doc_id"]),
            title=str(meta["title"]),
            section=str(meta["section"]),
            domain=str(meta["domain"]),
            text=hit.text,
            similarity=hit.similarity,
        )

    def to_dict(self) -> dict:
        return asdict(self)  # built-in types only, so it can live in checkpointed state


class Retriever:
    def __init__(
        self,
        collection: Collection,
        embed_query: Callable[[str], list[float]],
        top_k: int = 5,
        domain_fallback_similarity: float = 0.0,
    ) -> None:
        self.collection = collection
        self.embed_query = embed_query
        self.top_k = top_k
        self.domain_fallback_similarity = domain_fallback_similarity

    def retrieve(self, query: str, domain: str | None = None) -> list[RetrievedChunk]:
        vector = self.embed_query(query)
        if domain in {d.value for d in Domain}:
            hits = search(self.collection, vector, k=self.top_k, where={"domain": domain})
            if hits and hits[0].similarity >= self.domain_fallback_similarity:
                return [RetrievedChunk.from_hit(h) for h in hits]
        return [RetrievedChunk.from_hit(h) for h in search(self.collection, vector, k=self.top_k)]


def build_retriever(settings: Settings) -> Retriever:
    collection = get_collection(get_client(settings), settings.chroma_collection)
    return Retriever(
        collection,
        get_embeddings(settings).embed_query,
        top_k=settings.rag_top_k,
        domain_fallback_similarity=settings.rag_min_similarity,
    )
