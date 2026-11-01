# SmartDesk AI

An IT & HR help desk agent for the fictional company NovaTech Solutions. It
answers employee questions from a curated knowledge base (RAG), escalates what
it can't answer by raising a Jira ticket after explicit employee approval, and
reports the status of tickets an employee has already raised.

Built for the Interview Kickstart Applied Agentic AI capstone.

> **Status: Milestone 4 (Jira integration).** The agent answers IT and HR
> questions from the 40-document knowledge base with source citations, and
> escalates (offers a ticket) when the knowledge base does not contain the
> answer. A Jira ticket service (idempotent creation, lookup by employee email,
> status and comments) is implemented and tested against the live project. The
> conversational ticket and status flows with human approval arrive in
> Milestone 5; until then the agent replies to ticket intents with placeholders,
> and tickets can be created and inspected with `python -m smartdesk.tickets`.

## Tech stack

| Component | Choice |
|---|---|
| Orchestration | LangGraph |
| LLM | OpenAI `gpt-4o-mini` (configurable) via `langchain-openai` |
| Embeddings | OpenAI `text-embedding-3-small` (configurable) |
| Vector store | ChromaDB (local, persistent, cosine) |
| Ticketing | Jira Cloud REST API v3 (httpx) |
| Ticket mapping & idempotency | SQLite (checkpoints in M5) |
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

Then put your OpenAI key and Jira credentials in `.env`.

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
| `JIRA_BASE_URL` | for tickets | — | e.g. `https://your-site.atlassian.net` |
| `JIRA_EMAIL` | for tickets | — | Atlassian account email used for basic auth |
| `JIRA_API_TOKEN` | for tickets | — | Atlassian API token (id.atlassian.com → Security → API tokens) |
| `JIRA_PROJECT_KEY` | for tickets | — | Project that receives tickets, e.g. `KAN` |
| `JIRA_ISSUE_TYPE` | no | `Task` | Issue type for new tickets |
| `JIRA_TIMEOUT_SECONDS` | no | `10` | Per-request timeout |
| `JIRA_MAX_RETRIES` | no | `2` | Retries for reads (GET/search) only |
| `JIRA_MAX_CREATE_ATTEMPTS` | no | `2` | Create POSTs per call, each retry only after reconciling |
| `JIRA_RECONCILE_POLLS` / `JIRA_RECONCILE_DELAY_SECONDS` | no | `3` / `2` | Searches for a timed-out create |
| `SMARTDESK_DB_PATH` | no | `data/smartdesk.db` | SQLite ticket mapping and idempotency (git-ignored) |

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

## Jira tickets

`src/smartdesk/tickets/` is a self-contained ticket service. The LangGraph
workflow (M5) depends only on its `TicketService` interface:

| Method | Behaviour |
|---|---|
| `create_ticket(draft, op_id)` | Creates a Jira issue at most once per `op_id`; returns the real key and `…/browse/KEY` URL |
| `list_tickets(email)` | All of the employee's tickets, most recently updated first; `[]` when there are none |
| `get_ticket(email, key)` | Status, priority, description and support-team comments; `None` if the key does not exist **or belongs to another email** |

A `TicketDraft` holds the collected fields: employee email (validated,
trimmed, lower-cased), a one-line summary, a description, the IT/HR category
and an optional priority (Low/Medium/High/Critical; Critical maps to Jira's
Highest).

### How tickets are linked to employees

Every issue SmartDesk creates carries:

- **Description:** a header with `Employee email: …`, the category and
  "Raised via SmartDesk AI", followed by the employee's description, so the
  support team sees who raised it.
- **Labels:** `smartdesk`, `sd-cat-it` / `sd-cat-hr`,
  `sd-emp-<first 16 hex of sha256(email)>` and `sd-op-<first 32 hex of op_id>`.

