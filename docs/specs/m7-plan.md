# Milestone 7 plan — Testing and evaluation

Draft for approval (2026-11-14). Once approved, this file is the source of
truth for M7 scope; changes need discussion first. It builds on the first M7
plan (multi-turn cases, unclear handling, larger eval sets, coverage by
capstone area, live runs, evaluation report) and adds the constraints below.

## Constraint checklist

| Constraint | Where it is implemented |
|---|---|
| Offline tests before live runs | §1: every runner and metric is built and tested offline with fakes; live runs (§7) start only when the offline suite is green |
| $10 cap | §2: a budget guard stops a run before cumulative spend would pass $10 |
| Cached responses | §2: LLM and embedding caches, so a repeated dev run costs nothing |
| Token logging | §2: per-call input/output tokens and cost written to the run log |
| Held-out run once | §2: the held-out split runs exactly once; a recorded run marker blocks a second run |
| Mock ticketing for evals | §3: eval runs use `FakeTicketService`; Jira is never called |
| Deterministic assertions on graph state | §3: pass/fail is decided from `ChatSession` state fields and fake-service calls, never by an LLM judge |
| Report: SHA, models, date, set sizes, commands, latency p50/p95 | §8; latency is timed directly with `time.perf_counter`, not taken from Langfuse |
| One-day timebox; cut K4 first | §9 |
| All four multi-turn case types | §4 |
| ~8 unclear cases written explicitly | §5: U1–U8 without history; "same issue as before" also as U9 with history; a ticket start passes only if SmartDesk asks before drafting |
| Held-out cleanliness disclosed | §2a: held-out results reported as fresh (11), seen (21) and all 32 |
| `RUN.json` only after a completed held-out run | §2: atomic write at the end; a crashed or budget-stopped run does not block a rerun |
| Coverage output as a table from each rubric line to its tests | §6 |

## Current state (from the repo)

- `python -m smartdesk.rag.calibrate` measures Recall@5, Hit@1, MRR, escalation precision/recall, routing accuracy per category and citation accuracy.
- Dev set: 63 items (41 answerable, 11 gap, 6 out-of-scope, 5 greeting).
- Held-out set: 32 items (12 answerable, 14 gap, 4 out-of-scope, 2 greeting), **frozen by hash** (`data/eval/heldout/FROZEN.sha256`, tag `m7-heldout-frozen`, `tests/test_eval_frozen.py`). It is never edited or tuned against.
- No `docs/evaluation-report.md` yet. Open known issues for M7: K1, K3, K4.

## 1. Offline first

New code lives in `src/smartdesk/eval/`:

- `harness.py`: budget, caches, token logging and timing (§2)
- `multiturn.py`: the multi-turn runner (§4)
- `unclear.py`: the unclear-message runner (§5)
- `coverage.py`: the rubric coverage table (§6)
- `report.py`: run metadata (§8)

`rag/calibrate.py` keeps its metrics; its live calls go through the same harness.

Offline tests (`tests/test_eval_*.py`) drive every runner with `FakeLLM`, `FakeRetriever` and `FakeTicketService`:

- case-file schema checks;
- pass/fail logic on scripted conversations, including deliberately failing ones;
- metric arithmetic (rates, p50/p95);
- the budget guard stopping at the cap;
- the held-out marker written only on completion: a simulated crash or budget stop leaves no `RUN.json`, a completed run writes it, and a later run is refused;
- the coverage table listing an uncovered rubric line.

Live runs (§7) start only after `pytest` is green.

## 2. Cost controls, caching, token logging

- **Budget guard:** a LangChain callback reads each response's token usage and adds its cost from a price table in `harness.py`.
  - The table holds `gpt-4o-mini` input and output and `text-embedding-3-small`. The prices are recorded in the report and checked against OpenAI's pricing page before the live run.
  - A run stops before any call that would take the total over **$10**; the partial results are kept and marked incomplete.
  - Estimate: about 250 graph turns at about 3 LLM calls each, roughly 1–2 M input tokens, well under $1 for `gpt-4o-mini`.
- **Caching:**
  - LLM responses go through LangChain's `SQLiteCache`; query embeddings go through `CacheBackedEmbeddings`. Both live under `data/eval/.cache/`, which is git-ignored.
  - A repeated dev run costs nothing. Cache hits are counted and excluded from latency (§8).
