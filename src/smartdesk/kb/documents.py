"""KB document model and its Markdown-with-YAML-front-matter file format."""

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DOC_ID_PATTERN = r"^(it|hr|onb|pay)-[a-z0-9]+(?:-[a-z0-9]+)*$"
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)


class Domain(StrEnum):
    IT = "IT"
    HR = "HR"


class SourceType(StrEnum):
    DATASET_DERIVED = "dataset_derived"  # LLM-written, grounded in public dataset records
    SYNTHETIC = "synthetic"  # LLM-written from the company fact sheet only


class Provenance(BaseModel):
    source_type: SourceType
    datasets: list[str] = Field(default_factory=list)  # "<hf id>@<revision>"
    source_record_ids: list[str] = Field(default_factory=list)
    generator_model: str
    generated_at: str  # ISO date


class KBDocument(BaseModel):
    doc_id: str = Field(pattern=DOC_ID_PATTERN)
    title: str
    domain: Domain
    category: str
    subcategory: str
    provenance: Provenance
    body: str  # Markdown, starting at the "# Title" heading


def render(doc: KBDocument) -> str:
    meta = doc.model_dump(mode="json", exclude={"body"})
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n{doc.body.strip()}\n"


def parse(text: str) -> KBDocument:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise ValueError("missing YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    return KBDocument(**meta, body=match.group(2).strip())


def load_dir(kb_dir: Path) -> list[KBDocument]:
    """Parse every `*.md` file in `kb_dir`; raises on the first invalid file."""
    docs = []
    for path in sorted(kb_dir.glob("*.md")):
        try:
            doc = parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if path.stem != doc.doc_id:
            raise ValueError(f"{path.name}: file name does not match doc_id {doc.doc_id!r}")
        docs.append(doc)
    return docs
