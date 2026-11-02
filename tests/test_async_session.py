"""AsyncChatSession: the Chainlit entry point (D8.1). Real graph, fake LLM and Jira."""

import asyncio
import threading

from smartdesk.graph import AsyncChatSession, prompts
from tests.graph_helpers import expected_op_id, make_session
from tests.test_ticket_flow import DRAFT, ticket_llm, to_review
from tests.ticket_fake import BROWSE, FakeTicketService


def at_review(service: FakeTicketService | None = None) -> tuple[AsyncChatSession, FakeTicketService]:
    service = service or FakeTicketService()
    session = make_session(ticket_llm(), service)
    to_review(session)
    return AsyncChatSession(session), service


def test_turns_run_on_the_shared_worker_thread():
    session = AsyncChatSession(make_session(ticket_llm()))
    threads = []
    send = session.session.send
    session.session.send = lambda text: threads.append(threading.current_thread().name) or send(text)

    result = asyncio.run(session.send("hi"))
    assert result.replies
    assert threads and threads[0].startswith("smartdesk-turn")
    assert threads[0] != threading.current_thread().name


def test_two_concurrent_approvals_create_exactly_one_ticket():
    session, service = at_review()
    op_id = expected_op_id(DRAFT)

    async def double_click():
        return await asyncio.gather(session.approve(op_id), session.approve(op_id))

    first, second = asyncio.run(double_click())
    assert len(service.created) == 1
    assert first.created_ticket == {"key": "KAN-1", "url": f"{BROWSE}/KAN-1", "already_existed": False}
    assert second.error == "no_pending_approval" and second.text == prompts.NO_PENDING_APPROVAL


def test_a_stale_op_id_is_refused_and_creates_nothing():
    session, service = at_review()

    result = asyncio.run(session.approve("0" * 64))
    assert service.create_calls == []
    assert prompts.REVIEW_STALE in result.text
    assert result.approval is not None and result.approval["op_id"] == expected_op_id(DRAFT)


def test_approve_with_nothing_pending_replies_instead_of_raising():
    session = AsyncChatSession(make_session(ticket_llm()))

    for call in (session.approve(), session.cancel(), session.edit({"priority": "High"})):
        result = asyncio.run(call)
        assert result.error == "no_pending_approval" and result.approval is None


def test_edit_gives_a_new_op_id_and_only_that_one_approves():
    session, service = at_review()
    old_op_id = expected_op_id(DRAFT)

    result = asyncio.run(session.edit({"priority": "High"}))
    new_op_id = expected_op_id({**DRAFT, "priority": "High"})
    assert result.approval["op_id"] == new_op_id != old_op_id

    asyncio.run(session.approve(old_op_id))
    assert service.create_calls == []
    result = asyncio.run(session.approve(new_op_id))
    assert len(service.created) == 1 and result.created_ticket["key"] == "KAN-1"


def test_edited_values_get_the_input_guardrails():
    session, service = at_review()

    result = asyncio.run(session.edit({"summary": " ​\u202E "}))  # only hidden characters
    assert result.error == "empty" and result.approval["op_id"] == expected_op_id(DRAFT)
    assert result.state["ticket_draft"]["summary"] == DRAFT["summary"]

    result = asyncio.run(session.edit({"summary": "Dock​ monitor flickers"}))
    assert result.approval["draft"]["summary"] == "Dock monitor flickers"


def test_created_ticket_is_set_only_on_the_creating_turn():
    session, _ = at_review()

    assert asyncio.run(session.approve()).created_ticket["key"] == "KAN-1"
    assert asyncio.run(session.send("hi")).created_ticket is None
