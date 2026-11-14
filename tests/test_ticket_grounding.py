"""K28: ticket descriptions hold only what the employee said (no invented timing, no filler)."""

import re

import pytest

from smartdesk.graph.state import Intent as I
from smartdesk.graph.tickets import TicketFieldsUpdate, remove_unstated_claims
from smartdesk.rag.answer import GroundedAnswer
from tests.conftest import FakeLLM, FakeRetriever, make_chunk
from tests.graph_helpers import make_session
from tests.ticket_fake import FakeTicketService

pytestmark = pytest.mark.rubric("A4", "B2", "M7-GROUND", "M7-JIRA")

# Written independently of the implementation: any timing/onset claim, and "unknown" filler.
TIMING = re.compile(
    r"\b(recent(ly)?|lately|start(ed|ing)?|began|begin(ning)?|since|ago|yesterday|today|tonight|this morning|"
    r"last (night|week|month)|for (a few|several|\d+) (minutes|hours|days|weeks|months)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|\d{1,2}/\d{1,2})\b",
    re.I,
)
FILLER = re.compile(r"\b(not (been )?(mentioned|specified|stated|provided|described)|did not mention|"
                    r"unspecified|unknown|no (details|information))\b", re.I)

PRINTER = "The printer on the 3rd floor is not working."
EMBELLISHED = (
    "The printer on the 3rd floor is not working. The issue started recently, and the employee has not "
    "mentioned any troubleshooting steps taken. SmartDesk could not find this in the knowledge base."
)  # what the live extractor returned on 2026-11-14 (KAN-22, KAN-23)
GROUNDED = "The printer on the 3rd floor is not working. SmartDesk could not find this in the knowledge base."


def _insufficient(messages):
    return GroundedAnswer(evidence="none", sufficient=False, answer="", cited_passages=[])


def test_a_ticket_conversation_without_timing_never_gets_an_invented_onset_or_filler():
    llm = FakeLLM(
        {PRINTER: I.KNOWLEDGE_QUESTION, "yes please": I.CREATE_TICKET},
        answer_fn=_insufficient,
        tickets_by_text={"yes please": TicketFieldsUpdate(
            description=EMBELLISHED, summary="Printer issue on the 3rd floor", category="IT")},
    )
    service = FakeTicketService()
    session = make_session(llm, service, retriever=FakeRetriever([make_chunk("it-printers", similarity=0.6)]))
    assert session.send(PRINTER).state["escalation_reason"]
    session.send("yes please")

    result = session.send("arjun.mehta@novatech.example")
    description = result.approval["draft"]["description"]
    assert not TIMING.search(description), description
    assert not FILLER.search(description), description
    assert description == GROUNDED  # nothing beyond the employee's words and SmartDesk's KB note
    assert service.create_calls == []


@pytest.mark.parametrize(("description", "employee", "expected"), [
    # timing the employee stated is kept, including a different onset word for it
    ("The monitor has been flickering since yesterday.", "My monitor has been flickering since yesterday",
     "The monitor has been flickering since yesterday."),
    ("The VPN drops. It started on Monday.", "The VPN drops, since Monday", "The VPN drops. It started on Monday."),
    # invented specifics are dropped
    ("The VPN drops. It began on Monday.", "The VPN drops since last week", "The VPN drops."),
    ("Laptop will not charge. This has happened for several days.", "My laptop won't charge",
     "Laptop will not charge."),
    ("Outlook asks for a password. Steps tried: not specified. Impact unknown.", "Outlook keeps asking for my password",
     "Outlook asks for a password."),
    # a grounded description is unchanged
    (GROUNDED, PRINTER, GROUNDED),
])
def test_remove_unstated_claims(description, employee, expected):
    assert remove_unstated_claims(description, employee) == expected
