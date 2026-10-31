# SmartDesk AI

An IT & HR help desk agent for the fictional company NovaTech Solutions. It
answers employee questions from a curated knowledge base (RAG), escalates what
it can't answer by raising a Jira ticket after explicit employee approval, and
reports the status of tickets an employee has already raised.

Built for the Interview Kickstart Applied Agentic AI capstone.

> **Status: Milestone 1 (foundation).** Intent routing works end to end with
> the real LLM. Knowledge-base answers, ticket creation and ticket status reply
> with placeholders until Milestones 3–5.

## Tech stack

| Component | Choice |
|---|---|
| Orchestration | LangGraph |
| LLM | OpenAI `gpt-4o-mini` (configurable) via `langchain-openai` |
| Embeddings | OpenAI `text-embedding-3-small` (configurable) |
| Vector store | ChromaDB *(M2)* |
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
| `LANGFUSE_HOST` | no | `https://cloud.langfuse.com` | Langfuse server |

Secrets are only read from the environment. `.env` is git-ignored.

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
  __main__.py        CLI entry point
tests/               pytest suite
docs/
  rubric-traceability.md   spec requirements -> implementation and evidence
```
