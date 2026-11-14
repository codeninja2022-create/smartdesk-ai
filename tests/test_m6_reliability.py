"""Reliability: LLM retries and fallback, graceful turn failures, the router's
history cap, and dropping retrieved chunk text from state."""

import json
import logging

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk.graph import ChatSession, build_graph, prompts
from smartdesk.graph.state import Intent as I
from smartdesk.graph.tickets import TicketFieldsUpdate
from smartdesk.graph.workflow import recent_turns
from smartdesk.llm import get_resilient_chat_model
from smartdesk.rag.answer import GroundedAnswer
from tests.conftest import FakeLLM, FakeRetriever, latest_message, make_chunk
from tests.graph_helpers import EMAIL, MIN_SIMILARITY, MONITOR, MONITOR_TEXT, make_session
from tests.ticket_fake import FakeTicketService

pytestmark = pytest.mark.rubric("F1", "F2", "M7-ERR")

RAISE = "I want to raise a ticket"
GREETING = {"intent": "greeting", "domain": "unknown", "search_query": ""}


# --- LLM retries and fallback, over a mocked OpenAI API ---


class FakeOpenAI:
    """An OpenAI chat-completions endpoint whose status per model can be scripted."""

    def __init__(self, statuses: dict[str, list[int]]) -> None:
        self.statuses = statuses  # model -> statuses of successive requests; the last one repeats
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        self.requests.append(model)
        script = self.statuses[model]
        status = script.pop(0) if len(script) > 1 else script[0]
        if status != 200:  # retry-after-ms keeps the SDK's backoff short in tests
            return httpx.Response(status, headers={"retry-after-ms": "1"}, json={"error": {"message": "boom"}})
        return httpx.Response(200, json={
            "id": "c1", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(GREETING)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })  # fmt: skip

    def count(self, model: str) -> int:
        return self.requests.count(model)


@pytest.fixture
def openai_settings(make_settings):
    def factory(fallback: str = "") -> object:
        return make_settings(
            SMARTDESK_LLM_MODEL="primary-model",
            SMARTDESK_LLM_FALLBACK_MODEL=fallback,
            SMARTDESK_LLM_MAX_RETRIES="2",
            SMARTDESK_LLM_TIMEOUT_SECONDS="7",
        )

    return factory


def chat_session(settings, api: FakeOpenAI) -> ChatSession:
    llm = get_resilient_chat_model(settings, http_client=httpx.Client(transport=httpx.MockTransport(api.handler)))
    graph = build_graph(llm, FakeRetriever(), min_similarity=MIN_SIMILARITY, checkpointer=InMemorySaver())
    return ChatSession(graph, "t1")


def test_primary_and_fallback_share_the_timeout_and_retry_settings(openai_settings):
    llm = get_resilient_chat_model(openai_settings(fallback="fallback-model"))
    for model in (llm.primary, llm.fallback):
        assert model.request_timeout == 7.0 and model.max_retries == 2
    assert llm.fallback.model_name == "fallback-model"


def test_no_fallback_model_configured_by_default(openai_settings):
    assert get_resilient_chat_model(openai_settings()).fallback is None


def test_server_errors_are_retried_then_the_fallback_model_answers(openai_settings):
    api = FakeOpenAI({"primary-model": [500], "fallback-model": [200]})
    result = chat_session(openai_settings(fallback="fallback-model"), api).send("hello")

    assert api.count("primary-model") == 3  # 1 + SMARTDESK_LLM_MAX_RETRIES
    assert api.count("fallback-model") == 1
    assert result.error is None and result.text == prompts.GREETING_REPLY


def test_rate_limit_is_retried_without_the_fallback(openai_settings):
    api = FakeOpenAI({"primary-model": [429, 200], "fallback-model": [200]})
    result = chat_session(openai_settings(fallback="fallback-model"), api).send("hello")

    assert api.requests == ["primary-model", "primary-model"]
    assert result.error is None


