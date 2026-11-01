# SmartDesk AI

An IT & HR help desk agent for the fictional company NovaTech Solutions. It
answers employee questions from a curated knowledge base (RAG), escalates what
it can't answer by raising a Jira ticket after explicit employee approval, and
reports the status of tickets an employee has already raised.

Built for the Interview Kickstart Applied Agentic AI capstone.

> **Status: Milestone 3 (RAG).** The agent answers IT and HR questions from
> the 40-document knowledge base with source citations, and escalates (offers
> a ticket) when the knowledge base does not contain the answer. Ticket
> creation and ticket status still reply with placeholders until Milestones 4–5.

## Tech stack

| Component | Choice |
|---|---|
| Orchestration | LangGraph |
| LLM | OpenAI `gpt-4o-mini` (configurable) via `langchain-openai` |
| Embeddings | OpenAI `text-embedding-3-small` (configurable) |
| Vector store | ChromaDB (local, persistent, cosine) |
| Ticketing | Jira Cloud REST API *(M4)* |
| Checkpoints & ticket mapping | SQLite *(M4–M5)* |
| Observability | Langfuse, with sensitive-data redaction |
| UI | Chainlit *(M8)* |
| Tests | pytest |

Both models are hosted by OpenAI, so there are no local GPU or hardware requirements.

## Setup

Requires **Python 3.12**.

```powershell
git clone https://github.com/codeninja2022-create/smartdesk-ai.git
cd smartdesk-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
Copy-Item .env.example .env           # macOS/Linux: cp .env.example .env
```

Then put your OpenAI key in `.env`.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI API key |
| `SMARTDESK_LLM_MODEL` | no | `gpt-4o-mini` | Chat model |
| `SMARTDESK_EMBEDDING_MODEL` | no | `text-embedding-3-small` | Embedding model |
| `SMARTDESK_LLM_TEMPERATURE` | no | `0` | Sampling temperature |
| `SMARTDESK_LLM_TIMEOUT_SECONDS` | no | `30` | Per-request timeout |
| `SMARTDESK_LLM_MAX_RETRIES` | no | `2` | Client retries with exponential backoff |
| `LANGFUSE_PUBLIC_KEY` | no | — | Langfuse tracing; disabled when blank |
| `LANGFUSE_SECRET_KEY` | no | — | Langfuse tracing; disabled when blank |
| `LANGFUSE_HOST` (or `LANGFUSE_BASE_URL`) | no | `https://cloud.langfuse.com` | Langfuse server |
| `SMARTDESK_KB_DIR` | no | `data/kb` | Committed KB documents |
| `SMARTDESK_CHROMA_DIR` | no | `data/chroma` | ChromaDB storage (git-ignored) |
| `SMARTDESK_CHROMA_COLLECTION` | no | `smartdesk_kb` | Collection name |
| `SMARTDESK_RAG_TOP_K` | no | `5` | Chunks retrieved per question |
| `SMARTDESK_RAG_MIN_SIMILARITY` | no | `0.35` | Abstention pre-filter (calibrated, see below) |

Secrets are only read from the environment. `.env` is git-ignored.

## Populate the knowledge base

The 40 KB documents are already committed in `data/kb/`, so a fresh clone
only needs to build the vector index:

```powershell
python -m smartdesk.kb.ingest              # chunk, embed and upsert into ChromaDB (re-runnable)
python -m smartdesk.kb.ingest --rebuild    # drop the collection and re-index everything
python -m smartdesk.kb.evaluate            # retrieval check against data/eval/eval_set.jsonl
```

Ingestion reads only `data/kb/`. It upserts under stable chunk ids, skips
chunks whose content hash is unchanged, deletes chunks that no longer exist,
and prints counts, failures and sample retrievals.

Regenerating the documents themselves is a separate, deliberate step. LLM
output is non-deterministic, so it refuses to run without `--confirm`:

```powershell
python -m smartdesk.kb.generate --confirm                     # rewrite all 40 documents
python -m smartdesk.kb.generate --confirm --only it-vpn-setup # rewrite selected documents
```

See [`docs/data-sources.md`](docs/data-sources.md) for dataset provenance,
licences, the transformation pipeline and the list of deliberate KB gaps.

## Chunking strategy

