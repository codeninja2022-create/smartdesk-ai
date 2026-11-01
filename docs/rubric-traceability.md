# Rubric Traceability

Maps every graded requirement in the official capstone specification
(*SmartDesk AI — An Intelligent IT & HR Operations Agent*, Interview Kickstart
Applied Agentic AI Program) to where it is implemented and how it is verified.

- Quoted text is copied verbatim from the specification. Section numbers (§)
  refer to the specification.
- **Milestone** is the planned SmartDesk milestone (see `CLAUDE.md`).
- **Evidence** points to code, tests and docs once they exist.
- **Status:** ✅ done · 🟡 partial / foundation only · ⬜ not started.

Last updated: Milestone 4.

---

## 1. Marking scheme (§6, 100 marks)

### A. Knowledge Base & RAG Pipeline — 25 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| A1 | Quality and breadth of KB content | 5 | FR-1.1 – FR-1.4, §3.4 | M2 | `data/kb/` (40 docs), `docs/data-sources.md`, `tests/test_kb_data.py` | ✅ |
| A2 | Chunking strategy and justification | 5 | FR-2.1 | M2 | README "Chunking strategy", `src/smartdesk/kb/chunking.py`, `tests/test_kb_chunking.py` | ✅ |
| A3 | Retrieval quality — relevant results for test queries | 5 | FR-2.2, FR-2.3 | M2, M3, M7 | `src/smartdesk/rag/retriever.py`, `tests/test_rag_retriever.py`, `python -m smartdesk.rag.calibrate` (dev Hit@1 0.976 / Recall@5 1.000; held-out Hit@1 0.857 / Recall@5 1.000); report in M7 | 🟡 |
| A4 | LLM grounding — no hallucination | 5 | FR-2.4, NFR-1.3 | M3, M6, M7 | `src/smartdesk/rag/answer.py`, `tests/test_rag_answer.py`, `tests/test_workflow.py`; answers cite an expected doc 41/41 dev, 7/7 held-out (`data/eval/calibration_report.json`); injection hardening in M6 | 🟡 |
| A5 | Confidence / escalation logic | 5 | FR-3.1, FR-3.2 | M3, M7 | threshold 0.35 + LLM sufficiency check, `python -m smartdesk.rag.calibrate` (escalation precision/recall 1.000/1.000 on dev and on held-out), README "Calibrating abstention"; ticket hand-off in M5 | 🟡 |

### B. Ticket Creation (Write Operation) — 20 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| B1 | Successful external API integration | 5 | FR-4.1 | M4 | Jira Cloud REST v3 service `src/smartdesk/tickets/`; `tests/test_live_jira.py` (create, idempotent re-submit, lookup, ownership; passes against project KAN); mocked `tests/test_tickets_*.py` | ✅ |
| B2 | All mandatory fields collected | 5 | FR-4.2 | M5 | ticket-flow tests | ⬜ |
| B3 | Human-in-the-loop confirmation | 5 | FR-4.3 | M5 | `interrupt()` approval tests | ⬜ |
| B4 | Post-creation feedback with ticket ID/link | 5 | FR-4.4 | M4, M5 | `create_ticket` returns the real key and `/browse/KEY` URL (`test_create_ticket_returns_real_key_and_url`, live test); chat confirmation in M5 | 🟡 |

### C. Ticket Status Check (Read Operation) — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| C1 | Status retrieval via API | 5 | FR-5.1 – FR-5.4 | M4 | `get_ticket` returns status, status category and support comments (`test_get_ticket_returns_status_and_comments`, live test); conversational flow in M5 | 🟡 |
| C2 | Multiple-ticket handling (listing & selection) | 5 | FR-5.5 | M4, M5 | `list_tickets` returns all of an employee's tickets, newest update first (`test_multiple_tickets_are_listed_newest_update_first`); selection in M5 | 🟡 |
| C3 | Graceful handling when no tickets found | 5 | FR-5.6 | M4, M5 | `list_tickets` returns `[]`, `get_ticket` returns `None` for missing or foreign keys (`test_no_tickets_returns_empty_list`, `test_get_ticket_hides_other_employees_tickets`); chat wording in M5 | 🟡 |

