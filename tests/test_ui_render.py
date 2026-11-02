"""What the Chainlit UI shows for a turn (smartdesk.ui.render) and the app's logging setup."""

import asyncio
import importlib
import inspect
import logging
import sys
from pathlib import Path

from smartdesk.graph.session import TurnResult
from smartdesk.kb.documents import KBDocument, Provenance, SourceType, render
from smartdesk.redaction import RedactingFilter
from smartdesk.ui import render as ui

KB_DIR = Path("data/kb")
LONG_DOC = "hr-anti-bribery"
CITED_SECTION = "Prohibited Payments"
APPROVAL = {"type": "ticket_approval", "op_id": "a" * 64, "draft": {}, "text": "Here's the ticket"}


def result(text: str = "Answer [1]", state: dict | None = None, error: str | None = None, **kwargs) -> TurnResult:
    return TurnResult([text], kwargs.get("approval"), state or {}, error=error)


def write_doc(kb_dir: Path, doc_id: str, body: str) -> None:
    doc = KBDocument(
        doc_id=doc_id, title="Guest Wi-Fi", domain="IT", category="Network", subcategory="Wi-Fi",
        provenance=Provenance(
            source_type=SourceType.SYNTHETIC, generator_model="gpt-4o-mini", generated_at="2026-10-31"
        ),
        body=body,
    )
    (kb_dir / f"{doc_id}.md").write_text(render(doc), encoding="utf-8")


# --- buttons ---


def test_approval_buttons_carry_the_op_id_on_screen():
    buttons = ui.approval_buttons(APPROVAL)
    assert [b.name for b in buttons] == [ui.APPROVE, ui.EDIT, ui.CANCEL]
    assert all(b.payload == {"op_id": "a" * 64} for b in buttons)


def test_candidate_buttons_only_while_choosing_a_ticket():
    candidates = [{"key": "KAN-7", "summary": "Monitor flickers"}, {"key": "KAN-9", "summary": "Laptop"}]
    buttons = ui.candidate_buttons({"awaiting": "ticket_choice", "status_candidates": candidates})
    assert [(b.name, b.label, b.payload) for b in buttons] == [
        (ui.CHOOSE, "KAN-7: Monitor flickers", {"key": "KAN-7"}),
        (ui.CHOOSE, "KAN-9: Laptop", {"key": "KAN-9"}),
    ]
    assert ui.candidate_buttons({"awaiting": None, "status_candidates": candidates}) == []


# --- citations ---


def test_long_document_panel_shows_the_cited_chunk_first():
    assert len((KB_DIR / f"{LONG_DOC}.md").read_text(encoding="utf-8")) > ui.LONG_DOC_CHARS
    panel = ui.citation_panel({"doc_id": LONG_DOC, "section": CITED_SECTION, "number": 2}, KB_DIR)

    assert panel.startswith("### [2] Anti-Bribery and Gifts Policy")
    head, full = panel.split("**Full document**")
    assert f"**Cited section: {CITED_SECTION}**" in head
    assert "strictly prohibits offering, giving, receiving" in head
    assert "Anti-Bribery and Gifts Policy >" not in head  # the chunk's context header is not repeated
    assert f"#### {CITED_SECTION}" in full  # headings demoted below the panel heading
    assert "\n# " not in panel and "\n## " not in panel


def test_short_document_panel_is_the_whole_document(tmp_path):
    write_doc(tmp_path, "it-guest-wifi", "# Guest Wi-Fi\n\nConnect to NovaGuest.\n\n## Access\n\nAsk reception.")
    panel = ui.citation_panel({"doc_id": "it-guest-wifi", "section": "Access", "number": 1}, tmp_path)
    assert panel.startswith("### [1] Guest Wi-Fi") and "Full document" not in panel
    assert "#### Access" in panel and "Connect to NovaGuest." in panel


def test_unknown_section_falls_back_to_the_full_document():
    panel = ui.citation_panel({"doc_id": LONG_DOC, "section": "No such section", "number": 1}, KB_DIR)
    assert panel.startswith("### [1] Anti-Bribery and Gifts Policy") and "Cited section" not in panel


def test_missing_or_invalid_doc_ids_give_no_panel(tmp_path):
    (tmp_path / "secret.md").write_text("not a KB document", encoding="utf-8")
    assert ui.citation_panel({"doc_id": "it-missing-doc", "section": "x"}, KB_DIR) is None
    assert ui.citation_panel({"doc_id": "../secret", "section": "x"}, tmp_path / "kb") is None


def test_only_citations_named_in_the_reply_and_never_on_an_error():
    citations = [{"doc_id": "it-vpn-setup", "number": 1}, {"doc_id": "hr-leave", "number": 2}]
    state = {"citations": citations}
    assert ui.cited_in_text(result("Use the client [1].\n\nSources:\n[1] VPN > Setup (it-vpn-setup)", state)) == [
        citations[0]
    ]
    assert ui.cited_in_text(result("(it-vpn-setup)", state, error="too_long")) == []


# --- errors, text and welcome ---


def test_message_kinds():
    assert ui.message_kind(result(error="llm_unavailable")) == "error"
    assert ui.message_kind(result(error="internal_error")) == "error"
    assert ui.message_kind(result(state={"last_error": "jira_unavailable"})) == "warning"
    # a rejected input or a stale button keeps the previous turn's state: no stale warning
    assert ui.message_kind(result(state={"last_error": "jira_unavailable"}, error="too_long")) == "normal"
    assert ui.message_kind(result(error="no_pending_approval")) == "normal"
    assert ui.message_kind(result()) == "normal"


def test_markdown_keeps_line_breaks_as_is_and_defuses_images():
    # Chainlit renders paragraphs pre-wrap: adding hard breaks would double every line break
    assert ui.to_markdown("Email: a\nCategory: IT\n\nDescription") == "Email: a\nCategory: IT\n\nDescription"
    assert "![" not in ui.to_markdown("see ![x](https://tracker.example/p.png)")


def test_welcome_suggests_the_three_flows_and_new_chat():
    text = ui.welcome_text("t-123", jira_on=True)
    for shown in ("Ask an IT or HR question", "raise a ticket", "Check your tickets", "New Chat", "t-123"):
        assert shown in text
    assert "not configured" not in text
    assert "ticket features are off" in ui.welcome_text("t-123", jira_on=False)


def test_created_banner_links_the_ticket():
    ticket = {"key": "KAN-7", "url": "https://x.atlassian.net/browse/KAN-7", "already_existed": False}
    assert ui.created_banner(ticket) == "✅ **Ticket created: [KAN-7](https://x.atlassian.net/browse/KAN-7)**"
    assert "Already created earlier" in ui.created_banner({**ticket, "already_existed": True})


def test_app_installs_log_redaction(monkeypatch):
    monkeypatch.setattr(logging.getLogger(), "handlers", [])  # isolate from pytest's capture handlers
    monkeypatch.delitem(sys.modules, "smartdesk.ui.app", raising=False)
    importlib.import_module("smartdesk.ui.app")

    handlers = logging.getLogger().handlers
    assert handlers and all(any(isinstance(f, RedactingFilter) for f in h.filters) for h in handlers)


def test_guarded_handlers_accept_chainlit_keyword_arguments():
    # Chainlit calls action callbacks as handler(action=...), by the wrapped signature's names
    app = importlib.import_module("smartdesk.ui.app")
    seen = []

    async def on_click(action):
        seen.append(action)

    guarded = app._guarded(on_click)
    assert list(inspect.signature(guarded).parameters) == ["action"]
    asyncio.run(guarded(action="clicked"))
    assert seen == ["clicked"]
