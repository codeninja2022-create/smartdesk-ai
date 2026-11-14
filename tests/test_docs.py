"""The README carries the setup instructions and design notes the rubric grades."""

import re
from pathlib import Path

import pytest

README = Path("README.md").read_text(encoding="utf-8")
HEADINGS = {m.group(1).strip() for m in re.finditer(r"^#{2,3} (.+)$", README, re.M)}


@pytest.mark.rubric("E2")
@pytest.mark.parametrize("heading", ["Setup", "Environment variables", "Populate the knowledge base", "Run", "Tests"])
def test_readme_has_setup_and_run_instructions(heading: str):
    assert heading in HEADINGS


@pytest.mark.rubric("A2")
def test_readme_justifies_the_chunking_strategy():
    assert "Chunking strategy" in HEADINGS
