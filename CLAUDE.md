# SmartDesk AI — Claude Code Project Instructions

## Objective

Build SmartDesk AI, an IT/HR help desk assistant, for the Interview Kickstart Applied Agentic AI capstone.

Read `docs/capstone-spec.pdf` before implementation. The official PDF is the source of truth for requirements and grading.

Prioritize a reliable, working end-to-end application over unnecessary features. Target completion: 10–14 days.

Implement one milestone at a time and stop for my approval.

## Technology stack

- Python 3.12
- LangGraph for agent orchestration
- OpenAI via `langchain-openai`
- IK-provided `OPENAI_API_KEY`
- Default LLM: `gpt-4o-mini`
- Embeddings: `text-embedding-3-small`
- Hugging Face for public IT/HR datasets
- ChromaDB for vector storage
- Jira Cloud REST API for tickets
- SQLite for checkpoints and ticket mappings
- Langfuse for observability
- Chainlit for the user interface
- pytest for testing

Keep model names configurable. Verify model access using the IK key before implementation. If a configured model is unavailable, report it and ask before substituting another model.

Use Claude Code as the development assistant, but OpenAI as SmartDesk's runtime LLM.

## Milestone 1 — Foundation

1. Read the official capstone PDF.
2. Create a rubric traceability document using the PDF's exact requirements.
3. Inspect the existing repository.
4. Create the project structure and configuration.
5. Implement a minimal LangGraph workflow.
6. Configure OpenAI integration.
7. Integrate Langfuse tracing with sensitive-data redaction.
8. Add initial unit tests.

Keep API keys in `.env`, never in source code or Git.

Stop after M1 and report results.

## Milestone 2 — Knowledge base and ingestion

Follow Section 3 of the capstone PDF.

Investigate the recommended Hugging Face datasets:

- `strova-ai/hr-policies-qa-dataset`
- `Console-AI/IT-helpdesk-synthetic-tickets`

Verify availability, licensing, and schema before use.

Combine curated dataset content with LLM-generated synthetic knowledge documents.

Transform IT ticket records into troubleshooting articles rather than indexing raw tickets.

Transform HR data into coherent fictional-company policies and FAQs.

Generate and save **30–50 distinct IT/HR knowledge documents** in `data/kb/`.

### Deliberate KB gaps

Intentionally leave out a documented list of realistic IT/HR topics (for example: monitor flickering, office parking) so escalation can be tested.

Record the gap list in `docs/data-sources.md`. Do not generate KB content for these topics.

### Step A — One-time KB generation (separate command)

A separate, explicitly invoked command that:

1. Downloads and validates datasets.
2. Cleans, transforms, and deduplicates records.
3. Generates additional synthetic documents.
4. Saves actual curated KB documents to `data/kb/`.
5. Adds document IDs, categories, subcategories, and provenance metadata.

Generated documents are committed to the repository. This command is not part of routine ingestion and must not run automatically; re-running it requires explicit intent because LLM output is non-deterministic.

### Step B — Repeatable ChromaDB ingestion

A re-runnable command that reads only the committed files in `data/kb/` and:

1. Chunks documents.
2. Generates OpenAI embeddings.
3. Upserts into ChromaDB using stable IDs.
4. Supports rebuilding the index without regenerating documents.
5. Reports counts, failures, and sample retrieval results.

### Chunking rationale

Document the chosen chunking strategy (unit, size, overlap, how Q&A pairs vs. long policy documents are handled) and its justification in the README.

### Labeled evaluation set

Create a small labeled evaluation set in `data/eval/`, kept separate from `data/kb/` and never indexed. Include:

- Answerable questions, each with its expected source document ID(s)
- Gap questions targeting the deliberate KB gaps (expected: escalate)
- Out-of-scope questions
- Greetings / small talk

Use it to verify retrieval in M2, calibrate abstention in M3, and evaluate in M7.

## Milestone 3 — RAG

Implement:

- Semantic retrieval from ChromaDB
- IT/HR-aware retrieval
- Grounded answers with source citations
- Insufficient-evidence detection
- Honest abstention
- Escalation when the KB cannot answer

Do not invent company policies or citations.

