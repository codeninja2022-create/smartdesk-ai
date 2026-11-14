# Demo Script

How to prepare and record the SmartDesk AI demo (deliverable DEL-4): a 3–5 minute screen
recording, or annotated screenshots, showing the three flows: RAG answer, ticket creation and
ticket status.

## 0. Pre-flight checklist

- [ ] `.env` has `OPENAI_API_KEY` and the four `JIRA_*` variables; Langfuse optional.
- [ ] The index is built: `python -m smartdesk.kb.ingest` reports 40 documents and a sample retrieval.
- [ ] `pytest` passes.
- [ ] Demo tickets prepared (section 1) and updated by the "support agent" (section 2).
- [ ] `chainlit run src/smartdesk/ui/app.py` is running; browser at http://localhost:8000, zoomed so
      the chat and the source panel are readable.
- [ ] Jira board open in a second tab, to show a created ticket.

## Ground rule: who creates and who updates tickets

- **Tickets are created only through SmartDesk** (the chat flow from M5) **or
  the ticket CLI** (`python -m smartdesk.tickets create`). Both apply the
  labels status lookups depend on: `smartdesk`, `sd-cat-*`, `sd-emp-*` and
  `sd-op-*`. They also record the email → ticket mapping in SQLite.
- **The human support agent never creates tickets in the Jira UI.** A ticket
  created there has no `sd-emp-` label and is invisible to status lookups.
  The agent only *updates* existing tickets in Jira: changes the status,
  adds comments, sets priority or assignee.
- Use fictional `@novatech.example` addresses for demo employees.

## 1. Prepare demo data (before recording)

Create two tickets for one employee, so the multiple-ticket case can be shown,
and none for a second employee, so the no-ticket case can be shown:

```powershell
python -m smartdesk.tickets create --email priya.sharma@novatech.example --category IT `
    --summary "External monitor flickers when docked" `
    --description "My Dell monitor flickers every few seconds when my laptop is on the dock. Tried another cable." `
    --priority Medium
python -m smartdesk.tickets create --email priya.sharma@novatech.example --category HR `
    --summary "Parking permit for the Pune office" `
    --description "I am starting in the Pune office next month and need a parking permit." `
    --priority Low
python -m smartdesk.tickets list --email priya.sharma@novatech.example
```

Both topics are deliberate KB gaps (`docs/data-sources.md`), so they are
realistic escalations.

## 2. Support agent updates the tickets in the Jira UI

Acting as the support agent, in the Jira project board:

1. Open the IT ticket, move it to **In Progress** and add a comment, for
   example: *"Hi Priya, please try the monitor on a different dock port and
   tell us if it still flickers. — Sam, IT Support"*.
2. Leave the HR ticket in **To Do** with no comments.

Then check that SmartDesk sees the updates:

```powershell
python -m smartdesk.tickets show KAN-<n> --email priya.sharma@novatech.example
```

The output must show the new status and the agent's comment.

## 3. Recording run sheet (about 4 minutes, Chainlit)

The email is locked per session, so ticket creation (Arjun) and status checks (Priya, then Meera)
each use their own chat: click **New Chat** where marked.

| Time | Flow | Type this | What to point out |
|---|---|---|---|
| 0:00 | Intro | — | Welcome message: what SmartDesk does; the session id |
| 0:15 | **1. RAG answer** | `How do I connect to the VPN from my Mac at home?` | Grounded steps with `[n]` markers and a **Sources** list; click the `doc_id` to open the cited section |
| 0:45 | Follow-up (multi-turn) | `And on Windows?` | Understood from context, again cited |
| 1:05 | Escalation | `The printer on the 3rd floor is not working.` | Not in the KB (deliberate gap): says so, does not guess, offers a ticket |
| 1:25 | **2. Ticket creation** | `yes please` | Ticket starts from the printer question; asks for the email |
| 1:35 | | `arjun.mehta@novatech.example` | Category inferred (IT); full summary with **Approve / Edit / Cancel**; nothing is created yet |
| 1:55 | HITL edit | **Edit** → priority `High` → save | The summary updates; the earlier approval no longer applies |
| 2:15 | Approve | **Approve** | Real Jira key and link; open it in the Jira tab (labels `smartdesk`, `sd-cat-it`) |
| 2:40 | **3. Ticket status** | **New Chat**, then `What's the status of my tickets?` | Asks for the email |
| 2:50 | | `priya.sharma@novatech.example` | Both prepared tickets listed, open first, as buttons |
| 3:05 | | click the monitor ticket | Status **In Progress**, last update, link and the support agent's comment |
| 3:30 | No tickets | **New Chat**, then `Any updates on my tickets? My email is meera.iyer@novatech.example` | Told clearly that no tickets were found, with an offer to raise one |
| 3:50 | Out of scope | `What's the weather in Pune today?` | Politely declined, with what SmartDesk can do |
| 4:05 | Close | — | Recap: answers only from the KB with sources, escalates honestly, never creates a ticket without approval, status for your own email only |

If an answer differs from the script (the LLM is not fully deterministic), keep recording unless a
flow fails; the point is the behaviour, not exact wording.

### Screenshot alternative

Capture and annotate, in order: (1) the VPN answer with sources and the open source panel; (2) the
escalation reply with the ticket offer; (3) the review summary with Approve / Edit / Cancel; (4) the
confirmation with the Jira key and link; (5) the ticket in Jira; (6) Priya's two-ticket list;
(7) the selected ticket's status and comment; (8) the no-tickets reply.

### Shown by tests rather than on screen

Duplicate protection (approving the same draft twice returns the same key) and approval-bypass
attempts are hard to show in a UI, where the Approve button is bound to one draft. They are covered
by `test_same_draft_again_in_the_session_reports_the_existing_ticket`,
`tests/test_tickets_concurrency.py` and `tests/test_guardrails.py`.

## 4. Clean up after recording

Demo tickets can stay in the project. To remove them, delete them in Jira.
Any leftover live-test tickets carry the `sd-live-test` label and can be found
with the JQL `labels = "sd-live-test"`.
