import collections
import re

import pytest

from smartdesk.kb.catalog import GAPS, TOPICS, find_gap_mentions
from smartdesk.kb.documents import DOC_ID_PATTERN

pytestmark = pytest.mark.rubric("A1", "M7-KB")


def test_topic_plan_matches_approved_counts():
    counts = collections.Counter(t.category for t in TOPICS)
    assert counts == {"IT Support": 18, "HR Policies": 12, "Onboarding": 5, "Payroll & Compensation": 5}
    assert 30 <= len(TOPICS) <= 50


def test_topic_ids_are_unique_and_valid():
    ids = [t.doc_id for t in TOPICS]
    assert len(ids) == len(set(ids))
    assert all(re.match(DOC_ID_PATTERN, doc_id) for doc_id in ids)


def test_gap_list_matches_approved_gaps():
    assert [g.gap_id for g in GAPS] == [
        "monitor-flickering", "office-parking", "printers", "cafeteria",
        "office-shuttle", "relocation", "sabbatical",
    ]


@pytest.mark.parametrize(
    ("text", "gap_id"),
    [
        ("My monitor is flickering", "monitor-flickering"),
        ("Where is visitor parking?", "office-parking"),
        ("The printer is jammed", "printers"),
        ("Is the cafeteria open?", "cafeteria"),
        ("Take the office shuttle", "office-shuttle"),
        ("Relocation allowance details", "relocation"),
        ("Apply for a sabbatical", "sabbatical"),
    ],
)
def test_gap_terms_are_detected(text, gap_id):
    assert gap_id in find_gap_mentions(text)


@pytest.mark.parametrize(
    "text",
    [
        "Business travel expenses (transportation, accommodation, meals).",
        "Hybrid work saves commute time.",
        "Run a malware scanning tool.",
        "Install Cisco Secure Client from Software Center.",
    ],
)
def test_ordinary_text_is_not_flagged(text):
    assert find_gap_mentions(text) == []
