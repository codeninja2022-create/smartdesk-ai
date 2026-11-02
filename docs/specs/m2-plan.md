# Milestone 2 plan — Knowledge base and ingestion

> **Reconstructed after implementation from repo history; not the original pre-implementation plan.**
> Sources: `CLAUDE.md` (Milestone 2), commit `f456ce6` (2026-11-01), `docs/data-sources.md`, README "Chunking strategy".

## Scope (from `CLAUDE.md`)

- Investigate `strova-ai/hr-policies-qa-dataset` and `Console-AI/IT-helpdesk-synthetic-tickets`; verify availability, licensing and schema.
- Combine curated dataset content with LLM-generated documents: IT tickets become troubleshooting articles, HR data becomes fictional-company policies and FAQs.
- 30–50 distinct documents in `data/kb/`, with deliberate, documented gaps.
- Step A: a separate, explicitly invoked generation command. Step B: a repeatable ChromaDB ingestion with stable IDs.
- Chunking rationale in the README; a labelled evaluation set in `data/eval/`, never indexed.

## Delivered (commit `f456ce6`)

| Item | Implementation |
|---|---|
| Step A | `python -m smartdesk.kb.generate --confirm`: download pinned HF datasets, clean, deduplicate, drop gap topics, assign records to 40 topics by embedding similarity, generate articles with `gpt-4o-mini` from a shared company fact sheet, validate and retry |
| KB | 40 committed documents in `data/kb/` with provenance front matter |
| Gaps | 7 deliberate gaps, listed in `docs/data-sources.md` |
| Step B | `python -m smartdesk.kb.ingest [--rebuild]`: structure-aware chunking (overview / section / FAQ, 400-token cap), stable chunk IDs, hash-based incremental upsert, stale-chunk deletion, reporting |
| Evaluation | Labelled eval set (62 items) and a retrieval evaluation |

## Verification (as recorded in the commit)

- Retrieval: Hit@1 0.976, Recall@5 1.000, MRR 0.988.
- Tests: 92 unit and 7 live passing.

## Deferred

Answer generation, abstention calibration and escalation (M3).
