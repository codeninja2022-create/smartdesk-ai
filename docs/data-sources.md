# Data Sources and Provenance

SmartDesk's knowledge base follows **Option C** of the capstone specification
(§3.3): real public datasets combined with LLM-generated content for the
fictional company **NovaTech Solutions** (500-employee B2B SaaS, Bengaluru).

## Public datasets

| | HR policy Q&A | IT helpdesk tickets |
|---|---|---|
| Dataset | [`strova-ai/hr-policies-qa-dataset`](https://huggingface.co/datasets/strova-ai/hr-policies-qa-dataset) | [`Console-AI/IT-helpdesk-synthetic-tickets`](https://huggingface.co/datasets/Console-AI/IT-helpdesk-synthetic-tickets) |
| Pinned revision | `83682448cb8afe6a6123583e722ecdf04fb20b40` | `165693849d955c6da4c00bc8be8e541afec0514e` |
| File | `dataset.jsonl` | `tickets.csv` |
| Licence | MIT | MIT |
| Access | public, not gated | public, not gated |
| Rows | 644 | 500 |
| Schema | `messages`: `system` / `user` / `assistant` turns | `id, subject, description, priority, category, createdAt, requesterEmail` |
| Coverage | strong: conduct, harassment (POSH), performance, remote work, anti-bribery. Weak or absent: leave entitlements, reimbursement, payroll, tax, equity, onboarding | Software 231, Account 71, Network 68, Security 42, Communication 24, Hardware 22, RemoteWork 20, other 22 |
| Caveats | answers are short (~230 chars) and generic; 85 mention another company ("Kreeda Labs") | **no resolution column**: problem reports only (the spec describes "resolutions", but the published file has none); contains requester emails |

Raw downloads are cached in `data/raw/` (git-ignored) and re-fetched from the
pinned revision when missing.

## Transformation pipeline (Step A, `python -m smartdesk.kb.generate --confirm`)

1. **Download and validate:** fetch each file at its pinned revision and check
   the expected schema (message roles; CSV columns).
2. **Clean:** remove email addresses and Slack-style emoji codes, strip
   `Re:` / `[Acme IT]` / `Ticket #…` subject prefixes, replace other company
   names with NovaTech Solutions, normalise whitespace. `requesterEmail` is
   never used.
3. **Deduplicate and filter:** drop empty records, exact duplicates (after
   normalisation) and any record mentioning a deliberate-gap topic.
4. **Assign to topics:** embed records and the 40 topic briefs with
   `text-embedding-3-small`. Each record goes to its single most similar topic
   (minimum cosine similarity 0.40, at most 8 records per topic). Gap
   descriptions take part as pseudo-topics, so a record that is closest to a
   gap is dropped.
5. **Generate:** for each topic, `gpt-4o-mini` writes a structured article
   (summary, 3–7 sections, 4–7 FAQs) from the **company fact sheet**
   (`src/smartdesk/kb/company.py`) and the topic's source records. The records
   only show which questions and problems employees actually raise. All
   numbers, systems and contacts come from the fact sheet, so the 40 documents
   agree with one another. IT tickets therefore become troubleshooting
   articles, not indexed tickets.
6. **Validate:** a draft is rejected and regenerated (up to 3 attempts) if it
   mentions a gap topic, links to any URL that is not in the fact sheet, or
   has fewer than 250 words.
7. **Save:** `data/kb/<doc_id>.md` with YAML front matter: `doc_id`, `title`,
   `domain` (IT/HR), `category`, `subcategory`, and `provenance`
   (`source_type`, pinned `datasets`, `source_record_ids`, `generator_model`,
   `generated_at`). Run statistics go to `data/kb_generation_report.json`.

### Generation results (2026-10-31)

| | HR Q&A | IT tickets |
|---|---|---|
| Loaded | 644 | 500 |
| Dropped: duplicates | 0 | 0 |
| Dropped: gap keywords | 2 | 26 (mostly printer tickets) |
| Dropped: closest to a gap | 0 | 2 |
| Assigned to a topic | 72 | 128 |

- **40 documents, about 23,000 words:** 28 `dataset_derived` and 12
  `synthetic`.
- **Where synthetic documents were needed:** guest Wi-Fi, expense
  reimbursement, health insurance, learning budget, buddy programme,
  probation, benefits enrolment, tax declaration, salary structure, stock
  options and payslips. No dataset record reached the 0.40 similarity
  threshold for these topics.
- **Retries:** two first drafts were rejected for mentioning a gap topic, and
  both retries passed.
- **One manual re-run:** `it-vpn-setup` was regenerated with `--only` after a
  review found it linked to an external download page. That review is also
  where the "URLs must come from the fact sheet" validation rule came from.
- **One manual edit (Milestone 3):** `pay-tax-declaration` only used the term
  "investment declaration". As a result the agent could not answer "How do I
  submit my tax declaration?", one of the spec's example questions (§2.1.1).
  The title, overview, submission section and FAQs were edited by hand to use
  "tax declaration" and keep "investment declaration" as a synonym. The
  facts are unchanged and the edited document still passes `validate_body`.
  The topic brief in `catalog.py` and the fact sheet now use the same wording,
  so a regeneration keeps the term.

## Knowledge base contents

| Category | Documents |
|---|---|
| IT Support (18) | password reset, account lockout, MFA setup, VPN setup, VPN troubleshooting, software and licence requests, corporate Wi-Fi, guest Wi-Fi, email on mobile, Outlook and calendar, shared drives and SharePoint, remote desktop, slow network, application crashes, SSO and cloud app access, phishing and security incidents, Teams meetings and audio/video, data backup and recovery |
| HR Policies (12) | leave policy, public and floating holidays, hybrid/WFH policy, expense reimbursement, code of conduct, POSH and anti-harassment, anti-bribery and gifts, performance review cycle, grievance and whistleblower, health insurance and benefits, resignation and exit, learning budget |
| Onboarding (5) | first day, IT equipment allocation, buddy programme, probation, benefits enrolment |
| Payroll & Compensation (5) | pay-day schedule, tax declaration, salary structure, ESOP and vesting, payslips and corrections |

## Deliberate KB gaps

These realistic topics are **intentionally not covered**, so the agent's
escalation logic can be tested (spec §3.2 step 6, §3.4). Source records about
them are dropped, generated text that mentions them is rejected, and
`tests/test_kb_data.py` checks that no committed document mentions them.

| Gap id | Topic | Example question (in the eval set) |
|---|---|---|
| `monitor-flickering` | external monitor or laptop display flickering | "My monitor has been flickering for two days." |
| `office-parking` | car or bike parking, parking passes | "How do I get a parking pass for the office?" |
| `printers` | printers, printing, scanners, print queues | "The printer on the 3rd floor is not working." |
| `cafeteria` | cafeteria, canteen, meal coupons, snacks | "What time does the cafeteria open for lunch?" |
| `office-shuttle` | office shuttle, company cab or bus | "Is there an office shuttle from Whitefield?" |
| `relocation` | relocation assistance, moving allowance | "Is there a relocation allowance?" |
| `sabbatical` | sabbaticals, long career breaks | "Can I take a six-month sabbatical?" |

## Labelled evaluation sets

All items are hand-written. They live outside `data/kb/` and are never
indexed. There are two splits:

- **Dev** (`data/eval/eval_set.jsonl`) is used for calibration and prompt
  refinement.
- **Held-out** (`data/eval/heldout/eval_set.jsonl`) is never used for tuning.
  `tests/test_kb_data.py` checks that the two splits share no ids or
  questions.

| Category | Dev (63) | Held-out (21) | Expected behaviour |
|---|---|---|---|
| `answerable` | 41 (at least one per KB document) | 7 paraphrases | answer, citing `expected_doc_ids` |
| `gap` | 11 (every deliberate gap, with paraphrases) | 10: 7 deliberate gaps plus 3 `unplanned:` topics the KB does not cover | escalate (offer a ticket) |
| `out_of_scope` | 6 (includes a prompt-injection attempt) | 3 (two injection-style) | decline politely |
| `greeting` | 5 | 1 | greet |

`gap-11` ("book movers…") began as a held-out question. It exposed a routing
gap, and relocation was then added to the router's topic list. The question
was therefore moved to dev and replaced in held-out with a fresh relocation
question (`ho-13`), so no held-out item has influenced tuning.

Answerable questions are deliberately phrased differently from the documents'
own headings. One label was corrected after the first retrieval run: `ans-24`
originally asked whether freelancing is allowed, but no document answers that,
so an answer would have been a hallucination. It was replaced with a
conflict-of-interest question that the code of conduct does answer.
