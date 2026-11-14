# Known issues and future work

Open limitations and planned work, one line each. Sources: `docs/decisions.md`,
the README and the milestone reports. Remove a line only when its fix is
merged and tested.

Last updated: Milestone 9.

| # | Issue | Impact | Planned fix | When |
|---|---|---|---|---|
| K4 | The evaluation sets are small (held-out: 12 answerable, 14 gap; the clean fresh subset has 11 items). | Rates are indicative, not statistically strong; one miss moves the fresh rate by 9 points. | About 15 more dev questions (cut first under the M7 timebox); a further fresh held-out batch. | M9 or post-submission |
| K7 | The session email is a demo identifier, not authentication (D5.7). | Anyone can type any address and see that employee's tickets. | Take identity from single sign-on. | Post-submission |
| K8 | The `sd-emp-` label is an unsalted SHA-256 of the email (D4.3). | Pseudonymisation only: reversible by dictionary attack; the plain email is in the description anyway. | Keyed hash (HMAC with a deployment secret) if labels must not reveal identity. | Post-submission |
| K9 | Reconcile residual risk: an issue created by a timed-out POST but still missing from search after all polls can lead to a second POST (D4.7). | Rare duplicate ticket; both carry the same `sd-op-` label and later reconciliation picks the oldest. | Longer or adaptive reconcile polling; a cleanup job that closes the newer duplicate. | Post-submission |
| K10 | Lease residual risk: a single create POST that outlasts the 20 s in-flight window lets another caller take the op over (D6.2). | Rare duplicate ticket, only with a concurrent retry during an unusually slow POST; same label, oldest wins. | An overall per-request deadline below the window, or a window derived from the full httpx timeout. | Post-submission |
| K12 | Stored conversation history is never trimmed, and checkpoints grow quadratically with session length (D5.12, D6.6). | Larger `data/smartdesk.db` and slower state loads in long sessions; mitigated by `python -m smartdesk.sessions compact` and the router history cap. | Summarise old turns or start a new thread per ticket, keeping the absolute flow indices valid. | Post-submission |
| K13 | Session maintenance relies on LangGraph internals: time-ordered uuid6 checkpoint ids and the private `__interrupt__` channel (D6.8). | A LangGraph upgrade could make `list` misreport pending approvals or `compact` keep the wrong checkpoint. | Tests check both against real sessions; re-run them on every LangGraph upgrade, and pin the version. | Post-submission |
| K14 | A failure while handling a reply at review consumes that approval step (D6.4). | The employee sees the draft again and must approve again; nothing is created twice or without approval. | None planned; this is the safe behaviour. | — |
| K15 | Redaction is pattern-based (emails, keys, tokens, phone and card numbers). | Names, addresses and free-text personal details in messages are not masked in traces. | Add an NER-based redactor if traces must be free of all personal data. | Post-submission |
| K16 | Dense retrieval only; no hybrid search or re-ranking (optional bonus, needs approval). | Retrieval relies on embeddings alone; one held-out gap outscored answerable questions. | Hybrid search with a re-ranker, only with approval. | Post-submission |
| K17 | The demo recording (DEL-4) is not made yet; the architecture diagrams and the demo run sheet are done (M9). | Deliverable DEL-4 is open. | Record the 3–5 minute run sheet in `docs/demo-script.md`, or capture the listed screenshots. | M9 (author) |
| K20 | All UI turns run on one worker thread, one at a time (D8.1). | Concurrent users queue behind each other's turns (a few seconds each); fine for the demo. | Per-thread SQLite connections in `TicketStore` and the checkpointer, then a multi-worker pool. | Post-submission |
| K21 | No browser-side session resume: a page reload starts a new Chainlit session (D8.2). | The conversation stays in SQLite and resumes in the CLI (`--session`), not in the browser. | Chainlit data layer and authentication, mapping the Chainlit thread to the LangGraph thread_id. | Post-submission |
| K22 | The Edit dialog relies on Chainlit's emitter: `on_edit` sends `task_end()` itself because Chainlit 2.12 does not after an action callback (D8.6). | A Chainlit upgrade could change this: buttons would stay disabled after an edit, or the fix become redundant. | Re-run the UI smoke check (Edit, then Approve) on every Chainlit upgrade; the version is pinned `<3`. | Post-submission |
| K24 | Over-abstention on some follow-ups the KB answers: "How do I add them?" after a parents-coverage question escalated (M7 multi-turn D5). | A correct answer is replaced by a ticket offer; nothing is invented. | Inspect the retrieved passages and sufficiency prompt for dependant questions; add dev cases before changing the prompt. | Post-submission |
| K26 | The domain filter can exclude the right document when a question spans IT and HR (`ho-26`, laptop return on exit, routed IT). Found on the held-out set and deliberately not tuned against. | The answer cited an IT document; unfiltered retrieval ranked the HR exit policy first. | Merge filtered and unfiltered results, or fall back to unfiltered on mixed-domain questions; build dev cases first. | Post-submission |
| K27 | A workplace question with no KB entry ("What is on the cafeteria menu this week?", `ho-29`) was declined as out of scope instead of escalated. Found on the held-out set and deliberately not tuned against. | The employee gets no ticket offer for a legitimate workplace question. | Planned improvement: workplace questions with no KB entry should offer a ticket rather than be declined (router boundary for workplace facilities); dev cases first. | Post-submission |
| K29 | Live test `test_live_flow_aware_routing` fails 3/3: a reply with the issue details, while SmartDesk is asking for them, is routed `create_ticket` instead of `provide_info`. The same result with the router prompt from before K25, so it is a model-behaviour change since M6, not a code change. | None for the employee: in all runs the details filled the draft and the flow asked for the email, because `collect_ticket` treats both intents alike mid-flow. The live test's label check fails. | Decide whether the test should assert the outcome (details captured, flow continues) rather than the label, or add a router example; dev case first. | Needs approval |

