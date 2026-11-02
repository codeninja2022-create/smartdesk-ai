from smartdesk.tickets.adf import adf_to_text, text_to_adf


def test_text_to_adf_builds_paragraphs_and_hard_breaks():
    doc = text_to_adf("Line one\nLine two\n\nSecond paragraph")
    assert doc["type"] == "doc" and doc["version"] == 1
    first, second = doc["content"]
    assert [n["type"] for n in first["content"]] == ["text", "hardBreak", "text"]
    assert second["content"][0]["text"] == "Second paragraph"


def test_round_trip_keeps_the_text():
    text = "Employee email: jane@novatech.example\nCategory: IT\n\nThe monitor flickers."
    assert adf_to_text(text_to_adf(text)) == text


def test_adf_to_text_handles_lists_mentions_and_unknown_nodes():
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "mention", "attrs": {"text": "@Sam"}},
                {"type": "text", "text": " please try:"},
            ]},
            {"type": "orderedList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Reseat the cable"}]},
                ]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Update drivers"}]},
                ]},
            ]},
            {"type": "mysteryNode", "content": [{"type": "text", "text": "still shown"}]},
        ],
    }
    assert adf_to_text(doc) == "@Sam please try:\n\n1. Reseat the cable\n2. Update drivers\n\nstill shown"


def test_adf_to_text_accepts_none_and_plain_strings():
    assert adf_to_text(None) == ""
    assert adf_to_text("plain") == "plain"
