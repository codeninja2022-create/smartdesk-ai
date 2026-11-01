"""Structure-aware chunking for KB documents.

Unit of retrieval:
- the opening summary -> one "overview" chunk;
- each `##` section -> one "section" chunk;
- each FAQ (`### question` + answer) -> its own "faq" chunk, so an employee
  question can match a single Q&A pair instead of a whole FAQ list.

Every chunk's text starts with a context header ("<title> > <section>") so it
stays self-explanatory once separated from its document. Sections longer than
`max_tokens` are split on paragraph boundaries, carrying the previous
paragraph over as overlap when it is short enough.
"""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

from smartdesk.kb.documents import KBDocument

MAX_TOKENS = 400
MAX_OVERLAP_TOKENS = 80
FAQ_HEADING = "Frequently asked questions"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int]


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")  # the tokenizer used by text-embedding-3-*


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "section"


def _split_paragraphs(body: str, budget: int) -> list[str]:
    """Pack paragraphs into parts of at most `budget` tokens, with overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[list[str]] = [[]]
    for paragraph in paragraphs:
        current = parts[-1]
        if current and count_tokens("\n\n".join([*current, paragraph])) > budget:
            overlap = current[-1] if count_tokens(current[-1]) <= MAX_OVERLAP_TOKENS else None
            parts.append([overlap] if overlap else [])
        parts[-1].append(paragraph)
    return ["\n\n".join(part) for part in parts if part]


def _sections(body: str) -> list[tuple[str, str, str]]:
    """Split a document body into (chunk_type, heading, text) units."""
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    units: list[tuple[str, str, list[str]]] = [("overview", "Overview", [])]
    in_faq = False
    for line in lines:
        if line.startswith("## "):
            heading = line[3:].strip()
            in_faq = heading.lower() == FAQ_HEADING.lower()
            if not in_faq:
                units.append(("section", heading, []))
        elif line.startswith("### ") and in_faq:
            units.append(("faq", line[4:].strip(), []))
        else:
            units[-1][2].append(line)
    return [(kind, heading, "\n".join(text).strip()) for kind, heading, text in units if "\n".join(text).strip()]


def chunk_document(doc: KBDocument, max_tokens: int = MAX_TOKENS) -> list[Chunk]:
    chunks: list[Chunk] = []
    used_ids: set[str] = set()
    for kind, heading, text in _sections(doc.body):
        header = f"{doc.title} > {heading}"
        if kind == "faq":
            header = f"{doc.title} > FAQ"
            text = f"Q: {heading}\nA: {text}"
        parts = _split_paragraphs(text, max_tokens - count_tokens(header) - 2)
        for part_no, part in enumerate(parts, start=1):
            base = f"{doc.doc_id}#{kind}-{_slug(heading)}" + (f"-p{part_no}" if len(parts) > 1 else "")
            chunk_id, n = base, 2
            while chunk_id in used_ids:  # repeated headings stay unique and stable
                chunk_id, n = f"{base}-{n}", n + 1
            used_ids.add(chunk_id)
            full_text = f"{header}\n\n{part}"
            chunks.append(Chunk(
                chunk_id=chunk_id,
                text=full_text,
                metadata={
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "domain": doc.domain.value,
                    "category": doc.category,
                    "subcategory": doc.subcategory,
                    "section": heading,
                    "chunk_type": kind,
                    "source_type": doc.provenance.source_type.value,
                    "tokens": count_tokens(full_text),
                    "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16],
                },
            ))
    return chunks
