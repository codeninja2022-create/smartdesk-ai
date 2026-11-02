import pytest

from smartdesk.graph import ChatSession, build_graph, open_checkpointer, prompts
from smartdesk.graph.identity import find_email_claim, mask_email
from smartdesk.graph.session import resume_for_text
from smartdesk.graph.state import Intent as I
from smartdesk.graph.tickets import TicketFieldsUpdate
from tests.conftest import FakeLLM, FakeRetriever
from tests.graph_helpers import EMAIL, MIN_SIMILARITY, MONITOR, MONITOR_TEXT, make_session
from tests.ticket_fake import FakeTicketService

OTHER = "someone.else@novatech.example"
COLLEAGUE = "bob.lee@novatech.example"
RAISE = "I want to raise a ticket"
STATUS = "what's the status of my ticket?"
INTENTS = {RAISE: I.CREATE_TICKET, MONITOR_TEXT: I.PROVIDE_INFO, STATUS: I.TICKET_STATUS}


# --- which emails count as the employee's own ---


@pytest.mark.parametrize(
    ("text", "awaiting", "expected"),
    [
        (EMAIL, False, EMAIL),
        (f"  It's {EMAIL.upper()}. ", False, EMAIL),
        (f"sure, use {EMAIL} thanks", False, EMAIL),
        (f"my email is {EMAIL}", False, EMAIL),
        (f"Hi! My work email address is {EMAIL}, can you check my tickets?", False, EMAIL),
        (f"email: {EMAIL}", False, EMAIL),
        (f"my colleague {COLLEAGUE} can't open the shared drive", False, None),
        (f"please cc {COLLEAGUE} on the ticket", False, None),
        (f"contact {COLLEAGUE} if you need more details", False, None),
        (f"you can reach me at {EMAIL}", True, EMAIL),  # SmartDesk asked: the first address is the answer
        ("no email here", True, None),
    ],
)
def test_find_email_claim(text, awaiting, expected):
    claim = find_email_claim(text, awaiting_email=awaiting)
    assert (claim.email if claim else None) == expected


def test_invalid_address_is_a_claim_without_an_email():
    claim = find_email_claim("jane@nowhere", awaiting_email=True)
    assert claim is not None and claim.raw == "jane@nowhere" and claim.email is None


def test_mask_email():
    assert mask_email(EMAIL) == "j***@novatech.example"


# --- the session lock in conversations ---


def test_colleague_email_in_the_description_does_not_lock_the_session():
    text = f"Please raise a ticket: my colleague {COLLEAGUE} can't open the shared drive"
    update = TicketFieldsUpdate(
        description=f"Colleague {COLLEAGUE} can't open the shared drive.", summary="Shared drive access", category="IT"
    )
    session = make_session(FakeLLM({text: I.CREATE_TICKET}, tickets_by_text={text: update}))

    result = session.send(text)
    assert result.state.get("session_email") is None
    assert result.state["awaiting"] == "email"

    result = session.send(EMAIL)
    assert result.approval["draft"]["email"] == EMAIL
    assert COLLEAGUE in result.approval["draft"]["description"]


def test_colleague_email_after_locking_does_not_trigger_the_lock_message():
    text = f"please cc {COLLEAGUE}, he has the same problem"
    session = make_session(FakeLLM({**INTENTS, text: I.PROVIDE_INFO}, tickets_by_text={MONITOR_TEXT: MONITOR}))
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    session.send(EMAIL)  # locked; now at review
    assert session.pending_approval() is not None

    result = session.send(text)
    assert prompts.EMAIL_LOCKED_REPLY.format(email=mask_email(EMAIL)) not in result.text
    assert result.state["session_email"] == EMAIL
    assert result.approval is not None  # the remark went to collect_ticket and back to review


def test_a_different_email_is_refused_and_lookups_keep_the_locked_one():
    service = FakeTicketService()
    switch = f"actually my email is {OTHER}"
    session = make_session(FakeLLM({**INTENTS, switch: I.PROVIDE_INFO}), service)
    session.send(STATUS)
    session.send(EMAIL)

    result = session.send(switch)
    assert result.text == prompts.EMAIL_LOCKED_REPLY.format(email="j***@novatech.example")
    assert result.state["session_email"] == EMAIL

    session.send(STATUS)
    assert service.list_calls == [EMAIL, EMAIL]


