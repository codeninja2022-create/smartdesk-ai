# Rubric Traceability

Maps every graded requirement in the official capstone specification
(*SmartDesk AI — An Intelligent IT & HR Operations Agent*, Interview Kickstart
Applied Agentic AI Program) to where it is implemented and how it is verified.

- Quoted text is copied verbatim from the specification. Section numbers (§)
  refer to the specification.
- **Milestone** is the planned SmartDesk milestone (see `CLAUDE.md`).
- **Evidence** points to code, tests and docs once they exist.
- **Status:** ✅ done · 🟡 partial / foundation only · ⬜ not started.

Last updated: Milestone 6.

---

## 1. Marking scheme (§6, 100 marks)

### A. Knowledge Base & RAG Pipeline — 25 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| A1 | Quality and breadth of KB content | 5 | FR-1.1 – FR-1.4, §3.4 | M2 | `data/kb/` (40 docs), `docs/data-sources.md`, `tests/test_kb_data.py` | ✅ |
| A2 | Chunking strategy and justification | 5 | FR-2.1 | M2 | README "Chunking strategy", `src/smartdesk/kb/chunking.py`, `tests/test_kb_chunking.py` | ✅ |
| A3 | Retrieval quality — relevant results for test queries | 5 | FR-2.2, FR-2.3 | M2, M3, M7 | `src/smartdesk/rag/retriever.py`, `tests/test_rag_retriever.py`, `python -m smartdesk.rag.calibrate` (dev Hit@1 0.976 / Recall@5 1.000; held-out Hit@1 0.857 / Recall@5 1.000); report in M7 | 🟡 |
| A4 | LLM grounding — no hallucination | 5 | FR-2.4, NFR-1.3 | M3, M6, M7 | `src/smartdesk/rag/answer.py`, `tests/test_rag_answer.py`, `tests/test_workflow.py`; answers cite an expected doc 41/41 dev, 7/7 held-out (`data/eval/calibration_report.json`); M6 injection hardening: invented citations refused, passage delimiters stripped (`tests/test_guardrails.py`, live `test_live_instructions_inside_a_kb_passage_are_not_followed`); M7 report pending | 🟡 |
| A5 | Confidence / escalation logic | 5 | FR-3.1, FR-3.2 | M3, M7 | threshold 0.35 + LLM sufficiency check, `python -m smartdesk.rag.calibrate` (escalation precision/recall 1.000/1.000 on dev and on held-out), README "Calibrating abstention"; ticket hand-off in M5 | 🟡 |

### B. Ticket Creation (Write Operation) — 20 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| B1 | Successful external API integration | 5 | FR-4.1 | M4 | Jira Cloud REST v3 service `src/smartdesk/tickets/`; `tests/test_live_jira.py` (create, idempotent re-submit, lookup, ownership; passes against project KAN); mocked `tests/test_tickets_*.py` | ✅ |
| B2 | All mandatory fields collected | 5 | FR-4.2 | M5 | Slot-filling in `graph/tickets.py` (email, summary, description, inferred category, optional priority): `test_happy_path_collects_fields_then_creates_only_after_approval`, `test_category_is_inferred_from_the_conversation`, `test_unknown_category_is_asked_for`, live `test_live_escalation_offer_to_reviewed_ticket` | ✅ |
| B3 | Human-in-the-loop confirmation | 5 | FR-4.3 | M5 | `interrupt()` in `review_ticket`, approval bound to the draft's op_id: `test_structured_edit_changes_the_op_id_and_invalidates_the_old_approval`, `test_cancel_at_review_creates_nothing`, `test_new_input_while_paused_never_creates_a_ticket`, `test_submit_refuses_a_draft_without_a_matching_approval` | ✅ |
| B4 | Post-creation feedback with ticket ID/link | 5 | FR-4.4 | M4, M5 | Chat confirmation with key and URL (`test_happy_path_collects_fields_then_creates_only_after_approval`), duplicate reported as existing (`test_same_draft_again_in_the_session_reports_the_existing_ticket`); service: `test_create_ticket_returns_real_key_and_url`, live Jira test | ✅ |

### C. Ticket Status Check (Read Operation) — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| C1 | Status retrieval via API | 5 | FR-5.1 – FR-5.4 | M4 | `graph/status.py` presents status, last update, link and support comments: `test_single_ticket_shows_status_link_and_support_comments`, `test_asks_for_email_then_looks_up_tickets`; service: `test_get_ticket_returns_status_and_comments`, live Jira test | ✅ |
| C2 | Multiple-ticket handling (listing & selection) | 5 | FR-5.5 | M4, M5 | Numbered list (open first) and selection by number, key, ordinal or description: `test_multiple_tickets_are_listed_open_first_and_selected_by_number`, `test_ticket_can_be_chosen_by_key_or_position`, `test_a_reference_to_one_ticket_is_resolved_without_listing`, `test_invalid_choice_lists_the_tickets_again` | ✅ |
| C3 | Graceful handling when no tickets found | 5 | FR-5.6 | M4, M5 | `test_no_tickets_says_so_and_offers_a_ticket`, `test_ticket_key_in_the_message_is_looked_up_for_the_session_email_only`, `test_lookup_errors_get_a_clear_message`; service: `test_no_tickets_returns_empty_list` | ✅ |

