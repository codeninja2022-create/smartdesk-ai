"""Offline tests for the rubric coverage table (m7-plan §6)."""

from smartdesk.eval import coverage


def _collector(by_line: dict) -> coverage._Collector:
    collector = coverage._Collector()
    collector.by_line.update(by_line)
    return collector


def test_a_line_without_tests_is_uncovered_and_manual_lines_are_labelled():
    markdown, uncovered = coverage.table(_collector({"A1": [("tests/test_kb_data.py::test_x", False)]}))
    assert "A1" not in uncovered and "A2" in uncovered and "E1" not in uncovered
    assert "| A2 | Chunking strategy and justification | **UNCOVERED** |" in markdown
    assert coverage.MANUAL["E1"] in markdown


def test_offline_and_live_tests_are_counted_separately():
    tests = [("tests/test_a.py::t1", False), ("tests/test_a.py::t2", False), ("tests/test_live.py::t3", True)]
    markdown, _ = coverage.table(_collector({"B1": tests}))
    row = next(line for line in markdown.splitlines() if line.startswith("| B1 |"))
    assert "`test_a.py` (2), `test_live.py` (1)" in row and "2 offline / 1 live" in row


def test_every_rubric_marker_in_the_suite_names_a_known_line():
    collector = coverage.collect()
    assert collector.unknown == set()
    assert collector.by_line["B3"], "the HITL tests should be mapped"