- **Token logging:** one JSON line per LLM call in `data/eval/runs/<run-id>/calls.jsonl`, also git-ignored: model, input tokens, output tokens, cost, cache hit, latency. Totals go into the report.
- **Held-out run once:** `data/eval/heldout/RUN.json`, which is committed and records the SHA, date, models and per-item results, is written **only after a held-out run completes**: every item scored, no crash, no budget stop.
  - It is written atomically: to a temporary file, then renamed. A crashed or budget-stopped run therefore leaves no marker, so it does not block a rerun.
  - Every attempt, complete or not, is logged under `data/eval/runs/`. The report lists any incomplete attempts and how far each got, because their partial results were visible.
  - Once `RUN.json` exists, the runner refuses the held-out split. The results are reported as they come out, with no re-run and no tuning.

## 2a. Held-out history: what is clean

| Items | Added | Seen before M7? |
|---|---|---|
| `ho-01`–`ho-21` (21) | 2026-11-01, M3 (`5b00875`) | **Yes.** Scored by M3's `calibrate` (in `calibration_report.json` and the README). One held-out failure (relocation routing) led to a router change; that item moved to dev as `gap-11`, and its replacement `ho-13` was written after the failure was seen. Later prompt changes (M5/M6, M8) were made while these results were known. |
| `ho-22`–`ho-32` (11) | 2026-11-14, M7 (`3efe313`), after the last prompt/RAG change (2026-11-02) | **No.** Never scored before the freeze. Caveat: an assistant session that knew the system and KB wrote them, so they are not independent items. |

The report gives held-out results in three rows: **fresh** (`ho-22`–`ho-32`),
**seen** (`ho-01`–`ho-21`) and **all 32**. It states that only the fresh
subset is a clean held-out estimate, and that with 11 items it is indicative only.

## 3. Mock ticketing and deterministic assertions

- **Mock ticketing:** every eval conversation runs through `ChatSession` with the real LLM and retriever but `FakeTicketService`. Approvals go to the fake, so no Jira ticket is ever created by an eval.
- **Deterministic assertions:** each case states expected values for state fields, and the runner compares them exactly, or as keyword containment for LLM-written text. The fields:
  - `intent`
  - `escalation_reason`
  - citation `doc_id`s
  - `search_query`
  - `awaiting`
  - `ticket_draft` (summary, description and category, matched by keyword)
  - `pending_flow_start` / `ticket_flow_start`
  - the fake service's `create_calls`

  The keyword lists are written in the case files before the live run. No LLM judges any output.

## 4. Multi-turn cases (K1): `data/eval/multiturn.jsonl`

Each case is a list of turns with the expected state after the turns that matter. All four types are kept, about 6 cases each, mixing IT and HR:

| Type | Example conversation | Deterministic pass condition |
|---|---|---|
| **A. Unrelated question, then a ticket request** | "How many sick leave days do I get?" (answered) → "Please raise a ticket: I need a new laptop" | Draft contains the request keywords (`laptop`) and none of the question's (`sick`, `leave`); both answered and escalated variants |
| **B. "A ticket for it" after a KB turn** | "Why does the VPN say authentication failed?" (escalated) → "yes please"; or a VPN answer → "raise a ticket for that problem" | Draft carries the question's topic keywords (`vpn`, `authentication`) |
| **C. Held draft, then a new request** | Monitor ticket at review → KB question → "I need a new laptop" → `awaiting == "held_draft"` → "new"; plus the re-ask variant ("yes please" before "new", K18) | After "new": draft has `laptop`, none of `monitor` / `flicker` / the question's keywords; the held draft is never created (`create_calls == []`) |
| **D. Follow-up that depends on an earlier turn** | "How do I set up the VPN on Windows?" → "And on a Mac?"; "What's the WFH policy?" → "How many days is that per week?" | `search_query` contains the topic keyword (`vpn`, `work from home`/`wfh`); citations include the expected `doc_id` |

Reported metrics:

- **No-merge rate** (type A, plus type C after "new");
- **Carry-over rate** (type B);
- **Follow-up resolution rate** (type D);
- every failing case, listed with its final state.

## 5. Unclear handling (K3): `data/eval/unclear.jsonl`

Nine cases.

**Without history** (U1–U8): each is the first message of a fresh session.

1. "it's broken"
2. "help"
3. "the thing isn't working"
4. "can you fix it?"
5. "I have a problem"
6. "it doesn't work again"
7. "urgent, please sort this out"
8. "same issue as before"

