# Decisions

Agreed design decisions, and items deliberately deferred to later milestones.
Changing a recorded decision needs discussion first (`CLAUDE.md`).

## Milestone 4 — Jira integration

Approved before implementation, including the five amendments marked *(amended)*.

| # | Decision | Rationale |
|---|---|---|
| D4.1 | Three layers: `TicketService` interface → `JiraTicketService` → `JiraClient` (httpx, REST v3) + `TicketStore` (SQLite). | The graph (M5) depends only on the interface; Jira and SQLite can be faked in tests. |
| D4.2 | Email lives in the issue description (`Employee email: …`) and as a label `sd-emp-<sha256(email)[:16]>`. No custom field. | Project KAN is team-managed; custom fields need admin UI setup. Labels support exact JQL lookup. |
| D4.3 | The `sd-emp-` hash is unsalted and documented as **pseudonymisation, not anonymisation**: it is reversible by dictionary attack. *(amended)* | Same email gives the same label on any machine, with no shared secret. The plain email is in the description anyway. |
| D4.4 | Lookup = Jira label search ∪ SQLite `employee_tickets` mapping, with write-back. Jira is the source of truth for status and comments. Ownership is required for `get_ticket`. | The spec asks for a local mapping (Q13). SQLite also covers Jira's search-index lag. |
| D4.5 | Op id = `sha256("smartdesk-op-v1" + session_id + canonical draft)`, carried as label `sd-op-<op_id[:32]>`. | Same approved draft in the same session gives one ticket. An edited draft or a new session gives a new one. |
| D4.6 | `ticket_ops` states: `pending`, `unknown`, `created`, `failed`. A connect error or 4xx means `failed` (safe to retry). A read timeout, dropped connection or 5xx means `unknown`. | Separates "definitely not created" from "may exist". |
| D4.7 | An `unknown` op is always reconciled (label search, 3 polls × 2 s) before any further POST. At most `JIRA_MAX_CREATE_ATTEMPTS` (2) POSTs per call. If several issues match, the oldest wins. | "Reconcile before retrying; never blindly repeat creation." |
| D4.8 | Reads retry with exponential backoff on timeouts, 429 and 5xx, and **honour `Retry-After` on 429**, capped at 30 s. Creation is never retried by the transport. *(amended)* | Reads are idempotent; creation is not. |
| D4.9 | `jira_live` tests need **both** the `JIRA_*` credentials **and** `SMARTDESK_LIVE_TESTS=1`. *(amended)* | Credentials are configured locally, so a plain `pytest` would otherwise create real tickets. |
| D4.10 | Live-test teardown deletes the issue. **If the delete fails, it moves the issue to Done and keeps the `sd-live-test` label.** *(amended)* | Leaves no open test tickets, and leftovers stay findable. |
| D4.11 | Demo and test tickets are created **only via SmartDesk or `python -m smartdesk.tickets`**. The human agent only updates them in the Jira UI (`docs/demo-script.md`). *(amended)* | Tickets made in the Jira UI lack the `sd-emp-` label and would be invisible to status lookups. |

## Deferred to Milestone 6

### M6-1: Compare-and-set before retrying an `unknown` op

**Gap.** `create_ticket` guards a *recent* `pending` op as in flight, but an
op in `unknown` has no owner. Two concurrent calls for the same `unknown` op
can both reconcile, both find nothing, and both POST, which creates duplicates.
`record_attempt` updates the row unconditionally, so it does not stop the
second caller. The window is small: it needs a double submit at the same
moment as an ambiguous timeout. It matters once a UI such as Chainlit can run
concurrent turns.

**To do:**
- Add a conditional transition to `TicketStore`, e.g.
  `begin_retry(op_id, expected_attempts) -> bool`:
  `UPDATE ticket_ops SET status='pending', attempts=attempts+1, updated_at=? WHERE op_id=? AND status='unknown' AND attempts=?`.
  It succeeds only when `rowcount == 1`.
- In `JiraTicketService.create_ticket`, use it in place of `record_attempt`
  for every POST that follows a reconcile. If the update matches no row,
  another caller owns the retry: treat it as in flight and raise
  `TicketCreationUncertain`, without posting.
- Apply the same compare-and-set to the reconcile step's start, so a
  `pending` op older than the in-flight window is taken over by exactly one caller.
- Tests: two service instances on one SQLite file interleave on the same
  `unknown` op, and exactly one POST is sent. Also cover a stale `pending`
  op taken over by one of two callers.