Lookups combine two sources. The local SQLite table `employee_tickets` maps
email → ticket key (saved on creation), and a Jira search on the `sd-emp-`
label finds tickets the local file does not know (they are written back).
Jira is the source of truth for status and comments, and tickets deleted in
Jira are dropped from the result. SQLite also covers the few seconds before a
new issue appears in Jira's search index.

**The `sd-emp-` label is pseudonymisation, not anonymisation.** It keeps the
address out of label pickers and filters, but it is an unsalted hash: anyone
who can see the label and guess candidate addresses can confirm a match by
hashing them (a dictionary attack). It is deliberately unsalted so the same
email always maps to the same label on any machine without a shared secret,
and the plain address is in the description for the support team anyway.

Tickets created by hand in the Jira UI have no `sd-emp-` label, so status
lookups do not find them. Create test tickets through SmartDesk or the CLI
below; see [`docs/demo-script.md`](docs/demo-script.md).

### Duplicate prevention and timeout reconciliation

`derive_op_id(session_id, draft)` is a SHA-256 of the session id (the
LangGraph thread id from M5) and the normalised draft. The same approved
draft submitted twice in a session (a double click, a node re-run after
resume) has the same op id. An edited draft or a new session gets a new one.

SQLite table `ticket_ops` tracks each op as `pending`, `unknown`, `created`
or `failed`, and the op id travels to Jira as the `sd-op-` label:

```
op created                   -> return the existing ticket, no Jira call
op pending, recent           -> another submission is in flight: report "being created"
op pending (stale) / unknown -> reconcile first
op new / failed              -> claim it (BEGIN IMMEDIATE), then POST

POST /issue
  201                                    -> created; save the email mapping
  4xx, connection refused / timed out    -> failed (nothing created; a later retry is safe)
  read timeout, dropped connection, 5xx  -> unknown: the issue may exist
     reconcile: search labels = "sd-op-…", up to 3 polls 2 s apart
                (Jira search is eventually consistent)
       found -> created (the oldest wins if several match)
       none  -> POST again, at most JIRA_MAX_CREATE_ATTEMPTS per call
  still unknown -> TicketCreationUncertain; the next call reconciles before posting
```

A POST is never repeated without first searching for its op label, and never
sent for an op that is already `created`. Reads (GET, search) are idempotent,
so they retry up to `JIRA_MAX_RETRIES` times on timeouts, 429 and 5xx with
exponential backoff (0.5 s, 1 s, …), or the server's `Retry-After` on 429
(capped at 30 s).

**Remaining risk:** if an issue was created but is still missing from search
after all polls, a retry can create a second one. Both carry the same
`sd-op-` label, and later reconciliation always picks the oldest.

### Ticket CLI

```powershell
python -m smartdesk.tickets create --email jane.doe@novatech.example --category IT `
    --summary "Monitor flickers on dock" --description "Flickers when docked." --priority Medium
python -m smartdesk.tickets list --email jane.doe@novatech.example
python -m smartdesk.tickets show KAN-12 --email jane.doe@novatech.example
```

`create` prints the ticket and asks for confirmation before sending anything.

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
`SMARTDESK_LIVE_TESTS=1`. Tests marked `jira_live` need both
`SMARTDESK_LIVE_TESTS=1` and all four `JIRA_*` connection variables. Each run
creates one ticket for an `@example.com` test address, labelled
`sd-live-test`, and deletes it afterwards. If the account may not delete
issues, the ticket is moved to Done and keeps its `sd-live-test` label for
manual clean-up. Unit tests mock Jira with an in-memory fake
(`tests/jira_fake.py`) served through `httpx.MockTransport`.

```powershell
$env:SMARTDESK_LIVE_TESTS = "1"; pytest -m jira_live   # live Jira only
```

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
  tickets/           Jira adapter, SQLite store, idempotent ticket service, ticket CLI
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
  demo-script.md           demo data rules and ticket walkthrough
  data-sources.md          datasets, licences, transformations, deliberate gaps
```