| Decision | Choice |
|---|---|
| Unit | Document structure, not fixed-size windows. The opening summary is one *overview* chunk, each `##` section is one *section* chunk, and each FAQ question with its answer is one *faq* chunk. |
| Context header | Every chunk starts with `<document title> > <section>` (or `> FAQ`). |
| Size limit | 400 tokens (`cl100k_base`, the tokenizer of `text-embedding-3-*`). |
| Overlap | None between sections or FAQs. Only when a section exceeds the limit is it split at paragraph boundaries, carrying the previous paragraph (≤ 80 tokens) into the next part. |
| IDs | `<doc_id>#<type>-<heading-slug>`, plus `-p<n>` for split parts. Stable across runs, so re-ingestion upserts in place. |
| Metadata | `doc_id`, `title`, `domain`, `category`, `subcategory`, `section`, `chunk_type`, `source_type`, `tokens`, `content_hash`. |

The resulting index has 413 chunks: 40 overview chunks (median 54 tokens),
171 section chunks (median 108, max 376) and 202 FAQ chunks (median 55). No
current section reaches the 400-token limit, so no splits occur today.

**Why this approach:**

- **Q&A pairs vs. long policy documents.** Employees ask single questions,
  and a question embeds closest to a single Q&A pair, not a page of ten FAQs.
  Keeping each FAQ as its own chunk gives precise matches for factual
  questions ("How many sick leaves?"). Section chunks keep a whole procedure
  or policy clause together for how-to and interpretation questions, so
  numbered steps are never cut in half.
- **Section boundaries are semantic boundaries.** The generator writes one
  topic per section, so splitting there needs no overlap. Overlap would only
  duplicate text across chunks and crowd the top-k with near-identical hits.
- **Context headers** keep a chunk self-explanatory once it is separated from
  its document. For example, "Leave Policy > Sick Leave" disambiguates a bare
  "8 days per year". The headers also give the answer step the section name
  it needs for citations.
- **The 400-token cap** keeps each chunk focused on one idea, which helps
  embedding precision, while staying large enough for a complete procedure.
  Five chunks of this size fit comfortably in the answer prompt.
- **Measured result:** on the 41 answerable eval questions, document-level
  Hit@1 is 0.976, Recall@5 is 1.000 and MRR is 0.988
  (`python -m smartdesk.kb.evaluate`).

## Answering questions (RAG) and escalation

```
question -> router (intent, IT/HR domain, standalone query for follow-ups)
         -> retrieve top 5 chunks (domain-filtered; whole KB if the domain search is weak)
         -> no chunks, or top similarity < 0.35  -> escalate
         -> LLM: quote evidence, judge sufficiency, answer with [n] markers
         -> not sufficient, or no valid citation  -> escalate
         -> answer + "Sources:" list built from chunk metadata
```

- **Grounding.** The answer prompt allows only facts stated in the retrieved
  passages. The model must first quote its evidence, then decide whether it
  answers the question. That ordering reduced false "I don't know" verdicts.
- **Citations cannot be invented.** The LLM only returns passage numbers.
  SmartDesk maps them back to the chunk's document title, section and
  `doc_id`, drops numbers that do not match a passage, and escalates any
  answer left without a valid citation.
- **Retrieved text is untrusted.** Passages are wrapped in `<passage>`
  delimiters, with any look-alike tags inside them removed. The prompt treats
  them as data and ignores instructions found inside them.
- **Escalation.** The agent says it could not find the answer, does not
  guess, and offers to raise an IT or HR ticket. The ticket flow itself
  arrives in Milestones 4–5.
- **Follow-ups.** The first question is searched verbatim. On later turns the
  router's standalone rewrite is used, for example "what about on Mac?" after
  a VPN question.

### Calibrating abstention

```powershell
python -m smartdesk.rag.calibrate    # routing, retrieval and answering on the dev and held-out sets
```

Two evaluation splits are kept apart:

- **Dev** (`data/eval/eval_set.jsonl`, 63 questions) is used for calibration.
  The threshold sweep and recommendation come only from this split, and the
  prompts were refined against it.
- **Held-out** (`data/eval/heldout/eval_set.jsonl`, 21 questions) is **never
  used for tuning**. It holds paraphrases, deliberate gap questions, topics the
  KB happens not to cover (labelled `unplanned:<topic>`), injection-style
  out-of-scope messages and a greeting. It is scored once, at the configured
  threshold.

Similarity scores are ranking scores, not probabilities, and answerable and
gap questions overlap (dev: answerable top-1 0.40–0.75, gap 0.20–0.45;
held-out: answerable 0.43–0.65, gap 0.27–0.45). So the threshold is only a
cheap pre-filter, and the LLM's evidence-based sufficiency check makes the
final decision. The threshold is set to the lowest dev answerable top-1 score
(0.403) minus a 0.05 margin, which gives **0.35**.