### D. Agent Orchestration & Routing — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| D1 | Correct intent detection and routing | 5 | §1.2, §5 step 15 | M1 → M5 | `src/smartdesk/graph/workflow.py`, `tests/test_workflow.py`, `tests/test_live_openai.py` | 🟡 |
| D2 | Smooth multi-turn conversations | 5 | NFR-2.1, NFR-2.2, §10 Q16 | M5 | multi-turn tests | 🟡 |
| D3 | Out-of-scope / ambiguous query handling | 5 | NFR-1.2 | M1 → M5 | `tests/test_workflow.py` | 🟡 |

### E. Code Quality & Documentation — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| E1 | Clean, modular, readable code | 5 | NFR-4.1 | all | `src/smartdesk/` | 🟡 |
| E2 | README with setup instructions | 5 | NFR-4.2, DEL-2 | M1 → M9 | `README.md` | 🟡 |
| E3 | Architecture diagram | 5 | NFR-4.3, DEL-3 | M9 | README (Mermaid) | ⬜ |

### F. Error Handling & Robustness — 10 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| F1 | Graceful API failure degradation | 3 | NFR-3.1 | M4, M6 | failure-injection tests | ⬜ |
| F2 | Retry logic / LLM fallback | 3 | NFR-3.2 | M1 → M6 | `src/smartdesk/llm.py` (client retries); fallback in M6 | 🟡 |
| F3 | No hard-coded secrets | 2 | NFR-3.3 | M1 | `src/smartdesk/config.py`, `.env.example`, `.gitignore`, `src/smartdesk/redaction.py` | ✅ |
| F4 | Edge-case handling | 2 | NFR-1.2, FR-5.5, FR-5.6 | M6 | guardrail tests | ⬜ |

### Bonus (§6.1, up to +10, total capped at 100)

| ID | Bonus item (verbatim) | Planned? | Notes |
|---|---|---|---|
| X1 | Hybrid search (dense + sparse + re-ranker) with demonstrable improvement. | Optional | Only with approval (CLAUDE.md); dense retrieval first. |
| X2 | Multi-agent architecture with specialised IT and HR sub-agents. | No | Single agent agreed; needs approval to change. |
| X3 | Evaluation pipeline (LangSmith, Ragas, DeepEval) with quantitative metrics. | Partial | Custom Recall@5 + escalation precision/recall (M7); Ragas/DeepEval optional. |
| X4 | User-facing deployment (Streamlit, Gradio, Chainlit, or web app). | Yes | Chainlit UI (M8). |
| X5 | Caching (semantic cache, Redis, or LLM cache) for repeated queries. | No | — |
| X6 | Advanced memory (long-term, cross-session memory via database or memory framework). | No | Needs approval; SQLite checkpoints are per session. |

---

## 2. Functional requirements (§2)

### FR-1 Data preparation (§2.1.1)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-1.1 | "You must prepare a realistic knowledge base that covers both IT and HR topics for a fictional (or real, anonymised) company." | M2 | ✅ |
| FR-1.2 | "The knowledge base should contain at least 30–50 question–answer pairs or document chunks that span the categories listed below." | M2 | ✅ (40 docs, 413 chunks) |
| FR-1.3 | Categories table: **IT Support** (Password reset process, VPN configuration, Software installation requests, MFA setup, Guest Wi-Fi access, Email configuration on mobile); **HR Policies** (Leave policy (casual, sick, earned), WFH guidelines, Reimbursement process, Code of conduct, Anti-harassment policy, Performance review cycle); **Onboarding** (Day-one checklist, IT equipment allocation, Benefits enrollment, Buddy programme, Probation period); **Payroll & Comp** (Pay-day schedule, Tax declaration process, Salary structure, Stock-option vesting). | M2 | ✅ (every listed topic has a document) |
| FR-1.4 | Example questions to support: "How do I reset my password?", "How do I connect to the VPN?", "How do I request a software licence?", "How many sick leaves per year?", "What is the WFH policy?", "How do I submit a reimbursement?", "What do I do on my first day?", "When do I get my laptop?", "How do I enrol in insurance?", "When is payday?", "How do I submit my tax declaration?", "How does vesting work?" | M2, M7 (eval set) | ✅ (all in `data/eval/eval_set.jsonl`) |