### D. Agent Orchestration & Routing — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| D1 | Correct intent detection and routing | 5 | §1.2, §5 step 15 | M1 → M5 | Flow-aware router in `graph/workflow.py`: `tests/test_workflow.py`, `tests/test_ticket_flow.py`, `tests/test_status_flow.py`, live `test_live_intent_classification`, `test_live_flow_aware_routing` | ✅ |
| D2 | Smooth multi-turn conversations | 5 | NFR-2.1, NFR-2.2, §10 Q16 | M5 | SQLite checkpoints, email lock, intent switches with draft on hold: `test_knowledge_question_during_collection_puts_the_draft_on_hold`, `test_status_check_during_collection_keeps_the_draft`, `test_email_is_not_asked_again_later_in_the_session`, `test_pending_approval_survives_a_restart` | ✅ |
| D3 | Out-of-scope / ambiguous query handling | 5 | NFR-1.2 | M1 → M5 | `out_of_scope` and `unclear` → clarify (`tests/test_workflow.py`); measured on the eval set in M7 | 🟡 |

### E. Code Quality & Documentation — 15 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| E1 | Clean, modular, readable code | 5 | NFR-4.1 | all | `src/smartdesk/` | 🟡 |
| E2 | README with setup instructions | 5 | NFR-4.2, DEL-2 | M1 → M9 | `README.md` | 🟡 |
| E3 | Architecture diagram | 5 | NFR-4.3, DEL-3 | M9 | README (Mermaid) | ⬜ |

### F. Error Handling & Robustness — 10 marks

| ID | Sub-criterion (verbatim) | Marks | Spec requirement | Milestone | Evidence | Status |
|---|---|---|---|---|---|---|
| F1 | Graceful API failure degradation | 3 | NFR-3.1 | M4, M6 | Jira: distinct "not created" / "may exist" / lookup messages, draft kept (`test_jira_errors_get_their_own_message_and_keep_the_draft`, `test_lookup_errors_get_a_clear_message`); LLM: canned reply, next turn works (`test_without_a_fallback_model_the_employee_gets_a_canned_reply_and_the_next_turn_works`); any other failure: safe reply, draft kept (`test_unexpected_error_gets_a_safe_reply_and_only_its_type_is_logged`, `test_failure_while_handling_a_review_reply_never_creates_a_ticket`) | ✅ |
| F2 | Retry logic / LLM fallback | 3 | NFR-3.2 | M1 → M6 | `src/smartdesk/llm.py`: 30 s timeout, 2 retries with exponential backoff honouring `Retry-After`, optional fallback model, then a canned reply (D6.3, D6.4); `tests/test_m6_reliability.py` against a mocked OpenAI transport; Jira reads retry, creation reconciles (D4.7, D6.1) | ✅ |
| F3 | No hard-coded secrets | 2 | NFR-3.3 | M1 | `src/smartdesk/config.py`, `.env.example`, `.gitignore`, `src/smartdesk/redaction.py` | ✅ |
| F4 | Edge-case handling | 2 | NFR-1.2, FR-5.5, FR-5.6 | M6 | `tests/test_guardrails.py`: empty / over-long / invisible-character input, prompt injection, approval bypass, email-switch variants, malformed tool arguments; `tests/test_tickets_concurrency.py` (double submit); `tests/test_sessions.py` | ✅ |

### Bonus (§6.1, up to +10, total capped at 100)

| ID | Bonus item (verbatim) | Planned? | Notes |
|---|---|---|---|
| X1 | Hybrid search (dense + sparse + re-ranker) with demonstrable improvement. | Optional | Only with approval (CLAUDE.md); dense retrieval first. |
| X2 | Multi-agent architecture with specialised IT and HR sub-agents. | No | Single agent agreed; needs approval to change. |
| X3 | Evaluation pipeline (LangSmith, Ragas, DeepEval) with quantitative metrics. | Partial | Custom Recall@5 + escalation precision/recall (M7); Ragas/DeepEval optional. |
| X4 | User-facing deployment (Streamlit, Gradio, Chainlit, or web app). | Yes ✅ | Chainlit UI (M8): `chainlit run src/smartdesk/ui/app.py`; citations in side panels, Approve / Edit / Cancel buttons, ticket confirmation and status (D8.1–D8.6, `tests/test_ui_render.py`, `tests/test_async_session.py`, smoke check of all three flows in the M8 report). |
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
| FR-2.4 | "The agent must not hallucinate answers that are not present in the knowledge base." | M3, M6 | ✅ context-only prompt, evidence-first sufficiency check, citations validated against passages; injected passages cannot add sources (`test_instructions_in_a_kb_passage_cannot_add_passages_or_citations`) |

