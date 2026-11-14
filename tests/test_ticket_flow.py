import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

from smartdesk.graph import prompts
from smartdesk.graph.state import Intent as I
from smartdesk.graph.tickets import TicketFieldsUpdate, make_submit_node, summary_from
from smartdesk.rag.answer import GroundedAnswer
from smartdesk.tickets.models import (
    JiraAuthError,
    JiraRequestRejected,
    JiraUnavailable,
    TicketCreationUncertain,
    TicketDraft,
)
from tests.conftest import FakeLLM, FakeRetriever, latest_message
from tests.graph_helpers import EMAIL, MONITOR, MONITOR_TEXT, expected_op_id, make_session
from tests.ticket_fake import BROWSE, FakeTicketService

pytestmark = pytest.mark.rubric("M7-JIRA")

RAISE = "I want to raise a ticket"
DRAFT = {"summary": MONITOR.summary, "description": MONITOR.description, "category": "IT", "priority": None}
STORED_DRAFT = {k: v for k, v in DRAFT.items() if k != "priority"}  # state only holds fields that were set
INTENTS = {
    RAISE: I.CREATE_TICKET,
    MONITOR_TEXT: I.PROVIDE_INFO,
    "continue my ticket": I.CREATE_TICKET,
    "try again": I.CREATE_TICKET,
    "How do I set up the VPN?": I.KNOWLEDGE_QUESTION,
    "Please make it high priority": I.PROVIDE_INFO,
    "hi": I.GREETING,
}


def ticket_llm(intents=None, tickets=None, **kwargs) -> FakeLLM:
    return FakeLLM({**INTENTS, **(intents or {})}, tickets_by_text={MONITOR_TEXT: MONITOR, **(tickets or {})}, **kwargs)


def to_review(session):
    """Raise a ticket, describe it and give the email: ends at the approval interrupt."""
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    result = session.send(EMAIL)
    assert result.approval is not None
    return result


# --- slot-filling and approval ---


@pytest.mark.rubric("B2", "B4", "M7-HITL")
def test_happy_path_collects_fields_then_creates_only_after_approval():
    service = FakeTicketService()
    session = make_session(ticket_llm(), service)

    result = session.send(RAISE)
    assert result.text == prompts.ASK_TICKET_DETAILS
    assert result.state["awaiting"] == "ticket_details" and result.approval is None

    result = session.send(MONITOR_TEXT)
    assert result.state["awaiting"] == "email"
    assert MONITOR.summary in result.text and "email address" in result.text

    result = session.send("  Jane.Doe@NovaTech.example ")
    assert result.state["session_email"] == EMAIL
    assert result.approval["draft"] == {"email": EMAIL, **DRAFT}
    assert result.approval["op_id"] == expected_op_id(DRAFT)
    for shown in (EMAIL, "Category: IT", MONITOR.summary, MONITOR.description, prompts.PRIORITY_NOT_SET):
        assert shown in result.text
    assert service.create_calls == []

    result = session.send("approve")
    assert service.created == [(TicketDraft(email=EMAIL, **DRAFT), expected_op_id(DRAFT))]
    assert result.text == prompts.TICKET_CREATED.format(key="KAN-1", url=f"{BROWSE}/KAN-1")
    assert result.approval is None
    assert result.state["ticket_draft"] == {} and result.state["active_flow"] is None
    assert result.state["last_ticket"]["key"] == "KAN-1"


def test_classifier_is_told_what_smartdesk_is_waiting_for():
    llm = ticket_llm()
    session = make_session(llm)
    session.send(RAISE)
    session.send(MONITOR_TEXT)

    context = llm.calls[-1][1]
    assert isinstance(context, SystemMessage)
    assert prompts.AWAITING_LABELS["ticket_details"] in context.content


def test_extractor_sees_draft_conversation_and_latest_message_as_data():
    llm = ticket_llm()
    session = make_session(llm)
    session.send(RAISE)
    session.send(MONITOR_TEXT)

    system, human = llm.ticket_calls[-1]
    assert system.content == prompts.TICKET_FIELDS_SYSTEM_PROMPT
    assert "<conversation>\nEmployee: I want to raise a ticket\nSmartDesk:" in human.content
    assert human.content.endswith(f"<message>\n{MONITOR_TEXT}\n</message>")


