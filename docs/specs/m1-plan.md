# Milestone 1 plan — Foundation

> **Reconstructed after implementation from repo history; not the original pre-implementation plan.**
> Sources: `CLAUDE.md` (Milestone 1), commit `1e43dce` (2026-10-30), and the code it added.

## Scope (from `CLAUDE.md`)

1. Read the official capstone PDF.
2. Create a rubric traceability document using the PDF's exact requirements.
3. Inspect the existing repository.
4. Create the project structure and configuration.
5. Implement a minimal LangGraph workflow.
6. Configure OpenAI integration.
7. Integrate Langfuse tracing with sensitive-data redaction.
8. Add initial unit tests.

Constraint: API keys only in `.env`, never in source or Git.

## Delivered (commit `1e43dce`)

| Item | Implementation |
|---|---|
| Configuration | `config.py`: environment-based settings (pydantic-settings), secrets as `SecretStr`, configurable model names |
| OpenAI | `llm.py`: chat and embedding factories with request timeouts and client retries with backoff |
| Workflow | Minimal LangGraph graph: LLM intent classification routed to greeting, knowledge, ticket, status and out-of-scope nodes |
| Tracing | `observability.py`: optional Langfuse callbacks; `redaction.py`: mask for secrets and PII |
| Entry point | `python -m smartdesk` |
| Traceability | `docs/rubric-traceability.md`, initial README |
| Hygiene | Confidential capstone PDF untracked; `.env` ignored (fixed in `cb24977`) |

## Verification

Unit tests with mocked APIs, plus opt-in live OpenAI tests (gated on
`SMARTDESK_LIVE_TESTS=1`). The commit does not record the test count.

## Deferred

Knowledge base (M2), RAG answers (M3), Jira (M4), HITL orchestration (M5).
