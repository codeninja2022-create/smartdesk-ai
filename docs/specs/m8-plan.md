# Milestone 8 plan — Chainlit UI

Approved 2026-11-01. Order change approved: M8 is implemented before M7.

Decisions taken at approval: single worker thread (turn queueing logged in
`docs/known-issues.md`), Chainlit as a main dependency, `approve(op_id)` and
`TurnResult.created_ticket` added to `ChatSession`. Additions at approval: a
three-line welcome message with the New Chat note, and the cited chunk text
shown first in the citation side panel.

## 1. Execution model: worker thread, not `AsyncSqliteSaver` (D5.9, K5)

`AsyncChatSession` in `graph/session.py` wraps the sync `ChatSession`. Every
call (`send`, `approve`, `edit`, `cancel`, `pending_approval`) runs on **one
process-wide worker thread** (`ThreadPoolExecutor(max_workers=1)` +
`loop.run_in_executor`). Nodes, graph and checkpointer are unchanged.

- All nodes are synchronous (LLM, httpx Jira client, Chroma); `ainvoke` would
  run them on threads anyway.
- `smartdesk.sessions` and the CLI use `SqliteSaver`; one checkpointer flavour
  on the file is kept.
- The single worker is deliberate: `TicketStore` and `SqliteSaver` each share
  one connection across threads, and `TicketStore` uses explicit
  `BEGIN IMMEDIATE`. Serial turns keep SQLite safe and also serialise a
  double-clicked button. Trade-off: concurrent users queue behind each other's
  turns (known issue; future fix: per-thread connections).

## 2. Session and thread_id mapping

- `on_chat_start`: `thread_id = uuid4()`, a new `AsyncChatSession` in
  `cl.user_session`. One Chainlit chat = one LangGraph thread = one email lock.
- Chainlit's **New Chat** starts a new session; this is how a different email
  is used (D5.6). The welcome message says so.
- Graph, retriever, ticket service and checkpointer are built once per process
  (lazily) and shared; each session has its own `ChatSession` and Langfuse
  callbacks.
- No browser resume (`on_chat_resume` needs Chainlit's data layer and auth).
  The welcome shows the session id; `python -m smartdesk --session <id>`
  resumes it. A page reload starts a new session.
- `on_chat_end` flushes Langfuse.

Welcome message (three suggestions plus the note):

- Ask an IT or HR question, e.g. "How do I reset my VPN password?"
- Report a problem to raise a ticket, e.g. "My laptop won't charge."
- Check your tickets, e.g. "What's the status of my tickets?"
- To use a different email, start a New Chat.

## 3. Approve / Edit / Cancel buttons (HITL)

- When `TurnResult.approval` is set, the review message (the last reply) gets
  **Approve**, **Edit**, **Cancel** actions, each carrying `op_id`.
- `ChatSession.approve(op_id=None)`: the button passes its own `op_id`. After an
  edit, an old Approve button resumes with a stale op_id, which `review_ticket`
  rejects (`REVIEW_STALE`, D5.3). The UI never looks up the current op_id itself.
- Buttons are removed from the message after any click. With no approval
  pending (double click, already handled) the employee gets "That ticket is no
  longer awaiting approval." instead of an exception.
- **Edit**: `AskActionMessage` picks the field (Summary, Description,
  Category, Priority: `EDITABLE_FIELDS`; email is not editable).
  Summary/Description use `AskUserMessage`; Category and Priority offer their
  enum values as buttons. Then `session.edit({field: value})`; the graph
  validates it and re-presents the draft with a new op_id and new buttons. A
  timeout or dismissal changes nothing.
- Typed replies behave exactly as in the CLI (exact words approve/cancel,
  anything else goes through the graph).

## 4. Citations

- The answer text is shown as produced, including `Sources:` with `(doc_id)`.
- For each citation in `state["citations"]` (reset every turn) a `cl.Text`
  element with `name = doc_id`, `display="side"` is attached; Chainlit links
  each `doc_id` in the message to it.
- Panel content: the document title, then the **cited chunk text** first, then
  the full document when it is long. The chunk text is rebuilt by re-chunking
  `data/kb/<doc_id>.md` with `kb.chunking.chunk_document` (the same function
  ingestion uses) and keeping the chunks whose section matches the citation's
  section. No passage text is added back to state (D6.7). If no chunk matches,
  the full document is shown; a missing file skips the element and the text
  citation remains.

## 5. Ticket status and creation

- Listing and details text from `graph/status.py` is shown as is; Jira links
  render as Markdown links.
- When `awaiting == "ticket_choice"`, one button per listed candidate
  (`KAN-7: summary`, at most the 10 listed) sends that key as a message; the
  existing key path and the service's ownership check handle it.
- `TurnResult.created_ticket`: set only when `last_ticket` changed during the
  turn. The UI shows a highlighted confirmation (✅ key and link) without
  parsing reply text.

## 6. Errors

| Source | Display |
|---|---|
| `TurnResult.error` = `llm_unavailable` / `internal_error` (D6.4) | `cl.ErrorMessage` with the existing safe reply (+ "draft saved") |
| `empty` / `too_long` | Normal message, existing text |
| `state.last_error` (Jira, status and create) | The graph's text, prefixed ⚠️ |
| Exception outside `ChatSession` (UI, edit dialog) | Caught, exception type logged, `INTERNAL_ERROR` shown |
| Startup: empty KB index | Error instead of the welcome; messages refused |
| Startup: Jira not configured | Welcome notes ticket features are off |

`install_log_redaction()` runs at app start (K6). Raw HTML stays disabled
(`unsafe_allow_html = false`): Jira comments and KB text are untrusted.

## 7. Files

| File | Change |
|---|---|
| `src/smartdesk/graph/session.py` | `AsyncChatSession`, `approve(op_id=None)`, `TurnResult.created_ticket` |
| `src/smartdesk/ui/__init__.py`, `ui/render.py` | Pure helpers: actions, citation panel content, candidate buttons, error kind, welcome text |
| `src/smartdesk/ui/app.py` | Thin Chainlit handlers |
| `.chainlit/config.toml`, `chainlit.md` | App name, telemetry off, no raw HTML |
| `pyproject.toml` | `chainlit>=2.12,<3` |
| `.gitignore` | `.files/`, `.chainlit/translations/` |
| README, `decisions.md` (D8.x), `known-issues.md`, `rubric-traceability.md` | Docs |

Run: `chainlit run src/smartdesk/ui/app.py`.

## 8. Tests

- `tests/test_async_session.py`: turns run off the event loop; two concurrent
  approvals create one ticket; stale `op_id` refused; approve with nothing
  pending replies instead of raising; edit yields a new op_id;
  `created_ticket` set only on the creating turn.
- `tests/test_ui_render.py`: actions carry the shown op_id; citation panel
  shows the cited chunk first, falls back to the full document, skips a
  missing file; candidate buttons; error classification; the app module
  installs log redaction.
- Manual smoke check of RAG answer, ticket creation (approve/edit/cancel) and
  ticket status in the running app; results reported as observed.
