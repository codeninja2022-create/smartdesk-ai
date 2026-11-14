# Known issues and future work

Open limitations and planned work, one line each. Sources: `docs/decisions.md`,
the README and the milestone reports. Remove a line only when its fix is
merged and tested.

Last updated: Milestone 7 evaluation (after M8).

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
| K17 | Architecture diagram, demo script walkthrough and recording are not done yet. | Submission deliverables DEL-3 and DEL-4 are open. | Mermaid diagram in the README; 3–5 minute recording of the three flows. | M9 |
| K20 | All UI turns run on one worker thread, one at a time (D8.1). | Concurrent users queue behind each other's turns (a few seconds each); fine for the demo. | Per-thread SQLite connections in `TicketStore` and the checkpointer, then a multi-worker pool. | Post-submission |
| K21 | No browser-side session resume: a page reload starts a new Chainlit session (D8.2). | The conversation stays in SQLite and resumes in the CLI (`--session`), not in the browser. | Chainlit data layer and authentication, mapping the Chainlit thread to the LangGraph thread_id. | Post-submission |
| K22 | The Edit dialog relies on Chainlit's emitter: `on_edit` sends `task_end()` itself because Chainlit 2.12 does not after an action callback (D8.6). | A Chainlit upgrade could change this: buttons would stay disabled after an edit, or the fix become redundant. | Re-run the UI smoke check (Edit, then Approve) on every Chainlit upgrade; the version is pinned `<3`. | Post-submission |
| K23 | An unclear reply to "continue that one, or start a new ticket?" is routed `unclear`; the clarify reply clears the open question (M7 multi-turn C6). | The next "new ticket" re-asks the held-draft question instead of starting the new ticket; nothing is created. | Re-ask the held-draft question (as `HELD_DRAFT_REASK`) when an unclear reply arrives while it is open. | Needs approval |
| K24 | Over-abstention on some follow-ups the KB answers: "How do I add them?" after a parents-coverage question escalated (M7 multi-turn D5). | A correct answer is replaced by a ticket offer; nothing is invented. | Inspect the retrieved passages and sufficiency prompt for dependant questions; add dev cases before changing the prompt. | Needs approval |
| K25 | "Same issue as before" after a knowledge question is routed to `ticket_status` (M7 unclear U9). | SmartDesk asks for an email to look up tickets instead of resolving the earlier issue. | Router prompt example for back-references to the previous question; dev case first. | Needs approval |
| K26 | The domain filter can exclude the right document when a question spans IT and HR (`ho-26`, laptop return on exit, routed IT). | The answer cited an IT document; unfiltered retrieval ranked the HR exit policy first. | Merge filtered and unfiltered results, or fall back to unfiltered on mixed-domain questions; measure on dev first. | Needs approval |
| K27 | A gap topic phrased as a facilities question ("What is on the cafeteria menu this week?", `ho-29`) was declined as out of scope instead of escalated. | The employee gets no ticket offer for a workplace question. | Clarify the out-of-scope boundary for workplace-facilities questions in the router prompt; dev case first. | Needs approval |

## Resolved

- K1 (M7): measured, not just prompted: no-merge 10/11 (type A 6/6; the C miss is K23, a stalled flow, not a merge), carry-over 6/6; `docs/evaluation-report.md`.
- K3 (M7): measured: unclear first messages 8/8 asked for clarification, out-of-scope declined 6/6 dev and 4/4 held-out; the with-history miss is K25.

- K5 (M8): synchronous `ChatSession` under async Chainlit; `AsyncChatSession` on a worker thread (D8.1), `test_turns_run_on_the_shared_worker_thread`.
- K6 (M8): log redaction in the Chainlit entry point; `test_app_installs_log_redaction`.
- K2 (M6): generic "Support ticket request" summary; `test_no_title_is_kept_before_the_issue_is_described`.
- K11 (M6): no fallback model; `.env.example` sets `gpt-4o`; `test_live_fallback_model_returns_structured_output`.
- K18 (M6): "new" after a re-asked held-draft question; `test_new_after_the_held_draft_question_was_asked_again_starts_from_the_original_request`.
- K19 ("Style: ruff lint fixes"): 50 ruff findings fixed; `ruff check src tests` passes.
