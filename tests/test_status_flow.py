import pytest

from smartdesk.graph import prompts
from smartdesk.graph.state import Intent as I
from smartdesk.graph.status import choice_number, find_ticket_key, render_listing
from smartdesk.tickets.models import JiraAuthError, JiraUnavailable, TicketComment
from tests.conftest import FakeLLM
from tests.graph_helpers import EMAIL, make_session
from tests.ticket_fake import BROWSE, FakeTicketService

STATUS = "What's the status of my ticket?"
STATUS_WITH_EMAIL = f"What's the status of my ticket? My email is {EMAIL}"
VPN_REF = "Did anyone look at my VPN issue?"
INTENTS = {
    STATUS: I.TICKET_STATUS,
    STATUS_WITH_EMAIL: I.TICKET_STATUS,
    VPN_REF: I.TICKET_STATUS,
    "9": I.PROVIDE_INFO,
    EMAIL: I.PROVIDE_INFO,  # an unprompted email still goes through the classifier
}
COMMENT = TicketComment(author="Alex (IT)", created="2026-11-01T11:00:00.000+0000", body="Replacing the dock today.")


def status_llm(**kwargs) -> FakeLLM:
    return FakeLLM(INTENTS, **kwargs)


def three_tickets(service: FakeTicketService) -> None:
    service.add_ticket(EMAIL, "VPN drops every hour", status="In Progress", status_category="In Progress")
    service.add_ticket(EMAIL, "Old laptop return", status="Done", status_category="Done")
    service.add_ticket(EMAIL, "Payslip question", status="To Do", status_category="To Do")


def test_asks_for_email_then_looks_up_tickets():
    service = FakeTicketService()
    session = make_session(status_llm(), service)

    result = session.send(STATUS)
    assert result.text == prompts.ASK_EMAIL.format(purpose=prompts.EMAIL_PURPOSE["status"])
    assert result.state["awaiting"] == "email" and service.list_calls == []

    result = session.send(EMAIL)
    assert service.list_calls == [EMAIL]
    assert result.text == prompts.NO_TICKETS.format(email=EMAIL)


def test_no_tickets_says_so_and_offers_a_ticket():
    session = make_session(status_llm(), FakeTicketService())
    result = session.send(STATUS_WITH_EMAIL)

    assert result.text == prompts.NO_TICKETS.format(email=EMAIL)
    assert result.state["ticket_offered"] is True and result.state["active_flow"] is None


def test_single_ticket_shows_status_link_and_support_comments():
    service = FakeTicketService()
    service.add_ticket(EMAIL, "Monitor flickers", status="In Progress", status_category="In Progress", comments=[COMMENT])
    result = make_session(status_llm(), service).send(STATUS_WITH_EMAIL)

    assert result.text.splitlines()[:4] == [
        "KAN-1: Monitor flickers", "Status: In Progress", "Last updated: 2026-11-01 10:01", f"Link: {BROWSE}/KAN-1",
    ]
    assert "Updates from the support team:\n- Alex (IT) (2026-11-01 11:00): Replacing the dock today." in result.text
    assert service.get_calls == [(EMAIL, "KAN-1")]


def test_ticket_without_comments_says_no_updates_yet():
    service = FakeTicketService()
    service.add_ticket(EMAIL, "Monitor flickers")
    result = make_session(status_llm(), service).send(STATUS_WITH_EMAIL)
    assert result.text.endswith(prompts.NO_COMMENTS)


def test_multiple_tickets_are_listed_open_first_and_selected_by_number():
    service = FakeTicketService()
    three_tickets(service)
    session = make_session(status_llm(), service)

    result = session.send(STATUS_WITH_EMAIL)
    assert result.state["awaiting"] == "ticket_choice"
    assert [t["key"] for t in result.state["status_candidates"]] == ["KAN-3", "KAN-1", "KAN-2"]  # Done last
    assert result.text == prompts.CHOOSE_TICKET.format(count=3, listing=render_listing(result.state["status_candidates"]))

    result = session.send("2")
    assert result.text.startswith("KAN-1: VPN drops every hour")
    assert result.state["awaiting"] is None and result.state["status_candidates"] == []


@pytest.mark.parametrize(("reply", "key"), [("kan-2", "KAN-2"), ("the first one", "KAN-3"), ("#3", "KAN-2")])
def test_ticket_can_be_chosen_by_key_or_position(reply, key):
    service = FakeTicketService()
    three_tickets(service)
    session = make_session(FakeLLM({**INTENTS, reply: I.PROVIDE_INFO}), service)
    session.send(STATUS_WITH_EMAIL)

    assert session.send(reply).text.startswith(f"{key}:")


def test_invalid_choice_lists_the_tickets_again():
    service = FakeTicketService()
    three_tickets(service)
    session = make_session(status_llm(), service)
    session.send(STATUS_WITH_EMAIL)

    result = session.send("9")
    assert result.text.startswith(prompts.CHOICE_NOT_UNDERSTOOD)
    assert result.state["awaiting"] == "ticket_choice"
    assert service.get_calls == []


def test_a_reference_to_one_ticket_is_resolved_without_listing():
    service = FakeTicketService()
    three_tickets(service)
    service.tickets["KAN-1"][1].comments.append(COMMENT)
    llm = status_llm(choices_by_text={VPN_REF: 2})  # VPN is #2 in the open-first order
    session = make_session(llm, service)
    session.send(EMAIL)  # lock the email first

    result = session.send(VPN_REF)
    assert result.text.startswith("KAN-1: VPN drops every hour")
    sent = llm.choice_calls[0][1].content
    assert "2. KAN-1: VPN drops every hour" in sent and COMMENT.body not in sent


def test_ticket_key_in_the_message_is_looked_up_for_the_session_email_only():
    service = FakeTicketService()
    service.add_ticket("someone.else@novatech.example", "Not yours")
    text = "status of KAN-1 please"
    session = make_session(FakeLLM({**INTENTS, text: I.TICKET_STATUS}), service)
    session.send(EMAIL)

    result = session.send(text)
    assert result.text == prompts.TICKET_NOT_FOUND.format(key="KAN-1", email=EMAIL)
    assert service.get_calls == [(EMAIL, "KAN-1")]


@pytest.mark.parametrize(("error", "code"), [(JiraUnavailable("down"), "jira_unavailable"), (JiraAuthError("401"), "jira_auth")])
def test_lookup_errors_get_a_clear_message(error, code):
    result = make_session(status_llm(), FakeTicketService(read_errors=[error])).send(STATUS_WITH_EMAIL)
    assert result.text == prompts.STATUS_ERROR[code]
    assert result.state["last_error"] == code


def test_status_without_jira_explains_it_is_not_configured():
    result = make_session(status_llm(), with_tickets=False).send(STATUS_WITH_EMAIL)
    assert result.text == prompts.STATUS_ERROR["not_configured"]


@pytest.mark.parametrize(
    ("text", "count", "expected"),
    [("2", 3, 2), ("#1", 3, 1), ("number 3.", 3, 3), ("the second one", 3, 2), ("last", 3, 3), ("4", 3, None),
     ("0", 3, None), ("the VPN one", 3, None), ("2 and 3", 3, None)],
)
def test_choice_number(text, count, expected):
    assert choice_number(text, count) == expected


@pytest.mark.parametrize(
    ("text", "key"),
    [("status of kan-12?", "KAN-12"), ("KAN-7", "KAN-7"), ("my e-mail and wi-fi", None), (EMAIL, None)],
)
def test_find_ticket_key(text, key):
    assert find_ticket_key(text) == key
