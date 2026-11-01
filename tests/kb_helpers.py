import hashlib

from smartdesk.kb.documents import Domain, KBDocument, Provenance, SourceType


def make_doc(doc_id: str = "it-sample", body: str | None = None, **overrides) -> KBDocument:
    fields = dict(
        doc_id=doc_id,
        title="Sample Article",
        domain=Domain.IT,
        category="IT Support",
        subcategory="Accounts",
        provenance=Provenance(source_type=SourceType.SYNTHETIC, generator_model="test", generated_at="2026-10-31"),
        body=body or (
            "# Sample Article\n\nShort overview.\n\n## Steps\n\n1. Do this.\n2. Then that.\n\n"
            "## Frequently asked questions\n\n### How long does it take?\n\nFive minutes.\n\n"
            "### Who do I contact?\n\nThe IT Service Desk."
        ),
    )
    fields.update(overrides)
    return KBDocument(**fields)


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic 8-dim vectors derived from a hash of each text."""
    vectors = []
    for text in texts:
        digest = hashlib.sha256(text.encode()).digest()
        vectors.append([b / 255 + 0.01 for b in digest[:8]])
    return vectors