def test_all_fields_in_one_message_go_straight_to_review():
    text = f"Please raise a ticket: {MONITOR_TEXT}. My email is {EMAIL}"
    session = make_session(ticket_llm({text: I.CREATE_TICKET}, {text: MONITOR}))

    result = session.send(text)
    assert result.approval["draft"] == {"email": EMAIL, **DRAFT}


@pytest.mark.rubric("B2")
def test_category_is_inferred_from_the_conversation():
    text = "My payslip shows the wrong tax deduction"
    update = TicketFieldsUpdate(
        description="Payslip shows the wrong tax deduction.", summary="Wrong tax on payslip", category="HR"
    )
    session = make_session(ticket_llm({text: I.PROVIDE_INFO}, {text: update}))
    session.send(RAISE)
    session.send(text)

    assert session.send(EMAIL).approval["draft"]["category"] == "HR"


@pytest.mark.rubric("B2")
def test_unknown_category_is_asked_for():
    text = "Something about my account is wrong"
    update = TicketFieldsUpdate(description="Something about the employee's account is wrong.")
    session = make_session(ticket_llm({text: I.PROVIDE_INFO, "HR": I.PROVIDE_INFO}, {text: update}))
    session.send(RAISE)
    session.send(text)

    result = session.send(EMAIL)
    assert result.state["awaiting"] == "ticket_category"
    assert result.text.endswith(prompts.ASK_TICKET_CATEGORY)

    result = session.send("HR")
    assert result.approval["draft"]["category"] == "HR"
    assert result.approval["draft"]["summary"] == "Something about the employee's account is wrong."  # derived


@pytest.mark.rubric("B2", "A5", "M7-ESC")
def test_accepting_an_escalation_offer_starts_a_ticket_from_the_question():
    question = "Why does my monitor flicker?"
    llm = ticket_llm(
        {question: I.KNOWLEDGE_QUESTION, "yes please": I.CREATE_TICKET},
        {"yes please": MONITOR},
    )
    session = make_session(llm, retriever=FakeRetriever([]))

    result = session.send(question)
    assert result.state["ticket_offered"] is True

    result = session.send("yes please")
    assert prompts.FLOW_CONTEXT_OFFER in llm.calls[-1][1].content
    assert f"Employee: {question}" in llm.ticket_calls[-1][1].content
    assert result.state["ticket_draft"]["summary"] == MONITOR.summary
    assert result.state["awaiting"] == "email"


LAPTOP_TEXT = "I need a new laptop, my manager bob@test.com approved it"
LAPTOP = TicketFieldsUpdate(description="New laptop request, approved by manager bob@test.com.", category="IT")


def test_new_ticket_after_a_created_one_starts_from_a_fresh_draft():
    # Regression: the laptop request was merged with the monitor ticket created just before.
    service = FakeTicketService()
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET}, {LAPTOP_TEXT: LAPTOP})
    session = make_session(llm, service)
    to_review(session)
    session.send("approve")  # ticket A (monitor) created

    result = session.send(LAPTOP_TEXT)

    extractor_input = llm.ticket_calls[-1][1].content
    assert "monitor" not in extractor_input.lower()
    assert '"summary": null' in extractor_input and '"description": null' in extractor_input
    assert result.approval["draft"] == {
        "email": EMAIL, "summary": LAPTOP.description, "description": LAPTOP.description,
        "category": "IT", "priority": None,
    }
    assert result.state["session_email"] == EMAIL  # the manager's address neither locked nor conflicted
    assert result.state["messages"][result.state["ticket_flow_start"]].content == LAPTOP_TEXT
    assert len(service.created) == 1


