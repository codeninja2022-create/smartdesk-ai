"""Wiring shared by every live evaluation command (docs/specs/m7-plan.md §2, §7).

`start_run` gives one run directory with its call log, budget tracker, timer,
cached retriever and cached chat model. Sessions use an in-memory checkpointer
and a fresh `MockTicketService` per case: no Jira, no Langfuse, nothing written
to the app's checkpoint database.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from smartdesk.config import Settings, get_settings
from smartdesk.eval.harness import (
    DEFAULT_BUDGET_USD,
    CachedEmbedder,
    CallLog,
    CostTracker,
    SQLiteLLMCache,
    Timer,
    new_run_dir,
    prior_spend_usd,
    run_metadata,
)
from smartdesk.eval.mock_tickets import MockTicketService
from smartdesk.graph import ChatSession, build_graph
from smartdesk.llm import get_chat_model, get_resilient_chat_model
from smartdesk.rag.retriever import Retriever, build_retriever


@dataclass
class EvalRun:
    settings: Settings
    run_dir: Path
    log: CallLog
    tracker: CostTracker
    timer: Timer
    retriever: Retriever
    model_kwargs: dict[str, Any]
    metadata: dict

    def timed(self):
        return self.timer.turn(self.log)

    def chat_model(self):
        """The primary model alone, as calibrate.py uses it."""
        return get_chat_model(self.settings, **self.model_kwargs)

    def make_session(self, thread_id: str) -> tuple[ChatSession, Callable[[], int]]:
        tickets = MockTicketService()
        graph = build_graph(
            get_resilient_chat_model(self.settings, **self.model_kwargs),
            self.retriever,
            min_similarity=self.settings.rag_min_similarity,
            ticket_service=tickets,
            checkpointer=MemorySaver(),
            router_history_turns=self.settings.router_history_turns,
        )
        session = ChatSession(graph, thread_id, max_input_chars=self.settings.max_input_chars)
        return session, lambda: tickets.created_count

    def write_results(self, payload: dict) -> Path:
        path = self.run_dir / "results.json"
        full = {**self.metadata, **payload, "totals": self.log.totals(), "latency": self.timer.summary(),
                "budget_stopped": self.tracker.exceeded}
        path.write_text(json.dumps(full, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path


def run_case_file(name: str, case_path: Path, argv: list[str] | None = None) -> int:
    """Run one conversation case file live; 0 = complete, 2 = stopped by the budget."""
    from smartdesk.eval.conversations import load_cases, results_payload, run_cases

    cases = load_cases(case_path)
    run = start_run(name, argv=argv)
    results, complete = run_cases(cases, run.make_session, timed=run.timed, stop=lambda: run.tracker.exceeded)
    payload = results_payload(results, complete, {"case_file": str(case_path), "cases_total": len(cases)})
    path = run.write_results(payload)

    print(f"\n=== {name}: {len(results)}/{len(cases)} cases run{'' if complete else ' (INCOMPLETE: budget)'} ===")
    for kind, stats in payload["summary"]["by_type"].items():
        print(f"  {kind:28s} {stats['passed']}/{stats['total']}  failed: {stats['failed_ids'] or 'none'}")
    for result in results:
        for n, turn in enumerate(result.turns, 1):
            for failure in turn.failures:
                print(f"  {result.id} turn {n}: {failure}")
    if routes := payload["summary"]["clarification_routes"]:
        print(f"  clarification routes: {routes}")
    totals, latency = run.log.totals(), run.timer.summary()
    print(f"  spend: run ${totals['run_spent_usd']:.4f}, cumulative ${totals['cumulative_spent_usd']:.4f}; "
          f"calls {totals['calls']} ({totals['cache_hits']} cached)")
    print(f"  latency (uncached turns, n={latency['turns_timed']}): p50 {latency['p50_s']}s, p95 {latency['p95_s']}s")
    print(f"Results: {path}")
    return 0 if complete else 2


def start_run(name: str, budget_usd: float = DEFAULT_BUDGET_USD, argv: list[str] | None = None) -> EvalRun:
    settings = get_settings()
    base = build_retriever(settings)
    if base.collection.count() == 0:
        print("The index is empty; run `python -m smartdesk.kb.ingest` first.", file=sys.stderr)
        raise SystemExit(1)
    run_dir = new_run_dir(name)
    log = CallLog(run_dir / "calls.jsonl", prior_usd=prior_spend_usd())
    tracker = CostTracker(log, budget_usd)
    tracker.check_budget()  # refuse to start at all once the cap is reached
    embedder = CachedEmbedder(base.embed_query, settings.embedding_model, log, before_call=tracker.check_budget)
    retriever = Retriever(base.collection, embedder, top_k=base.top_k,
                          domain_fallback_similarity=base.domain_fallback_similarity)
    metadata = run_metadata(settings, ["python", "-m", *(argv or sys.argv)])
    metadata["budget_usd"] = budget_usd
    metadata["prior_spend_usd"] = round(log.prior_usd, 4)
    return EvalRun(settings, run_dir, log, tracker, Timer(), retriever,
                   {"cache": SQLiteLLMCache(), "callbacks": [tracker]}, metadata)
