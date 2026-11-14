"""Shared plumbing for live evaluation runs (docs/specs/m7-plan.md §2, §8).

- Budget: `CostTracker` charges every real OpenAI call from its reported token
  usage and refuses a call before it is sent once spend plus a per-call
  reserve would pass the cap (default $10). Cached responses cost nothing.
- Caching: `SQLiteLLMCache` (LangChain `BaseCache`) and `CachedEmbedder` keep
  responses under data/eval/.cache/, so repeating a dev run is free.
- Token log: one JSON line per call (model, tokens, cost, cache hit, latency).
- Timing: `Timer` measures turns with time.perf_counter; p50/p95 use uncached turns only.
- Metadata: git SHA (clean tree required for a recorded run), date, models, prices.
- Held-out marker: written atomically, and only after a run completes.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import tiktoken
from langchain_core._api import LangChainBetaWarning
from langchain_core.caches import RETURN_VAL_TYPE, BaseCache
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.load import dumps, loads
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, Generation, LLMResult
from pydantic import BaseModel

CACHE_DIR = Path("data/eval/.cache")
RUNS_DIR = Path("data/eval/runs")
DEFAULT_BUDGET_USD = 10.0
CALL_RESERVE_USD = 0.05  # assumed upper bound for one call; refused if spend + reserve > cap

# USD per 1M tokens (input, output), standard tier. Checked 2026-11-14 against
# https://developers.openai.com/api/docs/pricing and copied into the report. OpenAI's cached-input
# discount is ignored, so spend is over- rather than under-estimated. A model missing from this
# table is charged at the highest rate.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}


class BudgetExceeded(RuntimeError):
    """Raised before an LLM call that could take the run past its budget."""


def price_for(model: str) -> tuple[float, float]:
    # Responses name dated snapshots ("gpt-4o-mini-2024-07-18"): match the longest known prefix.
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name):
            return PRICES[name]
    return max(PRICES.values())


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = price_for(model)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def prior_spend_usd(runs_dir: Path = RUNS_DIR) -> float:
    """Total cost already logged by earlier runs: the $10 cap is cumulative across runs (plan §2)."""
    total = 0.0
    for log_path in runs_dir.glob("*/calls.jsonl"):
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += json.loads(line).get("cost_usd", 0.0)
    return total


class CallLog:
    """Append-only JSONL log of every call, plus running totals.

    `spent_usd` starts at `prior_usd`, so the budget check sees cumulative spend;
    `run_spent_usd` is this run alone.
    """

    def __init__(self, path: Path | None, prior_usd: float = 0.0) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.prior_usd = prior_usd
        self.spent_usd = prior_usd
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, kind: str, model: str, input_tokens: int, output_tokens: int, cached: bool,
               latency_s: float | None) -> None:
        cost = 0.0 if cached else cost_usd(model, input_tokens, output_tokens)
        with self.lock:
            self.calls += 1
            self.cache_hits += cached
            if not cached:
                self.spent_usd += cost
                self.input_tokens += input_tokens
                self.output_tokens += output_tokens
            if self.path:
                entry = {"kind": kind, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens,
                         "cost_usd": round(cost, 6), "cached": cached,
                         "latency_s": None if latency_s is None else round(latency_s, 4)}
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")

    def totals(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "run_spent_usd": round(self.spent_usd - self.prior_usd, 4),
                "cumulative_spent_usd": round(self.spent_usd, 4)}


class CostTracker(BaseCallbackHandler):
    """Charges real chat-model calls and enforces the budget before each call."""

    raise_error = True  # BudgetExceeded must stop the run, not be logged and swallowed

    def __init__(self, log: CallLog, budget_usd: float = DEFAULT_BUDGET_USD) -> None:
        self.log = log
        self.budget_usd = budget_usd
        self._started: dict[Any, float] = {}
        # ChatSession turns any exception into an error reply, so runners check this flag after each turn.
        self.exceeded = False

    def check_budget(self) -> None:
        if self.log.spent_usd + CALL_RESERVE_USD > self.budget_usd:
            self.exceeded = True
            raise BudgetExceeded(f"spent ${self.log.spent_usd:.2f} of the ${self.budget_usd:.2f} budget")

    def on_chat_model_start(self, serialized: dict, messages: list, *, run_id: Any, **kwargs: Any) -> None:
        self.check_budget()
        self._started[run_id] = time.perf_counter()

    def on_llm_end(self, response: LLMResult, *, run_id: Any, **kwargs: Any) -> None:
        started = self._started.pop(run_id, None)
        latency = None if started is None else time.perf_counter() - started
        output = response.llm_output
        if output is None:  # served from the cache: no API call was made
            usage = getattr(response.generations[0][0], "message", None)
            usage = getattr(usage, "usage_metadata", None) or {}
            model = (getattr(response.generations[0][0], "message", None).response_metadata or {}).get("model_name", "")
            self.log.record(kind="chat", model=model, input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0), cached=True, latency_s=latency)
            return
        usage = output.get("token_usage") or {}
        self.log.record(kind="chat", model=output.get("model_name", ""), input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0), cached=False, latency_s=latency)


class SQLiteLLMCache(BaseCache):
    """LangChain LLM cache in a local SQLite file (langchain-community is not a dependency)."""

    def __init__(self, path: Path = CACHE_DIR / "llm.db") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.execute("CREATE TABLE IF NOT EXISTS llm (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    @staticmethod
    def _key(prompt: str, llm_string: str) -> str:
        return hashlib.sha256(f"{llm_string}\x00{prompt}".encode()).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM llm WHERE key = ?", (self._key(prompt, llm_string),)).fetchone()
        if not row:
            return None
        with warnings.catch_warnings():  # `loads` is marked beta; the allow-list below is the stable part
            warnings.simplefilter("ignore", LangChainBetaWarning)
            # Only the reply objects this cache stores can be revived from the file.
            return loads(row[0], allowed_objects=[ChatGeneration, Generation, AIMessage])

    @staticmethod
    def _storable(generation: Generation) -> Generation:
        """Structured output carries a parsed Pydantic object, which cannot be serialised. The
        OpenAI parser also accepts it as a dict, so the stored copy holds a dict instead."""
        message = getattr(generation, "message", None)
        parsed = message.additional_kwargs.get("parsed") if message is not None else None
        if not isinstance(parsed, BaseModel):
            return generation
        kwargs = {**message.additional_kwargs, "parsed": parsed.model_dump(mode="json")}
        return generation.model_copy(update={"message": message.model_copy(update={"additional_kwargs": kwargs})})

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        stored = dumps([self._storable(g) for g in return_val])
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO llm VALUES (?, ?)", (self._key(prompt, llm_string), stored))
            self.conn.commit()

    def clear(self, **kwargs: Any) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM llm")
            self.conn.commit()


class CachedEmbedder:
    """Wraps an `embed_query` function with a SQLite cache and token/cost logging."""

    def __init__(self, embed_query: Callable[[str], list[float]], model: str, log: CallLog,
                 path: Path = CACHE_DIR / "embeddings.db", before_call: Callable[[], None] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.before_call = before_call  # e.g. CostTracker.check_budget
        self.embed_query_uncached = embed_query
        self.model = model
        self.log = log
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vector TEXT NOT NULL)")

    def __call__(self, text: str) -> list[float]:
        key = hashlib.sha256(f"{self.model}\x00{text}".encode()).hexdigest()
        tokens = len(self.encoding.encode(text))
        with self.lock:
            row = self.conn.execute("SELECT vector FROM emb WHERE key = ?", (key,)).fetchone()
        if row:
            self.log.record(kind="embedding", model=self.model, input_tokens=tokens, output_tokens=0, cached=True,
                            latency_s=None)
            return json.loads(row[0])
        if self.before_call:
            self.before_call()
        started = time.perf_counter()
        vector = self.embed_query_uncached(text)
        self.log.record(kind="embedding", model=self.model, input_tokens=tokens, output_tokens=0, cached=False,
                        latency_s=time.perf_counter() - started)
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO emb VALUES (?, ?)", (key, json.dumps(vector)))
            self.conn.commit()
        return vector


@dataclass
class Timer:
    """Per-turn wall-clock timings; a turn counts for latency only if it made no cached call."""

    uncached: list[float] = field(default_factory=list)
    cached: int = 0

    @contextmanager
    def turn(self, log: CallLog) -> Iterator[None]:
        hits_before, started = log.cache_hits, time.perf_counter()
        yield
        elapsed = time.perf_counter() - started
        if log.cache_hits > hits_before:
            self.cached += 1
        else:
            self.uncached.append(elapsed)

    def summary(self) -> dict:
        return {
            "turns_timed": len(self.uncached),
            "turns_with_cache_hits_excluded": self.cached,
            "p50_s": percentile(self.uncached, 50),
            "p95_s": percentile(self.uncached, 95),
        }


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile (numpy default); None for no values."""
    return round(float(np.percentile(values, q)), 3) if values else None


def git_state(ignore: tuple[str, ...] = ()) -> dict:
    """HEAD and whether the tree differs from it; `ignore` lists result files the runs themselves write."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()

    excludes = [f":!{path}" for path in ignore]
    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", ".", *excludes))}


def run_metadata(settings: Any, command: list[str]) -> dict:
    return {
        "git": git_state(),
        "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "models": {
            "chat": settings.llm_model,
            "embedding": settings.embedding_model,
            "fallback": settings.llm_fallback_model,
        },
        "prices_usd_per_1m_tokens": PRICES,
        "command": " ".join(command),
    }


def new_run_dir(name: str) -> Path:
    path = RUNS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_marker(path: Path, payload: dict) -> None:
    """Write the marker atomically: a crash leaves either no file or the complete file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