def test_escalated_question_seeds_the_new_flow_but_earlier_turns_do_not():
    vpn, question = "How do I set up the VPN?", "Why does my monitor flicker on the dock since Monday?"

    def answer(messages):
        if "monitor" in messages[-1].content:
            return GroundedAnswer(evidence="none", sufficient=False, answer="", cited_passages=[])
        return GroundedAnswer(evidence='[1] "..."', sufficient=True, answer="Do the thing [1].", cited_passages=[1])

    llm = ticket_llm({question: I.KNOWLEDGE_QUESTION, "yes": I.CREATE_TICKET}, {"yes": MONITOR}, answer_fn=answer)
    session = make_session(llm)
    session.send(vpn)  # answered: not part of the ticket
    assert session.send(question).state["escalation_reason"] == "insufficient_context"

    result = session.send("yes")

    extractor_input = llm.ticket_calls[-1][1].content
    assert f"Employee: {question}" in extractor_input
    assert vpn not in extractor_input
    assert result.state["ticket_draft"]["description"] == MONITOR.description
    assert result.state["messages"][result.state["ticket_flow_start"]].content == question


VPN_QUESTION = "How do I set up the VPN?"
FOR_IT = "I want to raise a ticket for it"
VPN_TICKET = TicketFieldsUpdate(description="Needs help setting up the VPN after reading the KB steps.", category="IT")


def test_ticket_for_it_after_a_kb_answer_starts_from_that_question():
    llm = ticket_llm({FOR_IT: I.CREATE_TICKET}, {FOR_IT: VPN_TICKET})
    session = make_session(llm)
    assert session.send(VPN_QUESTION).state["citations"]  # answered, not escalated

    result = session.send(FOR_IT)

    assert f"Employee: {VPN_QUESTION}" in llm.ticket_calls[-1][1].content
    assert result.state["messages"][result.state["ticket_flow_start"]].content == VPN_QUESTION
    assert result.state["ticket_draft"]["description"] == VPN_TICKET.description
    assert prompts.ASK_TICKET_DETAILS not in result.text
    assert result.state["awaiting"] == "email"


@pytest.mark.parametrize("between", ["created", "cancelled", "other turn"])
def test_kb_question_never_seeds_a_ticket_past_a_closed_ticket_or_another_turn(between):
    llm = ticket_llm({FOR_IT: I.CREATE_TICKET, "never mind": I.CANCEL, "hi": I.GREETING}, {FOR_IT: VPN_TICKET})
    session = make_session(llm)
    session.send(VPN_QUESTION)
    if between == "created":
        session.send(FOR_IT)
        session.send(EMAIL)
        session.send("approve")
    elif between == "cancelled":
        session.send(FOR_IT)
        session.send("never mind")
    else:
        session.send("hi")

    result = session.send(FOR_IT)

    assert VPN_QUESTION not in llm.ticket_calls[-1][1].content
    assert result.state["messages"][result.state["ticket_flow_start"]].content == FOR_IT


# --- a new ticket request while a draft is on hold ---


def hold_monitor_draft(session):
    to_review(session)
    # Leave review with a turn that does not seed a ticket (a KB question would: see seed_start).
    assert session.send("hi").text.endswith(prompts.ON_HOLD_NOTE)


def test_new_ticket_request_with_a_draft_on_hold_asks_continue_or_new():
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET}, {LAPTOP_TEXT: LAPTOP})
    session = make_session(llm)
    hold_monitor_draft(session)
    extractions = len(llm.ticket_calls)

    result = session.send(LAPTOP_TEXT)
    assert result.text == prompts.HELD_DRAFT_QUESTION.format(summary=MONITOR.summary)
    assert result.state["awaiting"] == "held_draft" and result.approval is None
    assert result.state["ticket_draft"] == STORED_DRAFT
    assert len(llm.ticket_calls) == extractions  # nothing extracted until the employee chooses


@pytest.mark.parametrize("reply", ["new", "Start a new ticket."])
def test_new_discards_the_held_draft_and_starts_from_the_request(reply):
    service = FakeTicketService()
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET}, {LAPTOP_TEXT: LAPTOP})
    session = make_session(llm, service)
    hold_monitor_draft(session)
    session.send(LAPTOP_TEXT)
    classifications = len(llm.calls)

    result = session.send(reply)
    assert len(llm.calls) == classifications  # exact phrase: no LLM routing
    extractor_input = llm.ticket_calls[-1][1].content
    assert extractor_input.endswith(f"<message>\n{LAPTOP_TEXT}\n</message>")
    assert "monitor" not in extractor_input.lower()
    assert result.approval["draft"]["description"] == LAPTOP.description
    assert result.state["messages"][result.state["ticket_flow_start"]].content == LAPTOP_TEXT

    session.send("approve")
    assert [draft.description for draft, _ in service.created] == [LAPTOP.description]


