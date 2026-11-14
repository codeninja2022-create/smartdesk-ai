import pytest
from pydantic import ValidationError

from smartdesk.tickets.models import (
    TicketDraft,
    category_label,
    derive_op_id,
    employee_label,
    normalize_email,
    op_label,
)

pytestmark = pytest.mark.rubric("B1", "M7-JIRA")


def make_draft(**overrides) -> TicketDraft:
    fields = dict(
        email="Jane.Doe@NovaTech.example",
        summary="Monitor flickers on dock",
        description="My external monitor flickers when connected to the dock.",
        category="IT",
    )
    fields.update(overrides)
    return TicketDraft(**fields)


def test_email_is_trimmed_and_lowercased():
    assert normalize_email("  Jane.Doe@NovaTech.Example ") == "jane.doe@novatech.example"
    assert make_draft().email == "jane.doe@novatech.example"


@pytest.mark.parametrize(
    "email", ["", "jane", "jane@", "@novatech.example", "jane@novatech", "ja ne@x.com", "a@b@c.com"]
)
def test_invalid_emails_are_rejected(email):
    with pytest.raises(ValueError):
        normalize_email(email)
    with pytest.raises(ValidationError):
        make_draft(email=email)


@pytest.mark.parametrize("summary", ["", "   ", "line one\nline two", "x" * 256])
def test_summary_must_be_one_non_empty_line(summary):
    with pytest.raises(ValidationError):
        make_draft(summary=summary)


def test_description_must_not_be_blank():
    with pytest.raises(ValidationError):
        make_draft(description="  \n ")


def test_category_and_priority_are_restricted():
    with pytest.raises(ValidationError):
        make_draft(category="Finance")
    with pytest.raises(ValidationError):
        make_draft(priority="Urgent")
    assert make_draft(priority="Critical").priority == "Critical"
    assert make_draft().priority is None


def test_employee_label_is_stable_and_case_insensitive():
    label = employee_label("jane.doe@novatech.example")
    assert label == employee_label("  JANE.DOE@novatech.example")
    assert label.startswith("sd-emp-") and len(label) == len("sd-emp-") + 16
    assert "jane" not in label
    assert label != employee_label("john@novatech.example")


def test_category_and_op_labels():
    assert category_label("IT") == "sd-cat-it"
    assert category_label("HR") == "sd-cat-hr"
    assert op_label("a" * 64) == "sd-op-" + "a" * 32


def test_op_id_is_stable_for_the_same_session_and_draft():
    same_email = make_draft(email="jane.doe@novatech.example")
    assert derive_op_id("thread-1", make_draft()) == derive_op_id("thread-1", same_email)


def test_op_id_changes_with_session_or_content():
    base = derive_op_id("thread-1", make_draft())
    assert derive_op_id("thread-2", make_draft()) != base
    assert derive_op_id("thread-1", make_draft(summary="Monitor flickers")) != base
    assert derive_op_id("thread-1", make_draft(priority="High")) != base
    assert derive_op_id("thread-1", make_draft(category="HR")) != base


def test_op_id_requires_a_session():
    with pytest.raises(ValueError):
        derive_op_id(" ", make_draft())
