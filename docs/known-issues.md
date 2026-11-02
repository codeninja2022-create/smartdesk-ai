# Known issues and future work

Open limitations and planned work, one line each. Sources: `docs/decisions.md`,
the README and the milestone reports. Remove a line only when its fix is
merged and tested.

Last updated: Milestone 8.

| # | Issue | Impact | Planned fix | When |
|---|---|---|---|---|
| K1 | An unrelated knowledge question asked just before a ticket request is kept out of the draft only by an extractor prompt rule (D5.13, M7-1). | A new ticket could absorb the previous question's topic. Three live tests pass; the rate is not measured. | Labelled multi-turn eval cases; report no-merge and carry-over rates; if too low, decide the flow start in code from a classifier field. | M7 |
| K3 | Out-of-scope and ambiguous handling (rubric D3) is tested case by case but not measured. | No evidence of its rate beyond the eval-set routing accuracy. | Report out-of-scope and unclear handling over the eval set. | M7 |
| K4 | The evaluation sets are small (held-out: 7 answerable, 10 gap questions). | Perfect held-out scores are indicative, not statistically strong. | Extend the eval set and report Recall@5 and escalation precision/recall. | M7 |
| K7 | The session email is a demo identifier, not authentication (D5.7). | Anyone can type any address and see that employee's tickets. | Take identity from single sign-on. | Post-submission |
| K8 | The `sd-emp-` label is an unsalted SHA-256 of the email (D4.3). | Pseudonymisation only: reversible by dictionary attack; the plain email is in the description anyway. | Keyed hash (HMAC with a deployment secret) if labels must not reveal identity. | Post-submission |
| K9 | Reconcile residual risk: an issue created by a timed-out POST but still missing from search after all polls can lead to a second POST (D4.7). | Rare duplicate ticket; both carry the same `sd-op-` label and later reconciliation picks the oldest. | Longer or adaptive reconcile polling; a cleanup job that closes the newer duplicate. | Post-submission |
| K10 | Lease residual risk: a single create POST that outlasts the 20 s in-flight window lets another caller take the op over (D6.2). | Rare duplicate ticket, only with a concurrent retry during an unusually slow POST; same label, oldest wins. | An overall per-request deadline below the window, or a window derived from the full httpx timeout. | Post-submission |
| K12 | Stored conversation history is never trimmed, and checkpoints grow quadratically with session length (D5.12, D6.6). | Larger `data/smartdesk.db` and slower state loads in long sessions; mitigated by `python -m smartdesk.sessions compact` and the router history cap. | Summarise old turns or start a new thread per ticket, keeping the absolute flow indices valid. | Post-submission |
| K13 | Session maintenance relies on LangGraph internals: time-ordered uuid6 checkpoint ids and the private `__interrupt__` channel (D6.8). | A LangGraph upgrade could make `list` misreport pending approvals or `compact` keep the wrong checkpoint. | Tests check both against real sessions; re-run them on every LangGraph upgrade, and pin the version. | Post-submission |
| K14 | A failure while handling a reply at review consumes that approval step (D6.4). | The employee sees the draft again and must approve again; nothing is created twice or without approval. | None planned; this is the safe behaviour. | — |
| K15 | Redaction is pattern-based (emails, keys, tokens, phone and card numbers). | Names, addresses and free-text personal details in messages are not masked in traces. | Add an NER-based redactor if traces must be free of all personal data. | Post-submission |
| K16 | Dense retrieval only; no hybrid search or re-ranking (optional bonus, needs approval). | Retrieval relies on embeddings alone; one held-out gap outscored answerable questions. | Hybrid search with a re-ranker, only with approval. | Post-submission |
| K17 | Architecture diagram, demo script walkthrough and recording are not done yet. | Submission deliverables DEL-3 and DEL-4 are open. | Mermaid diagram in the README; 3–5 minute recording of the three flows. | M9 |
| K20 | All UI turns run on one worker thread, one at a time (D8.1). | Concurrent users queue behind each other's turns (a few seconds each); fine for the demo. | Per-thread SQLite connections in `TicketStore` and the checkpointer, then a multi-worker pool. | Post-submission |
| K21 | No browser-side session resume: a page reload starts a new Chainlit session (D8.2). | The conversation stays in SQLite and resumes in the CLI (`--session`), not in the browser. | Chainlit data layer and authentication, mapping the Chainlit thread to the LangGraph thread_id. | Post-submission |
| K22 | The Edit dialog relies on Chainlit's emitter: `on_edit` sends `task_end()` itself because Chainlit 2.12 does not after an action callback (D8.6). | A Chainlit upgrade could change this: buttons would stay disabled after an edit, or the fix become redundant. | Re-run the UI smoke check (Edit, then Approve) on every Chainlit upgrade; the version is pinned `<3`. | Post-submission |

## Resolved

- K5 (M8): synchronous `ChatSession` under async Chainlit; `AsyncChatSession` on a worker thread (D8.1), `test_turns_run_on_the_shared_worker_thread`.
- K6 (M8): log redaction in the Chainlit entry point; `test_app_installs_log_redaction`.
- K2 (M6): generic "Support ticket request" summary; `test_no_title_is_kept_before_the_issue_is_described`.
- K11 (M6): no fallback model; `.env.example` sets `gpt-4o`; `test_live_fallback_model_returns_structured_output`.
- K18 (M6): "new" after a re-asked held-draft question; `test_new_after_the_held_draft_question_was_asked_again_starts_from_the_original_request`.
- K19 ("Style: ruff lint fixes"): 50 ruff findings fixed; `ruff check src tests` passes.