### FR-2 Indexing & retrieval (§2.1.2)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-2.1 | "You must build an indexing pipeline that ingests the documents and makes them searchable." | M2 | ✅ `python -m smartdesk.kb.ingest` |
| FR-2.2 | "Your pipeline must include at least one of the following retrieval strategies (using more than one carries bonus marks): Dense vector search … Sparse keyword search … Hybrid search that combines dense and sparse retrieval with a re-ranker." — **Chosen: dense (OpenAI `text-embedding-3-small` + ChromaDB).** | M2, M3 | ✅ dense retrieval indexed |
| FR-2.3 | "Regardless of strategy, you must demonstrate that the retrieval pipeline returns relevant chunks for a given query, and that the LLM uses these chunks to generate a grounded answer." | M2, M3, M7 | ✅ retrieval metrics + cited answers in `data/eval/calibration_report.json`; formal report M7 |
| FR-2.4 | "The agent must not hallucinate answers that are not present in the knowledge base." | M3, M6 | 🟡 context-only prompt, evidence-first sufficiency check, citations validated against passages; M6 adds guardrail tests |

### FR-3 Confidence handling & escalation (§2.1.3)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-3.1 | "Your agent must be able to determine when it does not know the answer." Suggested approaches: retrieval-score threshold, LLM self-assessment, no-retrieval fallback, or "A combination of the above with a human-in-the-loop confirmation before escalating." | M3 | ✅ no-retrieval fallback + calibrated score threshold + LLM self-assessment |
| FR-3.2 | "When the agent determines it cannot answer, it must transition to the Ticket Creation flow described in Section 2.2." | M3, M5 | 🟡 conditional edge to `escalate`, which offers a ticket; ticket flow in M5 |

### FR-4 Ticket creation (§2.2)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-4.1 | "When the agent cannot resolve a query from the knowledge base, it must offer to create a support ticket on an external project-management platform." — **Chosen: Jira Cloud REST API.** | M4, M5 | 🟡 Jira service done (`src/smartdesk/tickets/`); offering a ticket after escalation in M5 |
| FR-4.2 | §2.2.1 "Before the agent creates a ticket, it must collect at minimum the following": **Employee Email** — "A unique identifier to link the ticket to the employee. The agent should ask for this explicitly if not already known." (Mandatory); **Issue Summary** — "A short, one-line title for the ticket" (Mandatory); **Issue Description** — "A detailed description. The agent should summarise the conversation so far. The employee should be able to add more details." (Mandatory); **Category / Label** — "Whether the issue falls under IT or HR. The agent should infer this from the conversation." (Recommended); **Priority** — "Low, Medium, High, or Critical. The agent may infer this or ask the employee." (Optional) | M5 | ⬜ |
| FR-4.3 | §2.2.2 "Before submitting the ticket, the agent must present a summary to the employee and ask for explicit confirmation. … This is a mandatory requirement — the agent must not create tickets silently." | M5 | ⬜ |
| FR-4.4 | §2.2.3 "After the ticket is successfully created, the agent must confirm this to the employee and provide the ticket ID or a link so that the employee can track it independently." | M4, M5 | 🟡 key + URL returned by `create_ticket`; shown to the employee in M5 |