### FR-3 Confidence handling & escalation (§2.1.3)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-3.1 | "Your agent must be able to determine when it does not know the answer." Suggested approaches: retrieval-score threshold, LLM self-assessment, no-retrieval fallback, or "A combination of the above with a human-in-the-loop confirmation before escalating." | M3 | ✅ no-retrieval fallback + calibrated score threshold + LLM self-assessment |
| FR-3.2 | "When the agent determines it cannot answer, it must transition to the Ticket Creation flow described in Section 2.2." | M3, M5 | 🟡 conditional edge to `escalate`, which offers a ticket; ticket flow in M5 |

### FR-4 Ticket creation (§2.2)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-4.1 | "When the agent cannot resolve a query from the knowledge base, it must offer to create a support ticket on an external project-management platform." — **Chosen: Jira Cloud REST API.** | M4, M5 | ✅ escalation offers a ticket; "yes" starts it (`test_accepting_an_escalation_offer_starts_a_ticket_from_the_question`) |
| FR-4.2 | §2.2.1 "Before the agent creates a ticket, it must collect at minimum the following": **Employee Email** — "A unique identifier to link the ticket to the employee. The agent should ask for this explicitly if not already known." (Mandatory); **Issue Summary** — "A short, one-line title for the ticket" (Mandatory); **Issue Description** — "A detailed description. The agent should summarise the conversation so far. The employee should be able to add more details." (Mandatory); **Category / Label** — "Whether the issue falls under IT or HR. The agent should infer this from the conversation." (Recommended); **Priority** — "Low, Medium, High, or Critical. The agent may infer this or ask the employee." (Optional) | M5 | ✅ `graph/tickets.py` slot-filling (B2) |
| FR-4.3 | §2.2.2 "Before submitting the ticket, the agent must present a summary to the employee and ask for explicit confirmation. … This is a mandatory requirement — the agent must not create tickets silently." | M5 | ✅ `interrupt()` review with approve / edit / cancel (B3) |
| FR-4.4 | §2.2.3 "After the ticket is successfully created, the agent must confirm this to the employee and provide the ticket ID or a link so that the employee can track it independently." | M4, M5 | ✅ key + URL shown in chat (B4) |

### FR-5 Ticket status check (§2.3)

| ID | Requirement (verbatim) | Milestone | Status |
|---|---|---|---|
| FR-5.1 | "An employee must be able to ask the agent about the status of a previously raised ticket." e.g. "What is the status of my ticket?" or "Did anyone look at my VPN issue?" | M5 | ✅ `ticket_status` intent → `check_status` (C1) |
| FR-5.2 | "The agent asks for the employee's email address (if not already known in the current session) to look up their tickets." | M5 | ✅ asked once, then locked for the session (`test_asks_for_email_then_looks_up_tickets`, `test_email_is_not_asked_again_later_in_the_session`) |
| FR-5.3 | "The agent queries the external platform (Jira / Asana / Notion) using the API to fetch tickets associated with that email." | M4 | ✅ `list_tickets`: Jira search on the `sd-emp-` label ∪ SQLite mapping |
| FR-5.4 | "The agent presents the status (e.g., Open, In Progress, Resolved, Closed) along with any comments or updates from the support team." | M4, M5 | ✅ status + support comments presented (C1) |
| FR-5.5 | "If the employee has multiple open tickets, the agent should list them briefly and let the employee choose which one they want details on." | M4, M5 | ✅ list and choose (C2) |
| FR-5.6 | "If no tickets are found, the agent should say so clearly." | M4, M5 | ✅ clear no-ticket message with a ticket offer (C3) |

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
| NFR-2.1 | "The agent should remember context within a single session (e.g., do not re-ask for email)." | M5 | ✅ SQLite checkpoints per session; email not re-asked (D2) |
| NFR-2.2 | "Multi-turn conversations must flow naturally without losing track of the topic." | M5 | ✅ intent switches keep the ticket draft on hold (D2) |
| NFR-3.1 | "If the external API is unreachable, the agent must inform the employee politely and suggest trying again later." | M4, M6 | ✅ Jira and LLM outages get polite try-again replies (F1) |
| NFR-3.2 | "If the LLM API call fails, the agent should have a retry mechanism or a graceful fallback." | M1 → M6 | ✅ retries with backoff, optional fallback model, canned reply (F2) |
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
