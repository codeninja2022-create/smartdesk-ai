# Milestone 3 plan — RAG

> **Reconstructed after implementation from repo history; not the original pre-implementation plan.**
> Sources: `CLAUDE.md` (Milestone 3), commit `5b00875` (2026-11-01), README "Answering questions (RAG) and escalation".

## Scope (from `CLAUDE.md`)

- Semantic retrieval from ChromaDB, IT/HR-aware.
- Grounded answers with source citations; never invent policies or citations.
- Insufficient-evidence detection, honest abstention and escalation.
- Similarity scores are not calibrated probabilities: calibrate the abstention threshold on the labelled set.
- Dense retrieval first; hybrid search and re-ranking are optional.

## Delivered (commit `5b00875`)

| Item | Implementation |
|---|---|
| Retrieval | Dense ChromaDB search with an IT/HR domain filter that falls back to the whole KB; the router also returns the domain and a standalone follow-up query (the first turn is searched verbatim) |
| Answering | Context-only prompt, evidence-first sufficiency check, passages delimited and treated as untrusted; citations rebuilt from chunk metadata and validated; an answer without a valid citation escalates |
| Escalation | No results, top similarity below 0.35 (calibrated on dev), or the LLM's insufficiency verdict → acknowledge the gap and offer an IT/HR ticket |
| Calibration | `python -m smartdesk.rag.calibrate`: dev (63) and held-out (21, never tuned on) reported separately |
| KB | `pay-tax-declaration` covers the spec's "tax declaration" wording; re-ingested (413 chunks) |

## Verification (as recorded in the commit)

- End-to-end correct outcomes: dev 63/63, held-out 21/21.
- Tests: 123 unit and 10 live passing.

## Deferred

Ticket creation after escalation (M4, M5); injection hardening tests (M6); formal evaluation report (M7).