def test_without_a_fallback_model_the_employee_gets_a_canned_reply_and_the_next_turn_works(openai_settings):
    api = FakeOpenAI({"primary-model": [500, 500, 500, 200]})
    session = chat_session(openai_settings(), api)

    failed = session.send("hello")
    assert api.count("primary-model") == 3
    assert failed.error == "llm_unavailable"
    assert failed.text == prompts.LLM_UNAVAILABLE and "boom" not in failed.text

    recovered = session.send("hello again")
    assert recovered.error is None and recovered.text == prompts.GREETING_REPLY


def test_when_both_models_fail_the_employee_gets_the_canned_reply(openai_settings):
    api = FakeOpenAI({"primary-model": [503], "fallback-model": [500]})
    result = chat_session(openai_settings(fallback="fallback-model"), api).send("hello")

    assert (api.count("primary-model"), api.count("fallback-model")) == (3, 3)
    assert result.error == "llm_unavailable" and result.text == prompts.LLM_UNAVAILABLE


def test_a_rejected_request_is_neither_retried_nor_sent_to_the_fallback(openai_settings):
    api = FakeOpenAI({"primary-model": [400], "fallback-model": [200]})
    result = chat_session(openai_settings(fallback="fallback-model"), api).send("hello")

    assert api.requests == ["primary-model"]  # a 400 is a bug to surface, not an outage to mask
    assert result.error == "internal_error" and result.text == prompts.INTERNAL_ERROR


# --- graceful failures inside a turn ---