@pytest.mark.parametrize("reply", ["continue", "Continue that one"])
def test_continue_resumes_the_held_draft(reply):
    service = FakeTicketService()
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET}, {LAPTOP_TEXT: LAPTOP})
    session = make_session(llm, service)
    hold_monitor_draft(session)
    session.send(LAPTOP_TEXT)
    extractions = len(llm.ticket_calls)

    result = session.send(reply)
    assert result.approval["op_id"] == expected_op_id(DRAFT)  # the held draft, unchanged
    assert len(llm.ticket_calls) == extractions
    assert service.create_calls == []


@pytest.mark.rubric("D2", "M7-MULTI")
@pytest.mark.parametrize("routed_as", [I.PROVIDE_INFO, I.UNCLEAR])  # K23: the live router said "unclear"
def test_unclear_answer_to_the_held_draft_question_asks_again(routed_as):
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET, "hmm, not sure": routed_as}, {LAPTOP_TEXT: LAPTOP})
    service = FakeTicketService()
    session = make_session(llm, service)
    hold_monitor_draft(session)
    session.send(LAPTOP_TEXT)

    result = session.send("hmm, not sure")
    assert prompts.AWAITING_LABELS["held_draft"] in llm.calls[-1][1].content
    assert result.text == prompts.HELD_DRAFT_REASK + prompts.HELD_DRAFT_QUESTION.format(summary=MONITOR.summary)
    assert result.state["awaiting"] == "held_draft" and result.state["ticket_draft"] == STORED_DRAFT

    # The open question survives, so "new" still starts the laptop ticket (the M7 C6 failure).
    result = session.send("new")
    assert result.state["ticket_draft"]["description"] == LAPTOP.description
    assert service.create_calls == []


@pytest.mark.rubric("D2", "M7-MULTI")
def test_unclear_reply_while_issue_details_are_awaited_asks_for_them_again():
    request = "I need to raise a ticket"
    llm = ticket_llm({request: I.CREATE_TICKET, "hmm": I.UNCLEAR}, {})
    session = make_session(llm)
    assert session.send(request).state["awaiting"] == "ticket_details"

    result = session.send("hmm")
    assert result.text == prompts.ASK_TICKET_DETAILS
    assert result.state["awaiting"] == "ticket_details" and not result.state["ticket_draft"]


@pytest.mark.parametrize("unclear", [I.PROVIDE_INFO, I.CREATE_TICKET])
def test_new_after_the_held_draft_question_was_asked_again_starts_from_the_original_request(unclear):
    # K18: "yes please" is no answer to "continue or new?", so the question is asked again.
    llm = ticket_llm({LAPTOP_TEXT: I.CREATE_TICKET, "yes please": unclear}, {LAPTOP_TEXT: LAPTOP})
    session = make_session(llm)
    hold_monitor_draft(session)
    session.send(LAPTOP_TEXT)
    assert session.send("yes please").state["awaiting"] == "held_draft"

    result = session.send("new")
    assert latest_message(llm.ticket_calls[-1]) == LAPTOP_TEXT
    assert result.state["ticket_draft"]["description"] == LAPTOP.description
    assert "yes please" not in llm.ticket_calls[-1][1].content


def test_escalation_accepted_with_a_draft_on_hold_then_new_starts_from_the_question():
    question = "Why is my headset so quiet?"
    headset = TicketFieldsUpdate(description="Headset volume is very low.", category="IT")

    def answer(messages):
        if "headset" in messages[-1].content:
            return GroundedAnswer(evidence="none", sufficient=False, answer="", cited_passages=[])
        return GroundedAnswer(evidence='[1] "..."', sufficient=True, answer="Do the thing [1].", cited_passages=[1])

    llm = ticket_llm(
        {question: I.KNOWLEDGE_QUESTION, "yes please": I.CREATE_TICKET}, {"yes please": headset}, answer_fn=answer
    )
    session = make_session(llm)
    hold_monitor_draft(session)
    session.send(question)  # escalates

    assert session.send("yes please").state["awaiting"] == "held_draft"
    result = session.send("new")

    extractor_input = llm.ticket_calls[-1][1].content
    assert f"Employee: {question}" in extractor_input and "monitor" not in extractor_input.lower()
    assert result.approval["draft"]["description"] == headset.description
    assert result.state["messages"][result.state["ticket_flow_start"]].content == question


