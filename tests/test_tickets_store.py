import sqlite3

import pytest

from smartdesk.tickets.store import TicketStore

pytestmark = pytest.mark.rubric("B1", "M7-JIRA")

EMAIL = "jane@novatech.example"


@pytest.fixture
def store(tmp_path):
    s = TicketStore(tmp_path / "nested" / "smartdesk.db")
    yield s
    s.close()


def test_schema_is_created_and_reopenable(tmp_path):
    path = tmp_path / "smartdesk.db"
    TicketStore(path).close()
    store = TicketStore(path)  # CREATE ... IF NOT EXISTS on an existing file
    assert store.get_op("missing") is None
    store.close()


def test_claim_creates_a_pending_op(store):
    assert store.claim_op("op1", EMAIL) is True
    op = store.get_op("op1")
    assert (op.status, op.attempts, op.ticket_key, op.email) == ("pending", 0, None, EMAIL)


def test_second_claim_is_refused(store):
    assert store.claim_op("op1", EMAIL)
    assert store.claim_op("op1", EMAIL) is False


@pytest.mark.parametrize("state", ["unknown", "created"])
def test_claim_is_refused_for_unknown_and_created_ops(store, state):
    store.claim_op("op1", EMAIL)
    if state == "unknown":
        store.mark_unknown("op1", "ReadTimeout")
    else:
        store.mark_created("op1", "KAN-7", "IT")
    assert store.claim_op("op1", EMAIL) is False


def test_failed_op_can_be_reclaimed(store):
    store.claim_op("op1", EMAIL)
    store.record_attempt("op1")
    store.mark_failed("op1", "JiraRequestRejected")
    assert store.claim_op("op1", EMAIL) is True
    op = store.get_op("op1")
    assert (op.status, op.attempts, op.last_error) == ("pending", 0, None)


def test_attempts_are_counted(store):
    store.claim_op("op1", EMAIL)
    assert store.record_attempt("op1") == 1
    store.mark_unknown("op1", "ReadTimeout")
    assert store.record_attempt("op1") == 2
    assert store.get_op("op1").status == "pending"


def test_mark_created_records_the_mapping(store):
    store.claim_op("op1", EMAIL)
    store.mark_created("op1", "KAN-7", "IT")
    op = store.get_op("op1")
    assert (op.status, op.ticket_key) == ("created", "KAN-7")
    assert store.ticket_keys(EMAIL) == ["KAN-7"]
    assert store.is_mapped(EMAIL, "KAN-7")
    assert not store.is_mapped("john@novatech.example", "KAN-7")


def test_add_mapping_is_idempotent_and_keeps_op_link(store):
    store.claim_op("op1", EMAIL)
    store.mark_created("op1", "KAN-7", "IT")
    store.add_mapping(EMAIL, "KAN-7", "IT")
    store.add_mapping(EMAIL, "KAN-9", "HR")
    assert sorted(store.ticket_keys(EMAIL)) == ["KAN-7", "KAN-9"]
    assert store.ticket_keys("nobody@novatech.example") == []


def test_invalid_status_and_category_are_rejected_by_the_schema(store):
    store.claim_op("op1", EMAIL)
    with pytest.raises(sqlite3.IntegrityError):
        store._set_status("op1", "bogus", None)  # type: ignore[arg-type]
    with pytest.raises(sqlite3.IntegrityError):
        store.add_mapping(EMAIL, "KAN-1", "Finance")
