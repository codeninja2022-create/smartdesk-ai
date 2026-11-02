"""Builders for scripted multi-turn graph tests, driven through ChatSession."""

from langgraph.checkpoint.memory import InMemorySaver

from smartdesk.graph import ChatSession, build_graph
from smartdesk.graph.tickets import TicketFieldsUpdate
from smartdesk.tickets.models import TicketDraft, derive_op_id
from tests.conftest import FakeLLM, FakeRetriever
from tests.ticket_fake import FakeTicketService

EMAIL = "jane.doe@novatech.example"
THREAD = "t1"
MIN_SIMILARITY = 0.35

# A complete issue description as the extractor would return it.
MONITOR_TEXT = "My external monitor flickers when docked, since Monday"
MONITOR = TicketFieldsUpdate(
    description="External monitor flickers when connected to the dock, since Monday.",
    summary="External monitor flickers when docked",
    category="IT",
)


def make_session(
    llm: FakeLLM,
    service: FakeTicketService | None = None,
    *,
    retriever: FakeRetriever | None = None,
    checkpointer=None,
    thread_id: str = THREAD,
    with_tickets: bool = True,
) -> ChatSession:
    graph = build_graph(
        llm,
        retriever or FakeRetriever(),
        min_similarity=MIN_SIMILARITY,
        ticket_service=(service if service is not None else FakeTicketService()) if with_tickets else None,
        checkpointer=checkpointer or InMemorySaver(),
    )
    return ChatSession(graph, thread_id)


def expected_op_id(draft: dict, email: str = EMAIL, thread_id: str = THREAD) -> str:
    return derive_op_id(thread_id, TicketDraft(email=email, **draft))