SICK_LEAVE = "How many sick leave days do I get per year?"
NEW_LAPTOP = "Please raise a ticket: I need a new laptop"  # explicit, as the real router needs for create_ticket


def test_draft_on_hold_then_kb_question_then_new_ticket_excludes_the_held_draft():
    # Real path: the draft goes on hold because a KB question is asked at review.
    service = FakeTicketService()
    llm = ticket_llm(
        {SICK_LEAVE: I.KNOWLEDGE_QUESTION, NEW_LAPTOP: I.CREATE_TICKET}, {NEW_LAPTOP: LAPTOP}
    )
    session = make_session(llm, service)
    to_review(session)

    result = session.send(SICK_LEAVE)
    assert result.state["citations"] and result.text.endswith(prompts.ON_HOLD_NOTE)
    assert session.send(NEW_LAPTOP).text == prompts.HELD_DRAFT_QUESTION.format(summary=MONITOR.summary)

    result = session.send("new")

    # What the code controls: the held draft never reaches the extractor. The sick-leave
    # question directly preceded the request, so it is passed as the seed; keeping it out of
    # the draft is the extractor prompt's job (checked live in test_live_openai.py, M7-1).
    extractor_input = llm.ticket_calls[-1][1].content
    assert '"summary": null' in extractor_input and '"description": null' in extractor_input
    assert "monitor" not in extractor_input.lower()
    assert result.state["messages"][result.state["ticket_flow_start"]].content == SICK_LEAVE
    assert result.approval["draft"]["description"] == LAPTOP.description

    session.send("approve")
    assert [draft.description for draft, _ in service.created] == [LAPTOP.description]


def test_no_title_is_kept_before_the_issue_is_described():
    # K2: a bare ticket request made the extractor invent "Support ticket request", which stuck.
    details = TicketFieldsUpdate(description=MONITOR.description, category="IT")
    llm = ticket_llm({}, {RAISE: TicketFieldsUpdate(summary="Support ticket request"), MONITOR_TEXT: details})
    session = make_session(llm)

    assert "summary" not in session.send(RAISE).state["ticket_draft"]
    draft = session.send(MONITOR_TEXT).state["ticket_draft"]
    assert draft["summary"] == summary_from(MONITOR.description)


def test_router_is_told_a_ticket_is_in_progress_before_any_field_is_known():
    llm = ticket_llm()
    session = make_session(llm)
    assert session.send(RAISE).state["ticket_draft"] == {}

    session.send(MONITOR_TEXT)
    assert prompts.FLOW_CONTEXT_DRAFT in llm.calls[-1][1].content


def test_too_long_summary_falls_back_to_one_derived_from_the_description():
    text = "my monitor flickers on the dock since Monday"  # states what the fake extraction contains (K28)
    update = TicketFieldsUpdate(description=MONITOR.description, summary="x" * 300, category="IT")
    session = make_session(ticket_llm({text: I.PROVIDE_INFO}, {text: update}))
    session.send(RAISE)
    session.send(text)

    assert session.send(EMAIL).approval["draft"]["summary"] == MONITOR.description


def test_invalid_description_is_dropped_and_asked_for_again():
    text = "here are the details"
    session = make_session(ticket_llm({text: I.PROVIDE_INFO}, {text: TicketFieldsUpdate(description="x" * 20_001)}))
    session.send(RAISE)

    result = session.send(text)
    assert result.text == prompts.ASK_TICKET_DETAILS
    assert "description" not in result.state["ticket_draft"]


# --- review: edit, cancel, approval binding ---