Do not treat similarity scores as calibrated probabilities. Calibrate abstention thresholds against the labeled evaluation set.

Start with dense retrieval. Hybrid search and reranking are optional enhancements.

## Milestone 4 — Jira integration

Implement a modular Jira service for:

- Creating tickets
- Retrieving ticket details
- Looking up tickets associated with an employee email
- Retrieving status and comments
- Handling multiple tickets and no-ticket cases

Collect employee email, summary, description, and IT/HR category.

Return real ticket IDs and URLs.

Add SQLite mappings where needed.

Prevent duplicate ticket creation using a stable operation ID, SQLite status, and Jira labels.

On ambiguous API timeouts, reconcile before retrying. Never blindly repeat ticket creation.

Live Jira integration tests must be marked (e.g. `@pytest.mark.jira_live`) and skipped automatically when Jira credentials are not configured.

## Milestone 5 — LangGraph orchestration and HITL

Implement a single-agent LangGraph workflow supporting:

- Knowledge questions
- Ticket creation
- Ticket status checks
- Greetings and out-of-scope requests
- Multi-turn conversation
- Intent changes and clarification

Use LangGraph `interrupt()` for human approval before Jira ticket creation.

Show the complete ticket summary and allow approval, editing, or cancellation.

Never create a ticket without explicit approval of its final details.

Use SQLite-backed checkpoints.

Treat employee email as a demo identifier, not verified authentication. Document this limitation.

### Session email locking

- Validate and normalize the email when first provided.
- Lock it for the session once set.
- Do not allow switching to a different email within the same session; a different email requires a new session.
- Ticket status lookups return only tickets associated with the session email.

## Milestone 6 — Guardrails and reliability

Implement and test:

- Input validation
- Prompt-injection resistance
- Grounded-answer enforcement
- Tool argument validation
- Approval bypass prevention
- Session email-switch prevention
- API timeouts and bounded retries
- LLM call retries with backoff, and a safe fallback (a second configured model or a safe canned response) when retries are exhausted
- Duplicate submission handling
- Secret and sensitive-data protection
- Graceful error responses

Treat retrieved documents as untrusted content.

## Milestone 7 — Testing and evaluation

Test the mandatory capstone requirements:

- KB relevance and coverage
- Retrieval quality
- Grounded answers
- Escalation
- Intent routing
- Multi-turn behavior
- Jira ticket creation
- Ticket status retrieval
- HITL approval
- Error handling

Use pytest and practical test cases, driven by the labeled evaluation set.

If time permits, measure and report:

- Recall@5 on answerable questions
- Escalation precision and recall on gap vs. answerable questions

Record actual results in `docs/evaluation-report.md`.

Formal Ragas/DeepEval evaluation is optional bonus work, not mandatory.

Use Langfuse to capture useful token, latency, cost, and failure metrics when available.

## Milestone 8 — Chainlit UI

Build a simple conversational UI supporting:

- IT/HR questions
- Source citations
- Ticket approval
- Ticket creation confirmation
- Ticket status checking
- Error handling

Do not overengineer the interface.

## Milestone 9 — Final submission

Prepare:

- README and setup instructions (including chunking rationale)
- Architecture diagram
- Rubric traceability
- Dataset provenance
- Evaluation report
- Demo script
- 3–5 minute demo recording (or annotated screenshots) showing all three flows: RAG answer, ticket creation, ticket status
- Tests
- Working end-to-end demonstration

Demonstrate RAG, escalation, HITL approval, Jira creation, and ticket status.

## Engineering rules

- Prefer simple, modular, typed Python code.
- Use environment-based configuration.
- Mock external APIs in unit tests.
- Never fabricate test results or API responses.
- Do not commit credentials or the confidential capstone PDF.
- Do not add multi-agent architecture, advanced memory, hybrid search, or deployment complexity without asking.
- Do not change agreed architectural decisions without discussing them first.

## Working agreement

Implement one milestone at a time.

After each milestone, provide a concise report covering:

1. Files created or modified.
2. Tests run and results.
3. Capstone requirements satisfied.
4. Outstanding issues.
5. Proposed next step.

Stop and wait for approval before starting the next milestone.
