"""The held-out split is frozen: any edit changes its hash and fails this test."""

import hashlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.rubric("A3", "M7-RET")

HELDOUT = Path("data/eval/heldout")


def test_heldout_set_matches_its_frozen_hash():
    pinned = (HELDOUT / "FROZEN.sha256").read_text(encoding="utf-8").split()[0]
    data = (HELDOUT / "eval_set.jsonl").read_bytes().replace(bytes([13, 10]), bytes([10]))  # same hash on any OS
    actual = hashlib.sha256(data).hexdigest()
    assert actual == pinned, "held-out set changed after it was frozen; it must never be tuned against"