@pytest.mark.rubric("B3", "M7-HITL")
def test_structured_edit_changes_the_op_id_and_invalidates_the_old_approval():
    service = FakeTicketService()
    session = make_session(ticket_llm(), service)
    old_op_id = to_review(session).approval["op_id"]

    result = session.edit({"priority": "High"})
    new_op_id = result.approval["op_id"]
    assert new_op_id != old_op_id
    assert result.approval["draft"]["priority"] == "High"

    # Replaying the approval of the earlier draft creates nothing.
    session.graph.invoke(Command(resume={"action": "approve", "op_id": old_op_id}), session.config)
    assert service.create_calls == []
    assert prompts.REVIEW_STALE in [m.content for m in session.state()["messages"]]
    assert session.pending_approval()["op_id"] == new_op_id

    session.approve()
    assert service.created == [(TicketDraft(email=EMAIL, **{**DRAFT, "priority": "High"}), new_op_id)]


def test_invalid_structured_edit_is_reported_and_the_draft_kept():
    session = make_session(ticket_llm())
    to_review(session)

    result = session.edit({"priority": "Urgent", "summary": "two\nlines ok"})
    assert prompts.EDIT_REJECTED.format(problems="the priority wasn't valid") in result.text
    assert result.approval["draft"]["priority"] is None
    assert result.approval["draft"]["summary"] == "two lines ok"


def test_free_text_correction_at_review_updates_the_draft_and_asks_again():
    service = FakeTicketService()
    llm = ticket_llm(tickets={"Please make it high priority": TicketFieldsUpdate(priority="High")})
    session = make_session(llm, service)
    to_review(session)

    result = session.send("Please make it high priority")
    assert result.approval["draft"]["priority"] == "High"
    assert result.approval["op_id"] == expected_op_id({**DRAFT, "priority": "High"})
    assert service.create_calls == []


@pytest.mark.rubric("B3", "M7-HITL")
def test_cancel_at_review_creates_nothing():
    service = FakeTicketService()
    session = make_session(ticket_llm(), service)
    to_review(session)

    result = session.send("cancel")
    assert result.text == prompts.TICKET_CANCELLED
    assert result.approval is None and result.state["ticket_draft"] == {}
    assert service.create_calls == []


@pytest.mark.rubric("B3", "M7-HITL")
def test_new_input_while_paused_never_creates_a_ticket():
    # Bypassing ChatSession: a plain "approve" message starts a new turn instead of resuming.
    service = FakeTicketService()
    session = make_session(ticket_llm({"approve": I.CREATE_TICKET}), service)
    to_review(session)

    session.graph.invoke({"messages": [HumanMessage(content="approve")]}, session.config)
    assert service.create_calls == []
    # Routed as a new ticket request while a draft exists: SmartDesk asks continue or new.
    assert session.state()["awaiting"] == "held_draft"


@pytest.mark.rubric("B3", "M7-HITL")
def test_submit_refuses_a_draft_without_a_matching_approval():
    service = FakeTicketService()
    submit = make_submit_node(service)
    state = {"session_email": EMAIL, "ticket_draft": DRAFT, "approved_op_id": "some-other-op", "messages": []}

    result = submit(state, {"configurable": {"thread_id": "t1"}})
    assert result["messages"][0].content == prompts.TICKET_NOT_APPROVED
    assert service.create_calls == []


@pytest.mark.rubric("B4")
def test_same_draft_again_in_the_session_reports_the_existing_ticket():
    again = "raise that same ticket again: my external monitor flickers on the dock, since Monday"
    service = FakeTicketService()
    session = make_session(ticket_llm({again: I.CREATE_TICKET}, {again: MONITOR}), service)
    to_review(session)
    session.send("approve")

    assert session.send(again).approval["op_id"] == expected_op_id(DRAFT)
    result = session.send("approve")
    assert result.text == prompts.TICKET_ALREADY_CREATED.format(key="KAN-1", url=f"{BROWSE}/KAN-1")
    assert len(service.created) == 1


# --- Jira errors ---


