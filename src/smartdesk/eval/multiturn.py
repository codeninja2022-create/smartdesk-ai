"""Multi-turn conversation evaluation (docs/specs/m7-plan.md §4).

    python -m smartdesk.eval.multiturn
"""

import sys
from pathlib import Path

from smartdesk.eval.live import run_case_file

CASES = Path("data/eval/multiturn.jsonl")

if __name__ == "__main__":
    sys.exit(run_case_file("multiturn", CASES))
