# SmartDesk AI

An IT & HR help desk agent for the fictional company NovaTech Solutions. It
answers employee questions from a curated knowledge base (RAG), escalates what
it can't answer by raising a Jira ticket after explicit employee approval, and
reports the status of tickets an employee has already raised.

Built for the Interview Kickstart Applied Agentic AI capstone.

> **Status: Milestone 2 (knowledge base).** Intent routing works end to end
> with the real LLM, and the 40-document knowledge base is generated and
> indexed in ChromaDB. The agent's answers, ticket creation and ticket status
> still reply with placeholders until Milestones 3–5.

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

The resulting index has 412 chunks: 40 overview chunks (median 54 tokens),
171 section chunks (median 108, max 376) and 201 FAQ chunks (median 55). No
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

## Run

```powershell
python -m smartdesk        # interactive CLI; prints the detected intent for each message
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
  kb/                KB catalogue, fact sheet, generation (Step A), chunking,
                     ChromaDB ingestion (Step B) and retrieval evaluation
  __main__.py        CLI entry point
data/
  kb/                40 committed KB documents (Markdown + YAML front matter)
  eval/              labelled evaluation set (never indexed)
  kb_generation_report.json   statistics from the last generation run
tests/               pytest suite
docs/
  rubric-traceability.md   spec requirements -> implementation and evidence
  data-sources.md          datasets, licences, transformations, deliberate gaps
```
