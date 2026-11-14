# SmartDesk AI: evaluation report (Milestone 7)

All numbers below come from the run logs in `data/eval/runs/` (git-ignored) and the committed
`data/eval/calibration_report.json` and `data/eval/heldout/RUN.json`. Nothing is estimated or
re-typed by hand beyond copying these values. Method: `docs/specs/m7-plan.md`.

## Headline results

Two fixes (K23, K25) were made after the first evaluation; see "After the fixes". The held-out set
was **not** re-run after them, so every held-out number here is **measured before fixes**.

| Area | Set | Result |
|---|---|---|
| End-to-end outcome (answer / escalate / decline / greet) | dev, 63 | 63/63 (before and after fixes) |
| | held-out, 32, measured before fixes | 31/32 (miss: `ho-29`) |
| Retrieval Recall@5 on answerable (agent's domain-aware retrieval) | dev, 41 | 1.000 (Hit@1 0.976, MRR 0.988) |
| | held-out, 12, measured before fixes | 0.917 (Hit@1 0.833, MRR 0.875); unfiltered 1.000 |
| RAG escalation precision / recall (positive = gap) | dev | 1.000 / 1.000 (11/11 gap escalated, 0/41 answerable) |
| | held-out, measured before fixes | 1.000 / 1.000 (14/14 gap escalated, 0/12 answerable) |
| Answers citing an expected document | dev | 41/41 |
| | held-out, measured before fixes | 11/12 (miss: `ho-26`) |
| Multi-turn cases | before fixes: A–D, 24 cases | 22/24 |
| | after fixes: A–D plus 4 back-reference cases (E) | 27/28 (miss: D5, K24) |
| Unclear first messages asking for clarification | U1–U8, before fixes | 8/8 |
| "Same issue as before" resolved from history | U9, before fixes | 0/1; after the K25 fix the same conversation (E1) passes |
| Out-of-scope declined | dev 6, held-out 4 (before fixes) | 6/6, 4/4 |
| Agent turn latency (uncached), p50 / p95 | multi-turn before fixes, n=35 | 1.888 s / 3.031 s |
| Total OpenAI spend, all seven runs | — | $0.0583 of the $10 cap |

## Run metadata

| | |
|---|---|
| Date (UTC) | 2026-11-14, 18:00–18:08 |
| Code | dev run at `4e3ac38`; multi-turn, unclear and held-out at `866f66d` (see caveats) |
| Chat model | `gpt-4o-mini`, temperature 0 (`SMARTDESK_LLM_TEMPERATURE`) |
| Fallback model | none configured in the run environment |
| Embedding model | `text-embedding-3-small` |
| Retrieval | ChromaDB dense retrieval, top-k 5, `min_similarity` 0.35, router history 4 turns |
| Prices (USD per 1M tokens) | `gpt-4o-mini` 0.15 in / 0.60 out; `gpt-4o` 2.50 / 10.00; `text-embedding-3-small` 0.02. Checked 2026-11-14 at https://developers.openai.com/api/docs/pricing. Cached-input discounts are ignored, so spend is overestimated. |
| Ticketing | `MockTicketService` (in memory); no Jira call was made by any evaluation |
| Judging | deterministic checks on graph state; no LLM judge |
| Set sizes | dev 63 (41 answerable, 11 gap, 6 out-of-scope, 5 greeting); held-out 32 (12 / 14 / 4 / 2); multi-turn 24 cases; unclear 9 cases |

Commands, run once each in this order, on a tree whose only change was the report file the runs write:

```
python -m smartdesk.rag.calibrate --split dev
python -m smartdesk.eval.multiturn
python -m smartdesk.eval.unclear
python -m smartdesk.rag.calibrate --split heldout
```

(The multi-turn and unclear `results.json` record the command as the module's file path; that is
how `sys.argv` appears under `python -m`.)

| Run | Calls (cached) | Input / output tokens | Spend | Cumulative | Budget stop |
|---|---|---|---|---|---|
| calibrate dev | 247 (63) | 111,415 / 8,529 | $0.0217 | $0.0217 | no |
| multiturn | 136 (67) | 51,578 / 2,339 | $0.0091 | $0.0309 | no |
| unclear | 12 (0) | 8,936 / 282 | $0.0015 | $0.0324 | no |
| calibrate held-out | 126 (32) | 56,425 / 2,366 | $0.0098 | $0.0422 | no |
| *after the fixes (`f35b55c`):* | | | | | |
| K25 dev cases before the prompt fix (E1–E4 only) | 18 (12) | — | $0.0008 | $0.0430 | no |
| calibrate dev | 247 (184) | — | $0.0087 | $0.0517 | no |
| multiturn (28 cases) | 156 (111) | — | $0.0066 | $0.0583 | no |

Incomplete attempts: none. No run was stopped by the budget or crashed. The held-out set was
scored once; a second `--split heldout` is refused because `RUN.json` exists (verified).

## Dev set (calibration split)

| Category | Expected | Correct | Routing |
|---|---|---|---|
| answerable | answer | 41/41 | 41/41 |
| gap | escalate | 11/11 | 11/11 |
| out_of_scope | decline | 6/6 | 6/6 |
| greeting | greet | 5/5 | 5/5 |

Threshold sweep: precision/recall stay 1.000/1.000 for every threshold from 0.20 to 0.40; from 0.42
up, answerable questions start escalating (1/41 at 0.42, 5/41 at 0.50). The recommended
`min_similarity` (lowest answerable score minus a 0.05 margin) is 0.35, unchanged from M3. The
threshold is a pre-filter only; the LLM sufficiency check makes the final call, and the scores are
treated as rankings, not probabilities.

## Held-out set (scored once, measured before fixes)

These numbers were measured at `866f66d`, before the K23 and K25 fixes, and the set was not re-run
afterwards (`RUN.json`, committed in `5a6c5fe`). The K25 change edits the router prompt, so routing
on held-out questions after the fixes is unmeasured.

The held-out set is not fully clean, and the numbers are split accordingly (`docs/data-sources.md`,
m7-plan §2a): `ho-01`–`ho-21` were seen during M3–M6 and one failure among them influenced a router
change; `ho-22`–`ho-32` were written after that and never run before this evaluation.

| Subset | Items | End-to-end | Recall@5 (domain-aware / unfiltered) | Hit@1 (domain-aware) | Escalation P / R | Cites expected doc |
|---|---|---|---|---|---|---|
| **fresh** `ho-22`–`ho-32` | 11 | 10/11 | 0.800 / 1.000 | 0.800 | 1.000 / 1.000 | 4/5 |
| seen `ho-01`–`ho-21` | 21 | 21/21 | 1.000 / 1.000 | 0.857 | 1.000 / 1.000 | 7/7 |
| all | 32 | 31/32 | 0.917 / 1.000 | 0.833 | 1.000 / 1.000 | 11/12 |

The fresh row is the only unbiased estimate, and it is small (5 answerable, 4 gap questions).
Misses:

- `ho-29` "What is on the cafeteria menu this week?" (gap): routed `out_of_scope` and declined
  instead of escalating with a ticket offer. No information was invented.
- `ho-26` "I'm leaving the company. Do I have to give back my laptop and when?" (expected
  `hr-resignation-exit`): routed to the IT domain, so the domain filter returned IT documents only;
  the answer cited `onb-it-equipment`. Unfiltered retrieval ranked the expected document first.
- `ho-03` (seen): expected document ranked second behind `onb-day-one`; the answer still cited it.

## Multi-turn behaviour (`data/eval/multiturn.jsonl`)

Pass conditions were written into the case file before the run (keyword lists on the draft,
`search_query`, citations, `awaiting`, approval and ticket counts).

| Type | Passed | Metric |
|---|---|---|
| A. unrelated question, then a ticket request | 6/6 | no-merge: draft has the request's keywords and none of the question's |
| B. "a ticket for it" after a KB turn | 6/6 | carry-over: draft has the question's topic |
| C. held draft, then a new request (incl. K18 re-ask, continue, approve) | 5/6 | no ticket created before approval in any case; one held draft created only after "continue" + approve (C5) |
| D. follow-up depending on an earlier turn | 5/6 | follow-up resolution: `search_query` carried the topic in 6/6; expected citation in 5/6 |

- **No-merge rate** (A, plus C after "new"): 10/11. **Carry-over rate** (B): 6/6. **Follow-up
  resolution** (D): 5/6.
- **C6 fails**: at "Continue that one, or start a new ticket?" the reply "hmm, not sure" was routed
  `unclear`; the generic clarify reply cleared the open question, so the following "new ticket" was
  treated as a fresh request and the held-draft question was asked again. Final state: draft still
  the held payslip ticket, no ticket created. No topics were merged; the flow stalled.
- **D5 fails**: "Does the health insurance cover my parents?" → "How do I add them?". The rewritten
  query carried the topic, but the answer step judged the evidence insufficient and escalated,
  although `hr-health-insurance` has an "Adding a New Dependant" section. A false escalation
  (over-abstention), not a hallucination.

## After the fixes (dev and multi-turn only)

Two findings touched graded behaviour (multi-turn context, rubric D2) and were fixed at `f35b55c`,
each with a dev case written and seen failing first:

- **K23**: when SmartDesk is waiting for an answer to its own question, an `unclear` reply now keeps
  that question open and the flow asks it again (code change in `classify_intent`). Dev cases: two
  offline ticket-flow tests reproducing C6 (both failed before the change), plus multi-turn C6.
- **K25**: the router prompt now says a reference back to an issue described earlier in the
  conversation is about that issue, and is not a status request unless the employee asks about a
  ticket. Dev cases: new multi-turn type E (E1 "same issue as before", E2 "it's happening again",
  E3 "I'm still having the same problem", E4 a real status request as a control). Before the change
  E1 failed (routed `ticket_status`) and E2–E4 passed; after it all four pass.

Reruns after the fixes, as agreed: dev calibration and multi-turn only (unclear and held-out were
not re-run).

| Run | Result |
|---|---|
| dev calibration | unchanged: 63/63 end to end, routing 63/63, Recall@5 1.000, escalation P/R 1.000/1.000, citations 41/41 |
| multi-turn | A 6/6, B 6/6, **C 6/6** (C6 now passes), D 5/6 (D5 is K24, not fixed), **E 4/4** |

Latency from the post-fix multi-turn run is not used: most turns were served from cache (n=13 timed).

## Unclear and ambiguous messages (`data/eval/unclear.jsonl`, measured before fixes)

| Case | Result |
|---|---|
| U1–U8, first message of a fresh session ("it's broken", "help", "the thing isn't working", "can you fix it?", "I have a problem", "it doesn't work again", "urgent, please sort this out", "same issue as before") | 8/8 asked for clarification; all 8 via the clarify reply (0 via a ticket start); nothing retrieved, answered or drafted |
| U9, "same issue as before" after a VPN question | **fail**: routed `ticket_status` and asked for an email to look up tickets, instead of resolving the VPN issue from context |

Out-of-scope requests from the eval sets were declined 6/6 (dev) and 4/4 (held-out).

## Latency

Wall-clock time per turn with `time.perf_counter`, independent of Langfuse. Turns that used a
response cached by an earlier run are excluded.

| Run | What one unit is | n timed (excluded) | p50 | p95 |
|---|---|---|---|---|
| multiturn | one graph turn through `ChatSession` | 35 (28) | 1.888 s | 3.031 s |
| unclear | one graph turn | 10 (0) | 0.773 s | 2.202 s |
| calibrate held-out | router + two retrievals + answer step for one question | 32 (0) | 2.071 s | 3.223 s |
| calibrate dev | — | not measured (see caveats) | — | — |

## Rubric coverage

Generated by `python -m smartdesk.eval.coverage` from `@pytest.mark.rubric` markers. Offline
suite at `866f66d`: 471 passed, 23 skipped (live tests, which need `SMARTDESK_LIVE_TESTS=1`).

| Rubric line | Requirement | Tests | Offline / live | Live eval |
|---|---|---|---|---|
| A1 | Quality and breadth of KB content | `test_kb_catalog.py` (14), `test_kb_data.py` (9), `test_kb_documents.py` (8), `test_kb_generate.py` (10), `test_kb_sources.py` (5) | 46 offline / 0 live |  |
| A2 | Chunking strategy and justification | `test_docs.py` (1), `test_kb_chunking.py` (5), `test_kb_ingest.py` (6) | 12 offline / 0 live |  |
| A3 | Retrieval quality | `test_eval_conversations.py` (5), `test_eval_frozen.py` (1), `test_rag_retriever.py` (7) | 13 offline / 0 live | calibrate |
| A4 | LLM grounding, no hallucination | `test_guardrails.py` (1), `test_live_openai.py` (1), `test_rag_answer.py` (9), `test_workflow.py` (1) | 11 offline / 1 live | calibrate |
| A5 | Confidence / escalation logic | `test_eval_conversations.py` (5), `test_live_openai.py` (1), `test_rag_calibrate.py` (5), `test_ticket_flow.py` (1), `test_workflow.py` (4) | 15 offline / 1 live | calibrate |
| B1 | Successful external API integration | `test_live_jira.py` (4), `test_tickets_adf.py` (4), `test_tickets_jira_client.py` (17), `test_tickets_models.py` (19), `test_tickets_service.py` (33), `test_tickets_store.py` (10) | 83 offline / 4 live |  |
| B2 | All mandatory fields collected | `test_live_openai.py` (1), `test_ticket_flow.py` (4) | 4 offline / 1 live |  |
| B3 | Human-in-the-loop confirmation | `test_ticket_flow.py` (4) | 4 offline / 0 live |  |
| B4 | Post-creation feedback with ticket ID/link | `test_ticket_flow.py` (2), `test_tickets_service.py` (1) | 3 offline / 0 live |  |
| C1 | Status retrieval via API | `test_live_jira.py` (4), `test_status_flow.py` (27), `test_tickets_service.py` (1) | 28 offline / 4 live |  |
| C2 | Multiple-ticket handling | `test_status_flow.py` (6) | 6 offline / 0 live |  |
| C3 | Graceful handling when no tickets found | `test_status_flow.py` (4), `test_tickets_service.py` (1) | 5 offline / 0 live |  |
| D1 | Correct intent detection and routing | `test_live_openai.py` (7), `test_workflow.py` (19) | 19 offline / 7 live | calibrate |
| D2 | Smooth multi-turn conversations | `test_eval_conversations.py` (3), `test_live_openai.py` (1), `test_session.py` (36), `test_sessions.py` (11), `test_ticket_flow.py` (2), `test_workflow.py` (1) | 53 offline / 1 live | multiturn |
| D3 | Out-of-scope / ambiguous query handling | `test_eval_conversations.py` (9), `test_workflow.py` (5) | 14 offline / 0 live | unclear, calibrate |
| E1 | Clean, modular, readable code | manual review (ruff lint is the automated proxy) | - |  |
| E2 | README with setup instructions | `test_docs.py` (5) | 5 offline / 0 live |  |
| E3 | Architecture diagram | **UNCOVERED** (M9 deliverable) | - |  |
| F1 | Graceful API failure degradation | `test_m6_reliability.py` (16), `test_status_flow.py` (2), `test_ticket_flow.py` (3) | 21 offline / 0 live |  |
| F2 | Retry logic / LLM fallback | `test_llm.py` (4), `test_m6_reliability.py` (16) | 20 offline / 0 live |  |
| F3 | No hard-coded secrets | `test_config.py` (8), `test_observability.py` (3), `test_redaction.py` (14) | 25 offline / 0 live |  |
| F4 | Edge-case handling | `test_guardrails.py` (37), `test_tickets_concurrency.py` (6) | 43 offline / 0 live |  |
| M7-KB | KB relevance and coverage | `test_kb_catalog.py` (14), `test_kb_data.py` (9), `test_kb_documents.py` (8), `test_kb_generate.py` (10), `test_kb_sources.py` (5) | 46 offline / 0 live |  |
| M7-RET | Retrieval quality | `test_eval_frozen.py` (1), `test_rag_retriever.py` (7) | 8 offline / 0 live | calibrate |
| M7-GROUND | Grounded answers | `test_guardrails.py` (1), `test_live_openai.py` (1), `test_rag_answer.py` (9), `test_workflow.py` (1) | 11 offline / 1 live | calibrate |
| M7-ESC | Escalation | `test_live_openai.py` (1), `test_rag_calibrate.py` (5), `test_ticket_flow.py` (1), `test_workflow.py` (4) | 10 offline / 1 live | calibrate |
| M7-INTENT | Intent routing | `test_eval_conversations.py` (8), `test_live_openai.py` (7), `test_workflow.py` (19) | 27 offline / 7 live | calibrate, unclear |
| M7-MULTI | Multi-turn behaviour | `test_eval_conversations.py` (3), `test_live_openai.py` (1), `test_session.py` (36), `test_sessions.py` (11), `test_ticket_flow.py` (2), `test_workflow.py` (1) | 53 offline / 1 live | multiturn |
| M7-JIRA | Jira ticket creation | `test_live_jira.py` (4), `test_ticket_flow.py` (44), `test_tickets_adf.py` (4), `test_tickets_concurrency.py` (6), `test_tickets_jira_client.py` (17), `test_tickets_models.py` (19), `test_tickets_service.py` (33), `test_tickets_store.py` (10) | 133 offline / 4 live |  |
| M7-STATUS | Ticket status retrieval | `test_live_jira.py` (4), `test_status_flow.py` (27), `test_tickets_service.py` (2) | 29 offline / 4 live |  |
| M7-HITL | HITL approval | `test_live_openai.py` (1), `test_ticket_flow.py` (5) | 5 offline / 1 live |  |
| M7-ERR | Error handling | `test_guardrails.py` (37), `test_m6_reliability.py` (16), `test_status_flow.py` (2), `test_ticket_flow.py` (3) | 58 offline / 0 live |  |

Live tests were not re-run in M7; their counts show what exists. Untagged test files (UI, eval
infrastructure) are listed by the command and map to no rubric line.

## Caveats and deviations

- **Small samples.** The fresh held-out subset has 11 items; one miss moves a rate by 9 points. All
  rates are indicative, not statistically strong (K4).
- **Nondeterminism.** Temperature 0 reduces but does not remove run-to-run variation in the LLM.
  Each set was run once; repeat runs were not used to pick favourable results.
- **Cache, not LangChain's community classes.** The plan named `SQLiteCache` and
  `CacheBackedEmbeddings`; `langchain-community` and `langchain` are not dependencies, so
  `smartdesk.eval.harness` implements an equivalent SQLite LLM cache and embedding cache. Tests
  cover cache hits, persistence and structured-output round trips.
- **Two code versions.** The dev run used `4e3ac38`. A latency bug found in that run was fixed in
  `866f66d`, which changed only the evaluation timer and its test, not SmartDesk's behaviour; the
  other three runs used `866f66d`.
- **Dev latency not measured.** In the dev run the second embedding of each question (for unfiltered
  retrieval) hit the cache and wrongly excluded every item from timing. A repeat run would be served
  from cache, so dev latency is not reported; latency comes from the other three runs.
- **`RUN.json` shows `dirty: true`.** The run metadata counts every uncommitted file. At the time of
  the held-out run the only change was `data/eval/calibration_report.json`, written by the dev run
  (`git status` was printed immediately before the run); the code matched `866f66d`. The held-out
  gate itself ignores that file. `RUN.json` is left exactly as written.
- **Calibrate latency is pipeline latency.** One calibrate item runs two retrievals (domain-aware and
  unfiltered), so it is slower than one agent turn; agent-turn latency is the multi-turn row.
- **U9 pass condition.** The draft check matches summary and description, slightly broader than the
  plan's "description"; U9 failed on routing, so this did not matter.

## Findings

None of them created a ticket without approval or produced an invented answer. Only findings that
hit graded behaviour (made-up answers, ticket without confirmation, missing mandatory field, status
lookup, multi-turn context) were fixed; the rest stay in `docs/known-issues.md`.

| # | Finding | Evidence | Rubric | Status |
|---|---|---|---|---|
| K23 | An unclear reply to "continue or new?" drops the open held-draft question | multi-turn C6 (1/6 C cases) | D2 | **fixed** `f35b55c`; C6 passes |
| K24 | Over-abstention on a follow-up that the KB answers (adding a parent as a dependant) | multi-turn D5 (1/6 D cases) | A5 | open |
| K25 | "Same issue as before" after a knowledge question is routed to ticket status | unclear U9 (1/1) | D2, D1 | **fixed** `f35b55c`; E1 passes |
| K26 | The domain filter can exclude the right cross-domain document (IT routing for an HR exit question) | held-out `ho-26` (1/12 answerable) | A3 | open; found on held-out, deliberately not tuned against |
| K27 | A workplace question with no KB entry was declined as out of scope instead of escalated | held-out `ho-29` (1/14 gap) | D3, A5 | open; found on held-out, deliberately not tuned against |
