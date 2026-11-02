"""What the Chainlit UI shows for a turn, as pure functions (no Chainlit import, so testable).

`app.py` turns these into Chainlit messages, actions and elements. Text from
the graph is shown as Markdown with raw HTML disabled (`.chainlit/config.toml`);
KB passages and Jira comments are untrusted, so image syntax is defused.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from smartdesk.graph.session import TurnResult
from smartdesk.kb.chunking import chunk_document
from smartdesk.kb.documents import DOC_ID_PATTERN, parse
from smartdesk.tickets.models import Category, Priority

APPROVE, EDIT, CANCEL, CHOOSE = "approve_ticket", "edit_ticket", "cancel_ticket", "choose_ticket"
LONG_DOC_CHARS = 2000  # longer documents show the cited chunk first
FIELD_LABELS = {"summary": "Summary", "description": "Description", "category": "Category", "priority": "Priority"}
FIELD_CHOICES: dict[str, tuple[str, ...]] = {"category": get_args(Category), "priority": get_args(Priority)}
_DOC_ID = re.compile(DOC_ID_PATTERN)

WELCOME = (
    "Hi, I'm SmartDesk, NovaTech's IT and HR help desk assistant. You can:\n\n"
    "- **Ask an IT or HR question**, e.g. \"How do I connect to the VPN?\"\n"
    "- **Report a problem to raise a ticket**, e.g. \"My laptop won't charge.\"\n"
    "- **Check your tickets**, e.g. \"What's the status of my tickets?\"\n\n"
    "Your email is locked to this chat once you give it. To use a different email, start a **New Chat**."
)

Kind = Literal["normal", "warning", "error"]


@dataclass(frozen=True)
class Button:
    name: str  # the action callback that handles it
    label: str
    payload: dict


def to_markdown(text: str) -> str:
    """Stop untrusted text from loading images. Line breaks need nothing: Chainlit renders pre-wrap."""
    return text.replace("![", "!\\[")


def welcome_text(thread_id: str, jira_on: bool) -> str:
    text = WELCOME
    if not jira_on:
        text += "\n\n_Jira is not configured, so ticket features are off in this deployment._"
    return f"{text}\n\n_Session {thread_id} (resume in the CLI with `python -m smartdesk --session {thread_id}`)_"


def approval_buttons(approval: dict) -> list[Button]:
    op_id = approval["op_id"]  # the draft on screen; an older button is rejected as stale (D5.3)
    return [
        Button(APPROVE, "Approve", {"op_id": op_id}),
        Button(EDIT, "Edit", {"op_id": op_id}),
        Button(CANCEL, "Cancel", {"op_id": op_id}),
    ]


def candidate_buttons(state: dict) -> list[Button]:
    if state.get("awaiting") != "ticket_choice":
        return []
    return [Button(CHOOSE, f"{t['key']}: {t['summary']}"[:80], {"key": t["key"]}) for t in state["status_candidates"]]


def citation_panel(citation: dict, kb_dir: Path) -> str | None:
    """Side-panel text for a cited document: for long documents the cited chunk comes first."""
    doc_id = citation["doc_id"]
    path = kb_dir / f"{doc_id}.md"
    if not _DOC_ID.fullmatch(doc_id) or not path.is_file():
        return None
    doc = parse(path.read_text(encoding="utf-8"))
    # Chainlit stacks every side panel of an answer: a compact numbered heading tells them apart.
    heading = f"### [{citation['number']}] {doc.title}\n\n"
    body = _demote(doc.body)
    if len(doc.body) <= LONG_DOC_CHARS:
        return to_markdown(heading + body)
    # Re-chunk with the ingestion chunker: the exact indexed text, without keeping passages in state (D6.7).
    cited = [c.text.split("\n\n", 1)[-1] for c in chunk_document(doc) if c.metadata["section"] == citation["section"]]
    if not cited:
        return to_markdown(heading + body)
    excerpt = _demote("\n\n".join(cited))
    return to_markdown(
        f"{heading}**Cited section: {citation['section']}**\n\n{excerpt}\n\n---\n\n**Full document**\n\n{body}"
    )


def _demote(markdown: str) -> str:
    """Drop the document's `# Title` line and push its headings two levels down, below the panel heading."""
    markdown = re.sub(r"\A# .*\n+", "", markdown.lstrip())
    return re.sub(r"^(#{2,4}) ", lambda m: "#" * min(len(m.group(1)) + 2, 6) + " ", markdown, flags=re.M)


def cited_in_text(result: TurnResult) -> list[dict]:
    """Citations of this turn's answer: only those whose doc_id appears in the reply."""
    if result.error:
        return []
    return [c for c in result.state.get("citations") or [] if f"({c['doc_id']})" in result.text]


def message_kind(result: TurnResult) -> Kind:
    if result.error in ("llm_unavailable", "internal_error"):
        return "error"
    if result.error is None and result.state.get("last_error"):
        return "warning"
    return "normal"


def created_banner(ticket: dict) -> str:
    link = f"[{ticket['key']}]({ticket['url']})"
    return f"ℹ️ **Already created earlier: {link}**" if ticket["already_existed"] else f"✅ **Ticket created: {link}**"