def test_jira_unavailable_says_not_created_and_try_again_reuses_op_id():
    service = FakeTicketService(create_errors=[JiraUnavailable("down")])
    session = make_session(ticket_llm(), service)
    to_review(session)

    result = session.send("approve")
    assert result.text == prompts.TICKET_ERROR["jira_unavailable"]
    assert "NOT created" in result.text and "may already" not in result.text
    assert result.state["last_error"] == "jira_unavailable"
    assert result.state["ticket_draft"] == STORED_DRAFT

    result = session.send("try again")  # back through review: approval is asked for again
    assert result.approval["op_id"] == expected_op_id(DRAFT)
    session.send("approve")
    assert [op for _, op in service.create_calls] == [expected_op_id(DRAFT)] * 2
    assert len(service.created) == 1


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (JiraAuthError("401"), "jira_auth"),
        (JiraRequestRejected(400, "bad field"), "jira_rejected"),
        (TicketCreationUncertain("timeout"), "ticket_uncertain"),
    ],
)
@pytest.mark.rubric("F1", "M7-ERR")
def test_jira_errors_get_their_own_message_and_keep_the_draft(error, code):
    session = make_session(ticket_llm(), FakeTicketService(create_errors=[error]))
    to_review(session)

    result = session.send("approve")
    assert result.text == prompts.TICKET_ERROR[code]
    assert result.state["last_error"] == code and result.state["ticket_draft"] == STORED_DRAFT
    assert result.state["approved_op_id"] is None


def test_only_uncertain_creation_says_the_ticket_may_exist():
    assert "may already" in prompts.TICKET_ERROR["ticket_uncertain"]
    assert all("may already" not in text for code, text in prompts.TICKET_ERROR.items() if code != "ticket_uncertain")


def test_ticket_requests_without_jira_explain_it_is_not_configured():
    session = make_session(ticket_llm(), with_tickets=False)
    to_review(session)
    assert session.send("approve").text == prompts.TICKET_ERROR["not_configured"]


# --- intent switches mid-flow ---


@pytest.mark.rubric("D2", "M7-MULTI")
def test_knowledge_question_during_collection_puts_the_draft_on_hold():
    session = make_session(ticket_llm())
    session.send(RAISE)
    session.send(MONITOR_TEXT)  # now waiting for the email

    result = session.send("How do I set up the VPN?")
    assert result.text.startswith("Do the thing [1].")
    assert result.text.endswith(prompts.ON_HOLD_NOTE)
    assert result.state["ticket_draft"] == STORED_DRAFT

    result = session.send("continue my ticket")
    assert result.state["awaiting"] == "email"
    assert session.send(EMAIL).approval["draft"]["summary"] == MONITOR.summary


def test_knowledge_question_at_review_is_answered_and_review_can_resume():
    service = FakeTicketService()
    session = make_session(ticket_llm(), service)
    op_id = to_review(session).approval["op_id"]

    result = session.send("How do I set up the VPN?")
    assert result.text.startswith("Do the thing [1].") and result.text.endswith(prompts.ON_HOLD_NOTE)
    assert result.approval is None

    result = session.send("continue my ticket")
    assert result.approval["op_id"] == op_id
    assert service.create_calls == []


@pytest.mark.rubric("D2", "M7-MULTI")
def test_status_check_during_collection_keeps_the_draft():
    service = FakeTicketService()
    service.add_ticket(EMAIL, "Laptop battery drains fast", status="In Progress", status_category="In Progress")
    llm = ticket_llm({"what's the status of my ticket?": I.TICKET_STATUS})
    session = make_session(llm, service)
    to_review(session)
    session.send("How do I set up the VPN?")  # leave review; draft on hold

    result = session.send("what's the status of my ticket?")
    assert "KAN-1: Laptop battery drains fast" in result.text
    assert result.text.endswith(prompts.ON_HOLD_NOTE)
    assert result.state["ticket_draft"] == STORED_DRAFT


def test_cancel_during_collection_clears_the_draft():
    session = make_session(ticket_llm({"never mind": I.CANCEL}))
    session.send(RAISE)
    session.send(MONITOR_TEXT)

    result = session.send("never mind")
    assert result.text == prompts.TICKET_CANCELLED
    assert result.state["ticket_draft"] == {} and result.state["awaiting"] is None