### FR-5 Ticket status check (§2.3)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-5.1 | "An employee must be able to ask the agent about the status of a previously raised ticket." e.g. "What is the status of my ticket?" or "Did anyone look at my VPN issue?" | M5 | ⬜ |
| FR-5.2 | "The agent asks for the employee's email address (if not already known in the current session) to look up their tickets." | M5 | ⬜ |
| FR-5.3 | "The agent queries the external platform (Jira / Asana / Notion) using the API to fetch tickets associated with that email." | M4 | ✅ `list_tickets`: Jira search on the `sd-emp-` label ∪ SQLite mapping |
| FR-5.4 | "The agent presents the status (e.g., Open, In Progress, Resolved, Closed) along with any comments or updates from the support team." | M4, M5 | 🟡 `get_ticket` returns status and comments; presentation in M5 |
| FR-5.5 | "If the employee has multiple open tickets, the agent should list them briefly and let the employee choose which one they want details on." | M4, M5 | 🟡 listing done; choice in M5 |
| FR-5.6 | "If no tickets are found, the agent should say so clearly." | M4, M5 | 🟡 empty result handled; wording in M5 |

---

## 3. Data requirements (§3)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| DATA-1 | §3.3 Option C (Recommended): "The best knowledge bases combine real-world datasets with synthetic content." — **Chosen.** | M2 | ✅ 28 dataset-derived + 12 synthetic |
| DATA-2 | §3.2 step 6: "Deliberately leave some topics out (e.g., monitor flickering, office parking) so the agent correctly triggers escalation. This tests your confidence logic." | M2 | ✅ 7 gaps, `docs/data-sources.md` |
| DATA-3 | §3.2 step 7: "Store as Markdown files (one per policy area), a JSON array, or CSV. Include in your repository." | M2 | ✅ Markdown per policy area |
| DATA-4 | §3.4 KB evaluated on **Coverage** ("Does it span both IT and HR domains with at least 30–50 meaningful entries?"), **Realism** ("Do the policies read like something a real company would have? (Generic copy-paste scores lower.)"), **Diversity** ("Does it include simple factual, procedural how-to, and policy-interpretation questions?"), **Deliberate gaps** ("Are there topics intentionally left out so that your escalation logic is testable?"), **Structure** ("Is the data cleanly formatted and easy to ingest?") | M2 | ✅ |
| DATA-5 | §10 Q6: "adapting them to a fictional company (rename, tweak numbers, add categories) scores higher for 'Quality and breadth of KB content.'" | M2 | ✅ fact sheet + renaming |

---

## 4. Non-functional requirements (§4)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| NFR-1.1 | "The agent must maintain a polite, professional, and empathetic tone throughout." | M1 → M5 | 🟡 (canned replies) |
| NFR-1.2 | "The agent must handle greetings, small talk, and out-of-scope questions gracefully." | M1 → M5 | 🟡 |
| NFR-1.3 | "The agent must not hallucinate. If the KB does not contain the answer, the agent must acknowledge it." | M3, M6 | 🟡 escalation reply acknowledges the gap; gap questions escalated 11/11 dev, 10/10 held-out |
| NFR-2.1 | "The agent should remember context within a single session (e.g., do not re-ask for email)." | M5 | 🟡 (history kept per thread) |
| NFR-2.2 | "Multi-turn conversations must flow naturally without losing track of the topic." | M5 | 🟡 |
| NFR-3.1 | "If the external API is unreachable, the agent must inform the employee politely and suggest trying again later." | M4, M6 | ⬜ |
| NFR-3.2 | "If the LLM API call fails, the agent should have a retry mechanism or a graceful fallback." | M1 → M6 | 🟡 (client retries with backoff) |
| NFR-3.3 | "All API keys and secrets must be stored in environment variables — never hard-coded." | M1 | ✅ |
| NFR-4.1 | "Well-structured, modular, readable code with meaningful names." | all | 🟡 |
| NFR-4.2 | "README.md with setup instructions, env var list, and run commands." | M1 → M9 | 🟡 |
| NFR-4.3 | "Architecture diagram (hand-drawn, Mermaid, draw.io, or any format) showing components and data flow." | M9 | ⬜ |