Results at `min_similarity = 0.35`. "End-to-end" means what the employee
actually gets: routing first, then the RAG decision.

| | Dev (63) | Held-out (21) |
|---|---|---|
| Answerable → answered | 41/41 | 7/7 |
| Gap → escalated (offers a ticket) | 11/11 (6 by threshold, 5 by LLM check) | 10/10 (5 by threshold, 5 by LLM check) |
| Out of scope → declined | 6/6 | 3/3 |
| Greeting → greeted | 5/5 | 1/1 |
| Routing accuracy | 63/63 | 21/21 |
| Escalation precision / recall (positive = gap) | 1.000 / 1.000 | 1.000 / 1.000 |
| Answers citing an expected source document | 41/41 | 7/7 |
| Retrieval Hit@1 / Recall@5 / MRR (domain-aware) | 0.976 / 1.000 / 0.988 | 0.857 / 1.000 / 0.929 |

On dev, any threshold from 0.20 to 0.40 gives the same combined result.
Above 0.40 it starts escalating answerable questions. Per-question detail for
both splits, including every generated answer, is written to
`data/eval/calibration_report.json`.

**Known limitations:**

- **Small sets.** With 7 answerable and 10 gap items, the held-out results
  are indicative, not statistically strong. A perfect score here does not
  mean the agent never errs. The formal evaluation is in Milestone 7.
- **The threshold alone cannot separate gaps from answers.** One held-out gap
  (ho-02, Outlook password prompts, 0.45) scores above some answerable
  questions. It escalates only because of the LLM check, so both layers
  are needed.
- **Fixes made in this milestone, all on dev evidence:**
  - Ethics, office facilities and relocation were added to the router's
    topic list.
  - The search query is used verbatim on the first turn.
  - The answer prompt quotes its evidence before deciding.
  - `pay-tax-declaration` was edited to use the spec's wording "tax
    declaration" (see `docs/data-sources.md`).
  - The relocation question that exposed the routing gap ("book movers…")
    was moved from held-out to dev (`gap-11`) and replaced with a fresh
    relocation question, so held-out stays untouched by tuning.
- **Domain filter.** On both splits it neither helps nor hurts (identical
  metrics). It is kept so IT and HR content with similar wording does not
  compete, and the fallback to the whole KB means a wrong domain hint cannot
  by itself cause an escalation.

## Run

```powershell
python -m smartdesk        # interactive CLI; needs the index (python -m smartdesk.kb.ingest)
                           # prints intent, domain, top similarity and any escalation reason
```

## Tests

```powershell
pytest                                      # unit tests; all external APIs mocked
$env:SMARTDESK_LIVE_TESTS = "1"; pytest     # also run live OpenAI checks
```

Tests marked `openai_live` call the real OpenAI API and are skipped unless
`SMARTDESK_LIVE_TESTS=1`. Tests marked `jira_live` (from Milestone 4) are
skipped unless Jira credentials are configured.

## Observability and redaction

When Langfuse keys are set, every LangGraph/LangChain run is traced through the
Langfuse callback handler. The Langfuse client is created with a mask function
(`src/smartdesk/redaction.py`) that strips API keys, Langfuse and Jira tokens,
bearer tokens, `password=`/`token=` values, email addresses, phone numbers and
card numbers from trace inputs, outputs and metadata before they leave the process.

## Project layout

```
src/smartdesk/
  config.py          environment-based settings (secrets as SecretStr)
  llm.py             OpenAI chat + embedding factories
  observability.py   Langfuse client and callbacks
  redaction.py       secret / PII masking
  graph/             LangGraph state, prompts and workflow
  rag/               retrieval, grounded answers + citations, abstention calibration
  kb/                KB catalogue, fact sheet, generation (Step A), chunking,
                     ChromaDB ingestion (Step B) and retrieval evaluation
  __main__.py        CLI entry point
data/
  kb/                40 committed KB documents (Markdown + YAML front matter)
  eval/              labelled evaluation set (never indexed) and calibration report
  kb_generation_report.json   statistics from the last generation run
tests/               pytest suite
docs/
  rubric-traceability.md   spec requirements -> implementation and evidence
  data-sources.md          datasets, licences, transformations, deliberate gaps
```
