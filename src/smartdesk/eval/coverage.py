"""Rubric coverage: which tests cover each capstone rubric line (docs/specs/m7-plan.md §6).

    python -m smartdesk.eval.coverage [--out PATH]

Tests declare what they cover with `@pytest.mark.rubric("B3", ...)` (or a
module-level `pytestmark`). This collects the suite without running it and
prints one Markdown row per rubric line. A line with no test is UNCOVERED.
"""

import argparse
import contextlib
import io
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

# Graded rubric lines (docs/rubric-traceability.md) and the CLAUDE.md M7 test areas.
RUBRIC: dict[str, str] = {
    "A1": "Quality and breadth of KB content",
    "A2": "Chunking strategy and justification",
    "A3": "Retrieval quality",
    "A4": "LLM grounding, no hallucination",
    "A5": "Confidence / escalation logic",
    "B1": "Successful external API integration",
    "B2": "All mandatory fields collected",
    "B3": "Human-in-the-loop confirmation",
    "B4": "Post-creation feedback with ticket ID/link",
    "C1": "Status retrieval via API",
    "C2": "Multiple-ticket handling",
    "C3": "Graceful handling when no tickets found",
    "D1": "Correct intent detection and routing",
    "D2": "Smooth multi-turn conversations",
    "D3": "Out-of-scope / ambiguous query handling",
    "E1": "Clean, modular, readable code",
    "E2": "README with setup instructions",
    "E3": "Architecture diagram",
    "F1": "Graceful API failure degradation",
    "F2": "Retry logic / LLM fallback",
    "F3": "No hard-coded secrets",
    "F4": "Edge-case handling",
    "M7-KB": "M7: KB relevance and coverage",
    "M7-RET": "M7: retrieval quality",
    "M7-GROUND": "M7: grounded answers",
    "M7-ESC": "M7: escalation",
    "M7-INTENT": "M7: intent routing",
    "M7-MULTI": "M7: multi-turn behaviour",
    "M7-JIRA": "M7: Jira ticket creation",
    "M7-STATUS": "M7: ticket status retrieval",
    "M7-HITL": "M7: HITL approval",
    "M7-ERR": "M7: error handling",
}
MANUAL = {"E1": "manual review (ruff lint is the automated proxy)"}
LIVE_EVALS = {
    "A3": "calibrate", "A4": "calibrate", "A5": "calibrate", "D1": "calibrate", "D2": "multiturn",
    "D3": "unclear, calibrate", "M7-RET": "calibrate", "M7-GROUND": "calibrate", "M7-ESC": "calibrate",
    "M7-INTENT": "calibrate, unclear", "M7-MULTI": "multiturn",
}
LIVE_MARKERS = ("openai_live", "jira_live")


class _Collector:
    def __init__(self) -> None:
        self.by_line: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        self.unknown: set[str] = set()
        self.untagged_files: Counter[str] = Counter()

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            lines = {line for m in item.iter_markers("rubric") for line in m.args}
            live = any(item.get_closest_marker(name) for name in LIVE_MARKERS)
            if not lines:
                self.untagged_files[Path(str(item.fspath)).name] += 1
            for line in lines:
                if line in RUBRIC:
                    self.by_line[line].append((item.nodeid, live))
                else:
                    self.unknown.add(line)


def collect(test_path: str = "tests") -> _Collector:
    collector = _Collector()
    with contextlib.redirect_stdout(io.StringIO()):  # pytest's own listing is not part of the table
        code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", test_path], plugins=[collector])
    if code not in (0, 5):  # 5 = no tests collected
        raise RuntimeError(f"pytest collection failed with exit code {code}")
    return collector


def _tests_cell(tests: list[tuple[str, bool]]) -> str:
    files = Counter(nodeid.split("::")[0].removeprefix("tests/") for nodeid, _ in tests)
    return ", ".join(f"`{name}` ({n})" for name, n in sorted(files.items()))


def table(collector: _Collector) -> tuple[str, list[str]]:
    """The Markdown table and the list of uncovered lines."""
    rows = ["| Rubric line | Requirement | Tests | Offline / live | Live eval |", "|---|---|---|---|---|"]
    uncovered = []
    for line, name in RUBRIC.items():
        tests = collector.by_line.get(line, [])
        live = sum(is_live for _, is_live in tests)
        evals = LIVE_EVALS.get(line, "")
        if tests:
            cell, split = _tests_cell(tests), f"{len(tests) - live} offline / {live} live"
        elif line in MANUAL:
            cell, split = MANUAL[line], "-"
        else:
            cell, split = "**UNCOVERED**", "-"
            uncovered.append(line)
        rows.append(f"| {line} | {name} | {cell} | {split} | {evals} |")
    return "\n".join(rows), uncovered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="also write the table to this file")
    args = parser.parse_args(argv)

    collector = collect()
    markdown, uncovered = table(collector)
    if collector.unknown:
        print(f"Unknown rubric lines in markers: {sorted(collector.unknown)}", file=sys.stderr)
        return 1
    print(markdown)
    print(f"\nUncovered: {', '.join(uncovered) or 'none'}")
    untagged = ", ".join(f"{name} ({n})" for name, n in sorted(collector.untagged_files.items()))
    print(f"Test files with untagged tests (not mapped to a rubric line): {untagged or 'none'}")
    if args.out:
        args.out.write_text(markdown + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