---

## 5. Submission deliverables (§7)

| ID | Deliverable (verbatim) | Milestone | Status |
|---|---|---|---|
| DEL-1 | **GitHub Repository** — "Public or private repo (add evaluator as collaborator). Must include all source code, KB files, and configuration." | M9 | 🟡 |
| DEL-2 | **README.md** — "Setup instructions, env var list, how to populate the KB, how to run the agent, and a brief description of your approach." | M9 | 🟡 |
| DEL-3 | **Architecture Diagram** — "Visual diagram (image or Mermaid in README) showing components and data flow." | M9 | ⬜ |
| DEL-4 | **Demo Video / Screenshots** — "3–5 min screen recording or annotated screenshots showing all three flows: RAG answer, ticket creation, ticket status." | M9 | ⬜ |
| DEL-5 | **Knowledge Base Files** — "Raw documents / Q&A pairs / JSON / CSV used as your knowledge base. Must be included in the repo." | M2 | ✅ `data/kb/` |

---

## 6. Clarifications from the FAQ (§10) that affect grading

| Ref | Clarification (verbatim) | How SmartDesk handles it |
|---|---|---|
| Q2 | "Document the model name and hardware requirements in your README." | README lists `gpt-4o-mini` / `text-embedding-3-small` (hosted; no local hardware needs). |
| Q4 | "A minimum of 30. Quality and diversity matter more than quantity. Cover both IT and HR." | M2 target: 30–50 documents. |
| Q7 | "Mock the API calls … You'll receive partial marks but not full marks for live integration." | Live Jira integration (`tests/test_live_jira.py`); mocks only in unit tests (`tests/jira_fake.py`). |
| Q11 | "The evaluator will ask KB questions and non-KB questions. For non-KB questions, the agent must say it doesn't know or offer a ticket. Making up information loses marks." | Abstention + escalation (M3), gap questions in eval set (M2/M7). |
| Q13 | "Maintain a local mapping (JSON or SQLite) from email to ticket IDs. Save on creation, look up on status check." | SQLite `employee_tickets` (`src/smartdesk/tickets/store.py`), saved on creation, read on lookup (M4). |
| Q15 | "Consistently wrong routing affects your Orchestration & Routing score." | Live routing tests (`tests/test_live_openai.py`), eval set (M7). |
| Q16 | "Multi-turn support is required and evaluated under Session & Context Management." | SQLite checkpoints + session email lock (M5). |
| Q17 | "Creating tickets manually to test the status-check feature is expected." | Test tickets are created with `python -m smartdesk.tickets create` so they carry lookup labels; the support agent only updates them in Jira (`docs/demo-script.md`). |
| Q19 | "The agent identifies employees by email provided in conversation." | Email is a demo identifier, not authentication (documented, M5). |

---

## 7. Self-assessment rubric (§11)

Excellent (full marks) criteria, used as the target for each area:

| Criterion | "Excellent (Full)" (verbatim) | Covered by |
|---|---|---|
| RAG grounding | "All answers cite context, zero hallucination" | A4, FR-2.4 |
| Escalation logic | "Reliably detects unknown queries, offers tickets" | A5, FR-3 |
| Ticket creation | "All fields collected, confirmation shown, ID returned" | B1–B4 |
| Ticket status | "API fetch, multiple tickets handled, no-ticket case" | C1–C3 |
| Multi-turn context | "Smooth conversations, email remembered, context kept" | D2, NFR-2 |
| Knowledge base | "30+ entries, both domains, deliberate gaps, well-structured" | A1, DATA-1 – DATA-5 |
| Code & docs | "Clean, modular; thorough README; architecture diagram" | E1–E3 |
