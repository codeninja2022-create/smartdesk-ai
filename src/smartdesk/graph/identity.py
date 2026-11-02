"""Session email capture.

An email address is treated as the employee's own only when:

- SmartDesk just asked for it (`awaiting == "email"`): the first address in the reply;
- the message is essentially just an address ("it's jane@novatech.example"); or
- it follows an explicit "my email is ..." / "email: ...".

Any other address (a colleague's, say) is ordinary ticket content: it neither
sets nor conflicts with the session lock.

The email is a demo identifier, not authentication: anyone can type any address.
"""

import re
from dataclasses import dataclass

from smartdesk.tickets.models import normalize_email

_EMAIL_TOKEN = re.compile(r"[^\s<>()\[\]{},;:\"'`]+@[^\s<>()\[\]{},;:\"'`]+")
_EXPLICIT = re.compile(
    r"(?:\b(?:my|the)\s+(?:work\s+|company\s+)?e-?mail(?:\s+address)?\s*(?:is|=|:)"
    r"|\be-?mail(?:\s+address)?\s*:)\s*$",
    re.IGNORECASE,
)
_FILLER = {
    "it's", "its", "it", "is", "my", "email", "e-mail", "address", "here", "this", "sure", "ok", "okay",
    "yes", "yeah", "thanks", "thank", "you", "please", "i'm", "im", "i", "am", "use", "work",
}


@dataclass(frozen=True)
class EmailClaim:
    raw: str
    email: str | None  # normalized, or None if `raw` is not a valid address


def _only_filler(text: str) -> bool:
    words = re.findall(r"[a-z][a-z'-]*", text.lower().replace("’", "'"))
    return all(word in _FILLER for word in words)


def find_email_claim(text: str, *, awaiting_email: bool) -> EmailClaim | None:
    """The address the employee gives as their own in `text`, if any."""
    for match in _EMAIL_TOKEN.finditer(text):
        raw = match.group(0).rstrip(".!?")
        rest = text[: match.start()] + text[match.end():]
        if awaiting_email or _EXPLICIT.search(text[: match.start()]) or _only_filler(rest):
            try:
                return EmailClaim(raw, normalize_email(raw))
            except ValueError:
                return EmailClaim(raw, None)
    return None


def mask_email(email: str) -> str:
    """jane.doe@novatech.example -> j***@novatech.example"""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"