class FailingLLM(FakeLLM):
    """FakeLLM whose classifier or ticket extractor raises for one scripted message."""

    def __init__(self, *args, fail_on: str, error: Exception, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_on, self.error = fail_on, error

    def with_structured_output(self, schema):
        inner = super().with_structured_output(schema)

        def run(messages):
            latest = latest_message(messages) if schema is TicketFieldsUpdate else messages[-1].content
            if latest == self.fail_on:
                raise self.error
            return inner.invoke(messages)

        return RunnableLambda(run)


def test_unexpected_error_gets_a_safe_reply_and_only_its_type_is_logged(caplog):
    error = RuntimeError(f"database password=hunter2 for {EMAIL}")
    llm = FailingLLM({"hello": I.GREETING, "again": I.GREETING}, fail_on="hello", error=error)
    session = make_session(llm)

    with caplog.at_level(logging.DEBUG):
        failed = session.send("hello")
    assert failed.error == "internal_error" and failed.text == prompts.INTERNAL_ERROR
    assert "RuntimeError" in caplog.text
    assert "hunter2" not in caplog.text and EMAIL not in caplog.text

    assert session.send("again").text == prompts.GREETING_REPLY


def test_failure_during_collection_keeps_the_draft():
    broken = "it also crashes when I unplug it"
    llm = FailingLLM(
        {RAISE: I.CREATE_TICKET, MONITOR_TEXT: I.PROVIDE_INFO, broken: I.PROVIDE_INFO},
        tickets_by_text={MONITOR_TEXT: MONITOR},
        fail_on=broken,
        error=RuntimeError("extractor down"),
    )
    session = make_session(llm)
    session.send(RAISE)
    session.send(MONITOR_TEXT)  # draft complete; SmartDesk asks for the email

    failed = session.send(broken)
    assert failed.text == f"{prompts.INTERNAL_ERROR} {prompts.DRAFT_SAVED}"
    assert failed.state["ticket_draft"]["summary"] == MONITOR.summary


def test_failure_while_handling_a_review_reply_never_creates_a_ticket():
    # A reply at review resumes the interrupt; if handling it fails, that resume is spent.
    # The draft survives and is shown for review again; nothing is created until approved anew.
    correction = "Actually it is the laptop screen"
    service = FakeTicketService()
    llm = FailingLLM(
        {RAISE: I.CREATE_TICKET, MONITOR_TEXT: I.PROVIDE_INFO, correction: I.PROVIDE_INFO, "ok": I.PROVIDE_INFO},
        tickets_by_text={MONITOR_TEXT: MONITOR},
        fail_on=correction,
        error=RuntimeError("extractor down"),
    )
    session = make_session(llm, service)
    session.send(RAISE)
    session.send(MONITOR_TEXT)
    op_id = session.send(EMAIL).approval["op_id"]

    failed = session.send(correction)
    assert failed.error == "internal_error" and prompts.DRAFT_SAVED in failed.text
    assert failed.approval is None

    again = session.send("ok")
    assert again.approval is not None and again.approval["op_id"] == op_id  # same draft, back at review
    assert service.create_calls == []
    assert session.send("approve").text.startswith("Your ticket has been created: KAN-1")


# --- the router sees only recent turns; stored history is never trimmed ---


def test_recent_turns_starts_at_the_nth_last_employee_message():
    messages = [HumanMessage(content=str(n)) for n in range(5)]
    assert [m.content for m in recent_turns(messages, 2)] == ["3", "4"]
    assert recent_turns(messages, 10) == messages


def test_router_gets_only_the_last_turns_but_state_keeps_all_messages():
    texts = [f"hi {n}" for n in range(30)]
    llm = FakeLLM({text: I.GREETING for text in texts})
    session = make_session(llm)
    for text in texts:
        session.send(text)

    routed = llm.calls[-1]
    assert isinstance(routed[0], SystemMessage)
    assert routed[1].content == "hi 26"  # 4 turns: hi 26..hi 29 and the 3 replies between them
    assert len(routed) == 1 + 7
    assert len(session.state()["messages"]) == 60


def test_router_with_one_turn_still_gets_the_flow_state_line():
    llm = FakeLLM({RAISE: I.CREATE_TICKET, MONITOR_TEXT: I.PROVIDE_INFO}, tickets_by_text={MONITOR_TEXT: MONITOR})
    graph = build_graph(
        llm,
        FakeRetriever(),
        min_similarity=MIN_SIMILARITY,
        ticket_service=FakeTicketService(),
        checkpointer=InMemorySaver(),
        router_history_turns=1,
    )
    session = ChatSession(graph, "t1")
    session.send(RAISE)
    session.send(MONITOR_TEXT)

    routed = llm.calls[-1]
    assert len(routed) == 3
    assert routed[1].content.startswith(prompts.FLOW_CONTEXT_HEADER)
    assert routed[2].content == MONITOR_TEXT


# --- retrieved chunk text is dropped once the answer step is done ---

PASSAGE = "Hold the reset button for 10 seconds (marker-7f3a)."


def insufficient(messages):
    return GroundedAnswer(evidence="none", sufficient=False, answer="", cited_passages=[])


@pytest.mark.parametrize(
    ("similarity", "answer_fn", "escalation"),
    [(0.8, None, None), (0.8, insufficient, "insufficient_context"), (0.1, None, "low_similarity")],
    ids=["answered", "ungrounded", "low-similarity"],
)
def test_state_keeps_only_ids_and_similarity_of_retrieved_chunks(similarity, answer_fn, escalation):
    question = "How do I reset the router?"
    llm = FakeLLM({question: I.KNOWLEDGE_QUESTION}, answer_fn=answer_fn)
    retriever = FakeRetriever([make_chunk("it-router-reset", similarity=similarity, text=PASSAGE)])
    session = make_session(llm, retriever=retriever)

    result = session.send(question)

    assert result.state["escalation_reason"] == escalation
    assert result.state["retrieved"] == [
        {"chunk_id": "it-router-reset#section-steps", "doc_id": "it-router-reset", "similarity": similarity}
    ]
    if similarity > MIN_SIMILARITY:
        assert PASSAGE in llm.answer_calls[0][1].content  # the answer step did see the passage
    latest = session.graph.checkpointer.get_tuple(session.config).checkpoint
    assert "marker-7f3a" not in repr(latest)
