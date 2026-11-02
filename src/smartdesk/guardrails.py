"""Input guardrails applied to every employee message before it reaches the graph.

- Unicode is normalised (NFKC), so full-width and other look-alike forms become
  their plain equivalents before routing, email capture or extraction.
- Control characters are removed, as are zero-width and bidirectional-override
  characters, which can hide text from a human reader but not from the LLM.
  Newlines and tabs are kept.
- Empty messages and messages over the configured length are rejected with a
  reply; they are never truncated, sent to the LLM or stored.
"""

import re
import unicodedata
from typing import Literal

InputProblem = Literal["empty", "too_long"]

# Code point ranges removed from every message.
_INVISIBLE_RANGES = [
    (0x00, 0x08), (0x0B, 0x0C), (0x0E, 0x1F), (0x7F, 0x9F),  # C0/C1 controls except tab, newline, CR
    (0x200B, 0x200F),  # zero-width space/joiners, LTR/RTL marks
    (0x2028, 0x2029),  # line and paragraph separators
    (0x202A, 0x202E),  # bidi embeddings and overrides
    (0x2060, 0x2064),  # word joiner, invisible operators
    (0x2066, 0x2069),  # bidi isolates
    (0xFEFF, 0xFEFF),  # byte order mark / zero-width no-break space
]  # fmt: skip
_INVISIBLE = re.compile(
    "[" + "".join(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}" for lo, hi in _INVISIBLE_RANGES) + "]"
)


def clean_input(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _INVISIBLE.sub("", text).strip()


def check_input(text: str, max_chars: int) -> tuple[str, InputProblem | None]:
    """The cleaned message, and why it is rejected (None if it is acceptable)."""
    cleaned = clean_input(text)
    if not cleaned:
        return cleaned, "empty"
    if len(cleaned) > max_chars:
        return cleaned, "too_long"
    return cleaned, None