**Pass condition for U1–U8:** SmartDesk asks what is wrong and has not retrieved, answered or drafted anything. That is `retrieved == []`, `citations == []`, and one of:

- `intent == "unclear"` and the reply is the clarify prompt; or
- `intent == "create_ticket"`, `awaiting == "ticket_details"`, the reply is the ask-for-details prompt, **and the draft holds no fields** (`ticket_draft == {}`: no summary, description, category or priority). A ticket start that has already drafted any field fails.

The two passing routes are counted separately in the report.

**With history** (U9, "same issue as before" with context): first "My VPN keeps disconnecting every few minutes when I work from home", run normally; then "same issue as before" in the same session.

**Pass condition for U9:** it resolves from context instead of asking. Either:

- `intent == "knowledge_question"` with `search_query` containing `vpn`; or
- `intent == "create_ticket"` with the draft description containing `vpn`.

Failing results: the clarify prompt, or no `vpn` in the query or draft. U9 is reported on its own line as "resolved from context", not in the U1–U8 rate.

Out-of-scope handling comes from the existing out-of-scope items (dev 6, held-out 4) and is reported alongside.

## 6. Coverage: rubric line → tests

- Tests get a marker, `@pytest.mark.rubric("B3")`, registered in `pyproject.toml`. Most of the tests already exist; this work maps them.
- `python -m smartdesk.eval.coverage` collects the markers with `pytest --collect-only` and writes a Markdown table into the report:

  | Rubric line | Requirement | Tests | Offline / live |
  |---|---|---|---|
  | A1 … F4, FR-x, NFR-x | short name | test ids | marker type |

- Rows cover every graded rubric line (A1–F4), plus the CLAUDE.md M7 areas: KB relevance and coverage, retrieval quality, grounded answers, escalation, intent routing, multi-turn behaviour, Jira ticket creation, ticket status retrieval, HITL approval and error handling.
- A line with no test is printed as **UNCOVERED** and gets a small test. Expected candidates are few, since most areas already have tests.

## 7. Live runs (after §1 is green)

The commands are run once each and recorded verbatim in the report:

```
python -m smartdesk.rag.calibrate --split dev
python -m smartdesk.eval.multiturn
python -m smartdesk.eval.unclear
python -m smartdesk.rag.calibrate --split heldout   # once; writes data/eval/heldout/RUN.json
```

If a number comes out poor, it is reported as it is, with the failing cases. Nothing is tuned against the held-out results.

## 8. `docs/evaluation-report.md`

- **Run metadata:** git commit SHA (clean tree required), date, chat / embedding / fallback model names, the price table used, set sizes per category (dev, held-out, multi-turn per type, unclear), and the exact commands.
- **Retrieval:** Hit@1, Recall@5 and MRR for dev and held-out; held-out in three rows, fresh, seen and all (§2a).
- **Escalation:** precision and recall, with gap as the positive class, on gap vs answerable questions, per split, with the same three held-out rows.
- **Grounding:** grounded-answer and citation-accuracy rates.
- **Routing:** accuracy per category; out-of-scope and unclear handling (§5).
- **Multi-turn:** the rates from §4.
- **Latency:** p50 and p95 per turn, timed with `time.perf_counter` around each `ChatSession.send`. Uncached calls only, so cache hits are excluded, and the count of each is reported.
- **Tokens and cost:** totals from the call log (§2).
- **Coverage table** (§6).
- **Failures and limitations:** every failing case, the small set sizes, and what the numbers do not show.

The rubric traceability file and `docs/known-issues.md` (K1, K3, K4) are updated to point to the report.

## 9. Timebox: one day

- Work order: §1–§3 harness and offline tests → §5 unclear → §4 multi-turn → §6 coverage → §7 live runs → §8 report.
- **K4 (about 15 more dev questions) is cut first** if the day runs short; the held-out set cannot grow anyway, since it is frozen. If more must go after that, I'll ask before cutting anything else.
- If a stage overruns, I stop and report where it stands instead of extending the day.

## Out of scope

- Ragas or DeepEval (optional bonus).
- An LLM-as-judge.
- Langfuse-dependent metrics: Langfuse traces stay on if configured, but no number in the report depends on them.
- Hybrid search.
- Any tuning against held-out results.

Stop after M7 with the working-agreement report; M9 follows only after approval.
