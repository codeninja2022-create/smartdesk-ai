"""Download, validate and clean the public Hugging Face datasets.

Both datasets are pinned to a commit so a re-run sees exactly the same records.
"""

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from smartdesk.kb.catalog import find_gap_mentions
from smartdesk.kb.company import COMPANY_NAME


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    repo_id: str
    revision: str
    filename: str
    licence: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{self.repo_id}/resolve/{self.revision}/{self.filename}"

    @property
    def pinned_id(self) -> str:
        return f"{self.repo_id}@{self.revision[:12]}"


HR_QA = DatasetSpec(
    key="hr_qa",
    repo_id="strova-ai/hr-policies-qa-dataset",
    revision="83682448cb8afe6a6123583e722ecdf04fb20b40",
    filename="dataset.jsonl",
    licence="MIT",
)
IT_TICKETS = DatasetSpec(
    key="it_tickets",
    repo_id="Console-AI/IT-helpdesk-synthetic-tickets",
    revision="165693849d955c6da4c00bc8be8e541afec0514e",
    filename="tickets.csv",
    licence="MIT",
)
DATASETS = {spec.key: spec for spec in (HR_QA, IT_TICKETS)}

IT_TICKET_COLUMNS = {"id", "subject", "description", "priority", "category", "createdAt", "requesterEmail"}


@dataclass(frozen=True)
class SourceRecord:
    record_id: str
    dataset: str  # DatasetSpec.key
    text: str  # cleaned text used for matching and as generation context


@dataclass
class CleaningReport:
    loaded: int = 0
    empty: int = 0
    duplicates: int = 0
    gap_topic: int = 0

    @property
    def kept(self) -> int:
        return self.loaded - self.empty - self.duplicates - self.gap_topic


def download(spec: DatasetSpec, raw_dir: Path) -> Path:
    """Fetch the pinned file into `raw_dir` (skipped if already present)."""
    path = raw_dir / spec.revision[:12] / spec.filename
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(spec.url, follow_redirects=True, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    return path


# --- Cleaning ---------------------------------------------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SLACK_EMOJI = re.compile(r":[a-z0-9_+-]+:")
_REPLY_PREFIX = re.compile(r"^(?:(?:re|fwd?):\s*|\[[^\]]+\]\s*|ticket\s*#\d+\s*-\s*)+", re.I)
_OTHER_COMPANIES = re.compile(r"\b(?:Kreeda Labs|Acme(?: Corp(?:oration)?| Inc\.?)?)\b")
_WHITESPACE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = _EMAIL.sub("", text)
    text = _SLACK_EMOJI.sub("", text)
    text = _OTHER_COMPANIES.sub(COMPANY_NAME, text)
    return _WHITESPACE.sub(" ", text).strip()


def _dedupe_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _filter(candidates: list[SourceRecord], report: CleaningReport) -> list[SourceRecord]:
    seen: set[str] = set()
    kept = []
    for record in candidates:
        key = _dedupe_key(record.text)
        if not key:
            report.empty += 1
        elif key in seen:
            report.duplicates += 1
        elif find_gap_mentions(record.text):
            report.gap_topic += 1
        else:
            seen.add(key)
            kept.append(record)
    return kept


def load_hr_qa(path: Path) -> tuple[list[SourceRecord], CleaningReport]:
    report = CleaningReport()
    candidates = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        report.loaded += 1
        messages = json.loads(line)["messages"]
        by_role = {m["role"]: m["content"] for m in messages}
        if not {"user", "assistant"} <= by_role.keys():
            raise ValueError(f"{path.name}:{line_no}: expected user and assistant messages")
        question, answer = clean_text(by_role["user"]), clean_text(by_role["assistant"])
        text = f"Q: {question}\nA: {answer}" if question and answer else ""
        candidates.append(SourceRecord(f"hr_qa:{line_no}", HR_QA.key, text))
    return _filter(candidates, report), report


def load_it_tickets(path: Path) -> tuple[list[SourceRecord], CleaningReport]:
    report = CleaningReport()
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    missing = IT_TICKET_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    candidates = []
    for row in reader:
        report.loaded += 1
        subject = clean_text(_REPLY_PREFIX.sub("", row["subject"] or ""))
        description = clean_text(row["description"] or "")
        text = f"[{row['category']}] {subject}: {description}" if subject and description else ""
        candidates.append(SourceRecord(f"it_tickets:{row['id']}", IT_TICKETS.key, text))
    return _filter(candidates, report), report
