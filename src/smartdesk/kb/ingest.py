"""Step B: repeatable ChromaDB ingestion.

    python -m smartdesk.kb.ingest [--rebuild]

Reads only the committed documents in `data/kb/`, chunks them, embeds the
chunks with OpenAI and upserts them under stable chunk ids. Unchanged chunks
(same content hash) are not re-embedded; chunks that no longer exist are
deleted. `--rebuild` drops the collection and re-indexes everything.
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from chromadb.api.models.Collection import Collection

from smartdesk.config import Settings, get_settings
from smartdesk.kb.chunking import Chunk, chunk_document
from smartdesk.kb.documents import KBDocument, parse
from smartdesk.kb.vectorstore import get_client, get_collection, search
from smartdesk.llm import get_embeddings

SAMPLE_QUERIES = (
    "How do I reset my password?",
    "How many sick leaves do I get per year?",
    "When do I get my laptop?",
    "How does vesting work?",
    "My monitor keeps flickering",  # deliberate gap: expect weak matches
)


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    embedded: int = 0
    unchanged: int = 0
    deleted: int = 0
    failures: list[str] = field(default_factory=list)


def load_documents(kb_dir: Path, report: IngestReport) -> list[KBDocument]:
    docs = []
    for path in sorted(kb_dir.glob("*.md")):
        try:
            doc = parse(path.read_text(encoding="utf-8"))
            if path.stem != doc.doc_id:
                raise ValueError(f"file name does not match doc_id {doc.doc_id!r}")
            docs.append(doc)
        except Exception as exc:
            report.failures.append(f"{path.name}: {exc}")
    return docs


def ingest(
    docs: list[KBDocument],
    collection: Collection,
    embed_documents,
    report: IngestReport,
    batch_size: int = 100,
) -> None:
    chunks: list[Chunk] = [chunk for doc in docs for chunk in chunk_document(doc)]
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate chunk ids across documents")
    report.documents, report.chunks = len(docs), len(chunks)

    existing = collection.get(include=["metadatas"])
    existing_hash = {cid: (meta or {}).get("content_hash") for cid, meta in zip(existing["ids"], existing["metadatas"])}

    to_embed = [c for c in chunks if existing_hash.get(c.chunk_id) != c.metadata["content_hash"]]
    report.unchanged = len(chunks) - len(to_embed)
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start:start + batch_size]
        try:
            vectors = embed_documents([c.text for c in batch])
            collection.upsert(
                ids=[c.chunk_id for c in batch],
                embeddings=vectors,
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
            )
            report.embedded += len(batch)
        except Exception as exc:
            report.failures.append(f"batch {start // batch_size + 1} ({len(batch)} chunks): {exc}")

    stale = sorted(set(existing_hash) - set(ids))
    if stale:
        collection.delete(ids=stale)
    report.deleted = len(stale)


def run(settings: Settings, rebuild: bool) -> int:
    report = IngestReport()
    docs = load_documents(settings.kb_dir, report)
    if not docs:
        print(f"No valid documents found in {settings.kb_dir}", file=sys.stderr)
        for failure in report.failures:
            print(f"  FAILED {failure}", file=sys.stderr)
        return 1

    client = get_client(settings)
    if rebuild and settings.chroma_collection in [c.name for c in client.list_collections()]:
        client.delete_collection(settings.chroma_collection)
    collection = get_collection(client, settings.chroma_collection)
    embeddings = get_embeddings(settings)
    ingest(docs, collection, embeddings.embed_documents, report)

    print(f"Collection '{settings.chroma_collection}' at {settings.chroma_dir}")
    print(f"  documents: {report.documents}  chunks: {report.chunks}  "
          f"embedded: {report.embedded}  unchanged: {report.unchanged}  deleted: {report.deleted}  "
          f"total in index: {collection.count()}")
    for failure in report.failures:
        print(f"  FAILED {failure}")

    print("\nSample retrieval (top 3; similarity = 1 - cosine distance):")
    for query in SAMPLE_QUERIES:
        hits = search(collection, embeddings.embed_query(query), k=3)
        print(f"  {query}")
        for hit in hits:
            print(f"    {hit.similarity:.3f}  {hit.chunk_id}")
    return 1 if report.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="drop the collection and re-index everything")
    args = parser.parse_args(argv)
    return run(get_settings(), args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
