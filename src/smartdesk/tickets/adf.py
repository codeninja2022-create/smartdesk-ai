"""Conversion between plain text and Atlassian Document Format (ADF).

Jira REST API v3 takes descriptions and returns comments as ADF documents.
Only what SmartDesk needs is handled: paragraphs on the way in, and readable
text from any node on the way out.
"""

from typing import Any

_BLOCK_NODES = {"paragraph", "heading", "blockquote", "codeBlock", "listItem", "rule", "panel"}


def text_to_adf(text: str) -> dict[str, Any]:
    """One ADF paragraph per blank-line-separated block; single newlines become hard breaks."""
    content = []
    for block in text.strip().split("\n\n"):
        nodes: list[dict[str, Any]] = []
        for i, line in enumerate(block.split("\n")):
            if i:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        if nodes:
            content.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(node: Any) -> str:
    """Best-effort plain text for an ADF node (or a plain string from older APIs)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    return _render(node).strip()


def _render(node: dict[str, Any]) -> str:
    node_type = node.get("type")
    attrs = node.get("attrs") or {}
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type == "mention":
        return attrs.get("text") or "@user"
    if node_type in {"emoji", "status"}:
        return attrs.get("text") or attrs.get("shortName") or ""
    if node_type == "inlineCard":
        return attrs.get("url", "")

    children = node.get("content") or []
    if node_type in {"bulletList", "orderedList"}:
        items = []
        for index, item in enumerate(children, start=1):
            marker = f"{index}." if node_type == "orderedList" else "-"
            items.append(f"{marker} {_render(item).strip()}")
        return "\n".join(items) + "\n\n"

    inner = "".join(_render(child) for child in children)
    if node_type in _BLOCK_NODES:
        return inner.strip() + "\n\n" if node_type != "listItem" else inner
    return inner
