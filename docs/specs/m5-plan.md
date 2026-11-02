# Milestone 5 plan — LangGraph orchestration and HITL

> **Reconstructed after implementation from repo history; not the original pre-implementation plan.**
> Sources: `CLAUDE.md` (Milestone 5), commit `2cd741b` (2026-11-01; M5 was committed together with M6), `docs/decisions.md` (D5.1–D5.13).

## Scope (from `CLAUDE.md`)

- A single-agent LangGraph workflow: knowledge questions, ticket creation, ticket status, greetings and out-of-scope requests, multi-turn conversation, intent changes and clarification.
- `interrupt()` for human approval before Jira ticket creation: show the complete ticket; approve, edit or cancel. Never create a ticket without explicit approval of its final details.
- SQLite-backed checkpoints.
- Email is a demo identifier, not authentication (documented).
- Session email locking: validate and normalise, lock for the session, refuse a different email, look up only the session email's tickets.

## Decisions

Approved decisions, including the four amendments, are in `docs/decisions.md`
as **D5.1–D5.12**. **D5.13** records the fixes made after live testing
(ticket flow start, held-draft "continue or new?", seeding from the question
just asked).

## Delivered (in commit `2cd741b`)

| Item | Implementation |
|---|---|
| Routing | Flow-aware intent router (`graph/workflow.py`) with `provide_info`, `cancel` and `unclear`, and a flow-state system message |
| Tickets | Slot-filling (`graph/tickets.py`), `present_ticket` + `review_ticket` with `interrupt()`; approval bound to the draft's op_id; `submit_ticket` is the only node that creates tickets |
| Status | `graph/status.py`: one ticket shown, several listed and chosen, none said clearly with an offer |
| Identity | `graph/identity.py`: email capture rules and session lock (D5.6) |
| Sessions | `SqliteSaver` checkpoints on `data/smartdesk.db`; `ChatSession` as the only entry point; `--session` resume in the CLI |
| Topic changes | Draft kept on hold during other questions; "continue my ticket" resumes it |
| Docs | README conversation, session-email and privacy sections; decisions D5.x; rubric updates |

## Verification

M5 test results were reported during development but not recorded separately
in git. The combined M5+M6 commit records 386 offline tests passed (23 live
skipped), live OpenAI 19/19 and live Jira 4/4.

## Deferred

M6-1 compare-and-set (resolved in M6, D6.1); M7-1 measurement of unrelated
questions merging into a new ticket (`docs/decisions.md`, `docs/known-issues.md` K1).
