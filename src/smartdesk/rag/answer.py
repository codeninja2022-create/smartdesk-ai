"""Grounded answer generation with source citations.

The LLM sees the retrieved chunks as numbered, delimited passages and must
report whether they actually answer the question. Citations shown to the
employee are rebuilt from chunk metadata, never from LLM-written text, so a
source cannot be invented; an answer whose citations do not point at real
passages is treated as ungrounded.
"""

import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from smartdesk.llm import StructuredLLM
from smartdesk.rag import prompts

_CITATION = re.compile(r"\[(\d+)\]")
_TAG = re.compile(r"</?\s*passage[^>]*>", re.I)


class GroundedAnswer(BaseModel):
    """Structured output of the answer step. `evidence` comes first so the
    sufficiency verdict is made after locating support, not before."""

    evidence: str = Field(
        description="Short verbatim quotes from the passages that answer the question, each prefixed with its "
        "passage number, e.g. '[2] \"...\"'. Write 'none' if no passage answers it."
    )
    sufficient: bool = Field(
        description="True if the quoted evidence answers the question (fully or in part); false if it is 'none' "
        "or only on a related topic."
    )
    answer: str = Field(
        description="The answer, using only the passages, with [n] markers after the facts taken from passage n. "
        "Empty if sufficient is false."
    )
    cited_passages: list[int] = Field(
        default_factory=list, description="Numbers of the passages the answer relies on."
    )


@dataclass(frozen=True)
class Citation:
    number: int
    doc_id: str
    title: str
    section: str

    def to_dict(self) -> dict:
        return {"number": self.number, "doc_id": self.doc_id, "title": self.title, "section": self.section}


@dataclass(frozen=True)
class AnswerResult:
    grounded: bool
    text: str  # answer with renumbered [n] markers; empty when not grounded
    citations: list[Citation]
    reason: str | None = None  # why the answer was rejected


def format_passages(chunks: list[dict]) -> str:
    """Render chunks as numbered passages. Delimiter look-alikes inside chunk text are removed."""
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        text = _TAG.sub("", chunk["text"])
        blocks.append(f'<passage number="{number}" source="{chunk["doc_id"]}">\n{text}\n</passage>')
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[dict]) -> list:
    return [
        SystemMessage(content=prompts.ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=f"Passages:\n\n{format_passages(chunks)}\n\nEmployee question: {question}"),
    ]


def finalize(generated: GroundedAnswer, chunks: list[dict]) -> AnswerResult:
    """Validate the LLM's answer against the passages it was given and attach real citations."""
    if not generated.sufficient or not generated.answer.strip():
        return AnswerResult(False, "", [], "insufficient_context")

    valid = range(1, len(chunks) + 1)
    in_text = [int(n) for n in _CITATION.findall(generated.answer)]
    used = [n for n in dict.fromkeys(in_text + generated.cited_passages) if n in valid]
    if not used:
        return AnswerResult(False, "", [], "no_valid_citation")

    # Cite documents, not chunks: passages from the same document share one number.
    doc_numbers: dict[str, int] = {}
    citations: list[Citation] = []
    passage_to_citation: dict[int, int] = {}
    for n in used:
        chunk = chunks[n - 1]
        if chunk["doc_id"] not in doc_numbers:
            doc_numbers[chunk["doc_id"]] = len(citations) + 1
            citations.append(Citation(len(citations) + 1, chunk["doc_id"], chunk["title"], chunk["section"]))
        passage_to_citation[n] = doc_numbers[chunk["doc_id"]]

    def renumber(match: re.Match) -> str:
        n = int(match.group(1))
        return f"[{passage_to_citation[n]}]" if n in passage_to_citation else ""

    text = _CITATION.sub(renumber, generated.answer)
    text = re.sub(r"(\[\d+\])(\1)+", r"\1", text)  # collapse "[1][1]"
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text).strip()
    return AnswerResult(True, text, citations)


def render(result: AnswerResult) -> str:
    sources = "\n".join(f"[{c.number}] {c.title} > {c.section} ({c.doc_id})" for c in result.citations)
    return f"{result.text}\n\nSources:\n{sources}"


def generate_answer(llm: StructuredLLM, question: str, chunks: list[dict]) -> AnswerResult:
    generator = llm.with_structured_output(GroundedAnswer)
    generated = generator.invoke(build_messages(question, chunks))
    assert isinstance(generated, GroundedAnswer)
    return finalize(generated, chunks)
