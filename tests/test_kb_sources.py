import json

import pytest

from smartdesk.kb import sources

pytestmark = pytest.mark.rubric("A1", "M7-KB")


def test_clean_text_strips_emails_emoji_and_other_company_names():
    text = "Hi :wave:  mail j.doe@acme.co about the Kreeda Labs policy at Acme Corp"
    assert sources.clean_text(text) == "Hi mail about the NovaTech Solutions policy at NovaTech Solutions"


def _write_hr(path, pairs):
    lines = [
        json.dumps({"messages": [{"role": "system", "content": "sys"},
                                 {"role": "user", "content": q}, {"role": "assistant", "content": a}]})
        for q, a in pairs
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_hr_qa_dedupes_and_drops_gap_topics(tmp_path):
    path = tmp_path / "dataset.jsonl"
    _write_hr(path, [
        ("How many leaves?", "12 days."),
        ("How many leaves?", "12 days."),  # duplicate
        ("Is there parking?", "Yes."),  # gap topic
        ("", "orphan answer"),  # empty question
    ])
    records, report = sources.load_hr_qa(path)
    assert [r.record_id for r in records] == ["hr_qa:1"]
    assert records[0].text == "Q: How many leaves?\nA: 12 days."
    assert (report.loaded, report.duplicates, report.gap_topic, report.empty, report.kept) == (4, 1, 1, 1, 1)


def test_load_it_tickets_cleans_subjects_and_excludes_requester_email(tmp_path):
    path = tmp_path / "tickets.csv"
    path.write_text(
        "id,subject,description,priority,category,createdAt,requesterEmail\n"
        "t1,Re: [Acme IT] Ticket #123 - VPN down,Cannot connect,High,Network,2024-01-01,a@b.com\n"
        "t2,Printer jam,The printer is jammed,Low,Hardware,2024-01-01,c@d.com\n",
        encoding="utf-8",
    )
    records, report = sources.load_it_tickets(path)
    assert [(r.record_id, r.text) for r in records] == [("it_tickets:t1", "[Network] VPN down: Cannot connect")]
    assert report.gap_topic == 1


def test_load_it_tickets_validates_schema(tmp_path):
    path = tmp_path / "tickets.csv"
    path.write_text("id,subject\nt1,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        sources.load_it_tickets(path)


def test_datasets_are_pinned_to_full_commit_shas():
    for spec in sources.DATASETS.values():
        assert len(spec.revision) == 40 and spec.revision in spec.url