def test_same_email_in_other_case_is_accepted_silently():
    again = f"my email is {EMAIL.upper()}"
    session = make_session(FakeLLM({**INTENTS, again: I.PROVIDE_INFO}))
    session.send(STATUS)
    session.send(EMAIL)

    result = session.send(again)
    assert result.state["email_event"] is None
    assert prompts.EMAIL_LOCKED_REPLY.split(",")[0].format(email="") not in result.text


def test_invalid_email_is_asked_for_again_and_nothing_is_locked():
    session = make_session(FakeLLM(INTENTS, tickets_by_text={MONITOR_TEXT: MONITOR}))
    session.send(RAISE)
    session.send(MONITOR_TEXT)

    result = session.send("jane@nowhere")
    assert result.text.startswith(prompts.INVALID_EMAIL)
    assert result.state.get("session_email") is None and result.state["awaiting"] == "email"


def test_email_cannot_be_edited_at_review():
    session = make_session(FakeLLM(INTENTS, tickets_by_text={MONITOR_TEXT: MONITOR}))
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    session.send(EMAIL)

    result = session.edit({"email": OTHER})
    assert prompts.EMAIL_NOT_EDITABLE in result.text
    assert result.approval["draft"]["email"] == EMAIL


def test_email_is_not_asked_again_later_in_the_session():
    service = FakeTicketService()
    session = make_session(FakeLLM(INTENTS, tickets_by_text={MONITOR_TEXT: MONITOR}), service)
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    session.send(EMAIL)
    session.send("approve")

    result = session.send(STATUS)
    assert "email address" not in result.text
    assert result.text.startswith("KAN-1:")
    assert service.list_calls == [EMAIL]


def test_threads_have_separate_email_locks():
    llm = FakeLLM(INTENTS)
    service = FakeTicketService()
    first = make_session(llm, service, thread_id="a")
    first.send(STATUS)
    first.send(EMAIL)

    second = ChatSession(first.graph, "b")
    assert second.send(STATUS).state["awaiting"] == "email"
    assert second.send(OTHER).state["session_email"] == OTHER
    assert first.state()["session_email"] == EMAIL


# --- ChatSession ---


@pytest.mark.parametrize("text", ["approve", "Yes", " y ", "Confirm.", "yes, create it", "Yes please!"])
def test_approval_words_approve_the_op_shown(text):
    assert resume_for_text(text, "op-1") == {"action": "approve", "op_id": "op-1"}


@pytest.mark.parametrize("text", ["cancel", "No", "n", "don't create it"])
def test_cancel_words_cancel(text):
    assert resume_for_text(text, "op-1") == {"action": "cancel"}


@pytest.mark.parametrize("text", ["yes but change the summary", "looks fine I guess", "approve it after lunch"])
def test_anything_else_is_a_message(text):
    assert resume_for_text(text, "op-1") == {"action": "message", "text": text}


def test_approve_without_a_pending_ticket_is_an_error():
    session = make_session(FakeLLM({}))
    with pytest.raises(RuntimeError):
        session.approve()


# --- persistence ---


def test_pending_approval_survives_a_restart(tmp_path):
    db = tmp_path / "smartdesk.db"
    llm = FakeLLM(INTENTS, tickets_by_text={MONITOR_TEXT: MONITOR})
    service = FakeTicketService()

    def start() -> ChatSession:
        checkpointer = open_checkpointer(db)
        graph = build_graph(
            llm, FakeRetriever(), min_similarity=MIN_SIMILARITY, ticket_service=service, checkpointer=checkpointer
        )
        return ChatSession(graph, "session-1")

    session = start()
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    op_id = session.send(EMAIL).approval["op_id"]
    session.graph.checkpointer.conn.close()

    restarted = start()  # a new process: new connection, new graph, same thread id
    assert restarted.pending_approval()["op_id"] == op_id
    assert restarted.state()["session_email"] == EMAIL
    assert [m.content for m in restarted.state()["messages"]][:2] == [RAISE, prompts.ASK_TICKET_DETAILS]

    result = restarted.send("approve")
    assert result.text.startswith("Your ticket has been created: KAN-1")
    assert [op for _, op in service.created] == [op_id]
    restarted.graph.checkpointer.conn.close()
