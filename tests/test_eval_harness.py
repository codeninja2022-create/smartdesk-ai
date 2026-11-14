"""Offline tests for the M7 evaluation harness: budget, caching, token log, timing, run marker."""

import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI

from smartdesk.eval import harness
from smartdesk.eval.harness import (
    CALL_RESERVE_USD,
    BudgetExceeded,
    CachedEmbedder,
    CallLog,
    CostTracker,
    SQLiteLLMCache,
    Timer,
    cost_usd,
    percentile,
    price_for,
    prior_spend_usd,
    write_run_marker,
)


def test_price_matches_dated_snapshots_and_charges_unknown_models_the_highest_rate():
    assert price_for("gpt-4o-mini-2024-07-18") == harness.PRICES["gpt-4o-mini"]
    assert price_for("gpt-4o-2024-08-06") == harness.PRICES["gpt-4o"]
    assert price_for("some-new-model") == max(harness.PRICES.values())


def test_cost_is_tokens_times_price_per_million():
    price_in, price_out = harness.PRICES["gpt-4o-mini"]
    assert cost_usd("gpt-4o-mini", 1_000_000, 2_000_000) == pytest.approx(price_in + 2 * price_out)


def test_call_log_charges_real_calls_only_and_writes_one_line_per_call(tmp_path: Path):
    log = CallLog(tmp_path / "calls.jsonl", prior_usd=1.5)
    log.record(kind="chat", model="gpt-4o-mini", input_tokens=1000, output_tokens=100, cached=False, latency_s=0.2)
    log.record(kind="chat", model="gpt-4o-mini", input_tokens=1000, output_tokens=100, cached=True, latency_s=None)
    totals = log.totals()
    expected = cost_usd("gpt-4o-mini", 1000, 100)
    assert totals["calls"] == 2 and totals["cache_hits"] == 1
    assert totals["run_spent_usd"] == pytest.approx(round(expected, 4))
    assert totals["cumulative_spent_usd"] == pytest.approx(round(1.5 + expected, 4))
    lines = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [line["cached"] for line in lines] == [False, True]
    assert lines[1]["cost_usd"] == 0.0


def test_prior_spend_sums_every_earlier_run(tmp_path: Path):
    for name, costs in {"run-a": [0.25, 0.5], "run-b": [1.0]}.items():
        (tmp_path / name).mkdir()
        lines = [json.dumps({"cost_usd": c}) for c in costs]
        (tmp_path / name / "calls.jsonl").write_text("\n".join(lines) + "\n")
    assert prior_spend_usd(tmp_path) == pytest.approx(1.75)
    assert prior_spend_usd(tmp_path / "missing") == 0.0


def test_budget_guard_refuses_a_call_that_could_pass_the_cap_and_sets_the_flag():
    log = CallLog(None, prior_usd=10.0 - CALL_RESERVE_USD / 2)
    tracker = CostTracker(log, budget_usd=10.0)
    assert not tracker.exceeded
    with pytest.raises(BudgetExceeded):
        tracker.check_budget()
    assert tracker.exceeded


def test_budget_guard_allows_calls_below_the_cap():
    tracker = CostTracker(CallLog(None, prior_usd=1.0), budget_usd=10.0)
    tracker.check_budget()
    assert not tracker.exceeded


def _generation(model: str = "gpt-4o-mini-2024-07-18") -> ChatGeneration:
    return ChatGeneration(message=AIMessage(content="hi", response_metadata={"model_name": model}))


def test_tracker_charges_reported_token_usage_and_logs_cache_hits_free():
    log = CallLog(None)
    tracker = CostTracker(log)
    real = LLMResult(generations=[[_generation()]],
                     llm_output={"token_usage": {"prompt_tokens": 500, "completion_tokens": 50},
                                 "model_name": "gpt-4o-mini-2024-07-18"})
    tracker.on_llm_end(real, run_id="r1")
    tracker.on_llm_end(LLMResult(generations=[[_generation()]], llm_output=None), run_id="r2")
    assert log.calls == 2 and log.cache_hits == 1
    assert log.spent_usd == pytest.approx(cost_usd("gpt-4o-mini", 500, 50))


class _OpenAIStub:
    """Minimal chat-completions endpoint; counts HTTP requests."""

    def __init__(self) -> None:
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return httpx.Response(200, json={
            "id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini-2024-07-18",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hello"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135},
        })


