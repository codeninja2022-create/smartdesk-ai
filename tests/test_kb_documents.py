import pytest
from pydantic import ValidationError

from smartdesk.kb.documents import load_dir, parse, render
from tests.kb_helpers import make_doc


def test_render_parse_round_trip():
    doc = make_doc()
    assert parse(render(doc)) == doc


def test_parse_rejects_missing_front_matter():
    with pytest.raises(ValueError, match="front matter"):
        parse("# Just markdown\n")


@pytest.mark.parametrize("doc_id", ["IT-Upper", "xx-unknown-prefix", "it-", "it_bad"])
def test_invalid_doc_ids_are_rejected(doc_id):
    with pytest.raises(ValidationError):
        make_doc(doc_id=doc_id)


def test_load_dir_requires_file_name_to_match_doc_id(tmp_path):
    (tmp_path / "it-wrong-name.md").write_text(render(make_doc("it-sample")), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match doc_id"):
        load_dir(tmp_path)


def test_load_dir_reads_sorted_documents(tmp_path):
    for doc_id in ("it-b", "hr-a"):
        (tmp_path / f"{doc_id}.md").write_text(render(make_doc(doc_id)), encoding="utf-8")
    assert [d.doc_id for d in load_dir(tmp_path)] == ["hr-a", "it-b"]
