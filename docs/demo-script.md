# Demo Script

How to prepare and run the SmartDesk AI demo. The ticket sections are in
place from Milestone 4. The conversational steps are completed in Milestone 5
(approval flow) and Milestone 9 (final recording).

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

## 3. Flows to show in the recording

| # | Flow | What to show |
|---|---|---|
| 1 | RAG answer | An answerable IT or HR question, answered with source citations |
| 2 | Escalation + ticket creation | A gap question → offer of a ticket → the collected fields → the approval summary → approve → the real ticket key and link *(M5)* |
| 3 | Ticket status, multiple tickets | Priya asks "what's the status of my tickets?" → both tickets listed → she picks one → its status and the agent's comment *(M5)* |
| 4 | Ticket status, no tickets | A second employee asks for status → told clearly that no tickets were found *(M5)* |
| 5 | Duplicate protection | Approving the same ticket twice returns the same key *(M5)* |

## 4. Clean up after recording

Demo tickets can stay in the project. To remove them, delete them in Jira.
Any leftover live-test tickets carry the `sd-live-test` label and can be found
with the JQL `labels = "sd-live-test"`.