def _model(stub: _OpenAIStub, cache: SQLiteLLMCache, tracker: CostTracker) -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini", api_key="sk-test", cache=cache, callbacks=[tracker], max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(stub)))


def test_repeated_call_is_served_from_the_sqlite_cache_and_charged_once(tmp_path: Path):
    stub, log = _OpenAIStub(), CallLog(tmp_path / "calls.jsonl")
    tracker = CostTracker(log)
    model = _model(stub, SQLiteLLMCache(tmp_path / "llm.db"), tracker)
    assert model.invoke("hello").content == "hello"
    assert model.invoke("hello").content == "hello"
    assert stub.requests == 1
    assert log.calls == 2 and log.cache_hits == 1
    assert log.spent_usd == pytest.approx(cost_usd("gpt-4o-mini", 120, 15))


def test_structured_output_round_trips_through_the_cache(tmp_path: Path):
    from smartdesk.graph.state import IntentClassification

    stub = _OpenAIStub()
    stub_content = json.dumps({"intent": "greeting", "domain": "unknown", "search_query": ""})
    original = stub.__call__

    def respond(request: httpx.Request) -> httpx.Response:
        response = original(request)
        body = response.json()
        body["choices"][0]["message"]["content"] = stub_content
        return httpx.Response(200, json=body)

    model = ChatOpenAI(model="gpt-4o-mini", api_key="sk-test", cache=SQLiteLLMCache(tmp_path / "llm.db"),
                       max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    classifier = model.with_structured_output(IntentClassification)
    first, second = classifier.invoke("hello"), classifier.invoke("hello")
    assert first == second == IntentClassification(intent="greeting")
    assert stub.requests == 1


def test_cache_persists_across_processes(tmp_path: Path):
    stub = _OpenAIStub()
    _model(stub, SQLiteLLMCache(tmp_path / "llm.db"), CostTracker(CallLog(None))).invoke("hello")
    _model(stub, SQLiteLLMCache(tmp_path / "llm.db"), CostTracker(CallLog(None))).invoke("hello")
    assert stub.requests == 1


def test_a_refused_call_never_reaches_the_api(tmp_path: Path):
    stub = _OpenAIStub()
    tracker = CostTracker(CallLog(None, prior_usd=10.0), budget_usd=10.0)
    with pytest.raises(BudgetExceeded):
        _model(stub, SQLiteLLMCache(tmp_path / "llm.db"), tracker).invoke("hello")
    assert stub.requests == 0 and tracker.exceeded


def test_embedding_cache_calls_the_api_once_per_text_and_checks_the_budget_on_misses(tmp_path: Path):
    calls, checks = [], []
    log = CallLog(None)
    embed = CachedEmbedder(lambda text: calls.append(text) or [0.1, 0.2], "text-embedding-3-small", log,
                           path=tmp_path / "emb.db", before_call=lambda: checks.append(1))
    assert embed("vpn setup") == [0.1, 0.2]
    assert embed("vpn setup") == [0.1, 0.2]
    assert calls == ["vpn setup"] and len(checks) == 1
    assert log.cache_hits == 1 and log.input_tokens > 0


def test_percentile_uses_linear_interpolation_and_handles_no_values():
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95) == 4.8
    assert percentile([], 50) is None


def test_timer_excludes_turns_that_hit_the_cache():
    log, timer = CallLog(None), Timer()
    with timer.turn(log):
        log.record(kind="chat", model="gpt-4o-mini", input_tokens=1, output_tokens=1, cached=False, latency_s=0.1)
    with timer.turn(log):
        log.record(kind="chat", model="gpt-4o-mini", input_tokens=1, output_tokens=1, cached=True, latency_s=None)
    summary = timer.summary()
    assert summary["turns_timed"] == 1 and summary["turns_with_cache_hits_excluded"] == 1


def test_run_marker_is_written_whole(tmp_path: Path):
    marker = tmp_path / "RUN.json"
    write_run_marker(marker, {"sha": "abc", "items": [1, 2]})
    assert json.loads(marker.read_text()) == {"sha": "abc", "items": [1, 2]}


def test_a_failed_marker_write_leaves_no_file_behind(tmp_path: Path):
    marker = tmp_path / "RUN.json"
    with pytest.raises(TypeError):
        write_run_marker(marker, {"not_json": object()})
    assert list(tmp_path.iterdir()) == []
