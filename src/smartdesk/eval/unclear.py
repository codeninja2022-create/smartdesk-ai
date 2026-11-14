"""Unclear-message evaluation (docs/specs/m7-plan.md §5).

    python -m smartdesk.eval.unclear
"""

import sys
from pathlib import Path

from smartdesk.eval.live import run_case_file

CASES = Path("data/eval/unclear.jsonl")

if __name__ == "__main__":
    sys.exit(run_case_file("unclear", CASES))