## Resolved

- K28 (M9): the ticket extractor invented details the employee never gave ("The issue started recently", "has not mentioned any troubleshooting steps"; seen live in KAN-22 and KAN-23). Root cause: the prompt asked the description to cover "the problem, when it started, what they tried, the impact", which the model treated as slots to fill. Fix: the prompt now includes timing, impact and steps tried only if the employee stated them, with no "not specified" filler; and `remove_unstated_claims` drops any sentence with filler or with timing the employee never gave, so it holds whatever the model does. Tests: `tests/test_ticket_grounding.py` (offline, the live text as input), `test_live_extractor_adds_no_timing_or_filler_the_employee_did_not_give` (raw prompt output) and `test_live_ticket_for_a_gap_question_holds_only_what_the_employee_said`, both passing 3/3 runs.

- K23 (M7, `f35b55c`): an `unclear` reply to SmartDesk's open question keeps the question open; `test_unclear_answer_to_the_held_draft_question_asks_again[UNCLEAR]`, `test_unclear_reply_while_issue_details_are_awaited_asks_for_them_again`, multi-turn C6.
- K25 (M7, `f35b55c`): back-references to an earlier issue route to that issue, not ticket status (router prompt); multi-turn E1–E4 (E4 is a status control).

- K1 (M7): measured, not just prompted: no-merge 10/11 (type A 6/6; the C miss is K23, a stalled flow, not a merge), carry-over 6/6; `docs/evaluation-report.md`.
- K3 (M7): measured: unclear first messages 8/8 asked for clarification, out-of-scope declined 6/6 dev and 4/4 held-out; the with-history miss is K25.

- K5 (M8): synchronous `ChatSession` under async Chainlit; `AsyncChatSession` on a worker thread (D8.1), `test_turns_run_on_the_shared_worker_thread`.
- K6 (M8): log redaction in the Chainlit entry point; `test_app_installs_log_redaction`.
- K2 (M6): generic "Support ticket request" summary; `test_no_title_is_kept_before_the_issue_is_described`.
- K11 (M6): no fallback model; `.env.example` sets `gpt-4o`; `test_live_fallback_model_returns_structured_output`.
- K18 (M6): "new" after a re-asked held-draft question; `test_new_after_the_held_draft_question_was_asked_again_starts_from_the_original_request`.
- K19 ("Style: ruff lint fixes"): 50 ruff findings fixed; `ruff check src tests` passes.
