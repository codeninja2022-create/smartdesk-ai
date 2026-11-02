# Milestone 4 plan — Jira integration

> **Reconstructed after implementation from repo history; not the original pre-implementation plan.**
> Sources: `CLAUDE.md` (Milestone 4), commits `a54a98b` and `7909c53` (2026-11-01), `docs/decisions.md` (D4.1–D4.11).

## Scope (from `CLAUDE.md`)

- A modular Jira service: create tickets, get ticket details, look up an employee's tickets by email, status and comments, multiple- and no-ticket cases.
- Collect email, summary, description and IT/HR category; return real ticket IDs and URLs.
- SQLite mappings; duplicate prevention with a stable operation ID, SQLite status and Jira labels.
- On ambiguous timeouts, reconcile before retrying; never blindly repeat creation.
- Live tests marked `jira_live`, skipped without credentials.

## Decisions

The approved design decisions, including the five amendments, are recorded
in `docs/decisions.md` as **D4.1–D4.11** (layering, email label, unsalted
hash, lookup union, op id, op states, reconcile policy, read retries, live-test
gating and teardown, demo ticket rules).

## Delivered (commit `a54a98b`)

| Item | Implementation |
|---|---|
| Service | `TicketService` interface with a Jira Cloud REST v3 implementation |
| Store | SQLite `employee_tickets` mappings and `ticket_ops` (pending / unknown / created / failed) |
| Duplicates | Op id from session + draft, `sd-op-` label; ambiguous timeouts and 5xx reconciled by label search before any retry; bounded create attempts |
| Lookup | `sd-emp-` label search unioned with the local mapping; ownership enforced |
| Reads | Retries with backoff, honouring `Retry-After` on 429 |
| CLI | `python -m smartdesk.tickets create/list/show` |
| Tests | In-memory Jira over `httpx.MockTransport`; `jira_live` tests gated on `SMARTDESK_LIVE_TESTS=1` and `JIRA_*`, deleting the test issue or moving it to Done |
| Docs | README Jira section, `docs/demo-script.md`, rubric updates |

## Deferred (commit `7909c53`)

M6-1: a compare-and-set before retrying an `unknown` op, so concurrent
retries cannot both create a ticket. Resolved in M6 (D6.1).

## Verification

The commits do not record test counts; the live Jira tests passed against project KAN (rubric B1).
