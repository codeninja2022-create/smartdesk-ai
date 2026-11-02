import json

import pytest

from smartdesk.tickets.models import (
    JiraRequestRejected,
    JiraUnavailable,
    TicketCreationUncertain,
    TicketDraft,
    derive_op_id,
    employee_label,
    op_label,
)
from smartdesk.tickets.service import JiraTicketService, build_ticket_service
from smartdesk.tickets.store import TicketStore
from tests.jira_fake import BASE_URL, FakeJira

EMAIL = "jane.doe@novatech.example"
OTHER = "john@novatech.example"
OP1, OP2 = "1" * 64, "2" * 64  # derive_op_id produces 64 hex characters


def make_draft(**overrides) -> TicketDraft:
    fields = dict(
        email=EMAIL,
        summary="Monitor flickers on dock",
        description="My external monitor flickers when connected to the dock.",
        category="IT",
        priority="Critical",
    )
    fields.update(overrides)
    return TicketDraft(**fields)


@pytest.fixture
def jira() -> FakeJira:
    return FakeJira()


@pytest.fixture
def store(tmp_path):
    s = TicketStore(tmp_path / "smartdesk.db")
    yield s
    s.close()


@pytest.fixture
def make_service(jira, store):
    def factory(**options) -> JiraTicketService:
        options.setdefault("reconcile_polls", 3)
        options.setdefault("reconcile_delay_seconds", 0)
        return JiraTicketService(jira.client(), store, project_key="KAN", sleep=lambda s: None, **options)

    return factory


# --- creation ---


def test_create_ticket_returns_real_key_and_url(jira, store, make_service):
    draft = make_draft()
    op_id = derive_op_id("thread-1", draft)
    ticket = make_service().create_ticket(draft, op_id)

    assert (ticket.key, ticket.url, ticket.already_existed) == ("KAN-1", f"{BASE_URL}/browse/KAN-1", False)
    fields = jira.issues["KAN-1"]["fields"]
    assert set(fields["labels"]) == {"smartdesk", "sd-cat-it", employee_label(EMAIL), op_label(op_id)}
    assert fields["summary"] == draft.summary
    assert store.get_op(op_id).status == "created"
    assert store.ticket_keys(EMAIL) == ["KAN-1"]


def test_issue_fields_carry_email_in_description_and_mapped_priority(jira, make_service):
    make_service().create_ticket(make_draft(), OP1)
    assert json.loads(jira.requests[0].content)["fields"]["priority"] == {"name": "Highest"}  # Critical -> Highest
    paragraph = jira.issues["KAN-1"]["fields"]["description"]["content"][0]["content"]
    assert paragraph[0]["text"] == f"Employee email: {EMAIL}"


def test_priority_is_omitted_when_not_given(jira, make_service):
    make_service().create_ticket(make_draft(priority=None), OP1)
    assert b"priority" not in jira.requests[0].content


def test_extra_labels_are_added(jira, make_service):
    make_service(extra_labels=["sd-live-test"]).create_ticket(make_draft(), OP1)
    assert "sd-live-test" in jira.issues["KAN-1"]["fields"]["labels"]


def test_duplicate_submission_makes_no_jira_call(jira, make_service):
    service = make_service()
    first = service.create_ticket(make_draft(), OP1)
    calls = len(jira.requests)
    second = service.create_ticket(make_draft(), OP1)

    assert second.key == first.key and second.already_existed is True
    assert len(jira.requests) == calls
    assert len(jira.issues) == 1


def test_timeout_then_reconcile_finds_issue_without_reposting(jira, store, make_service):
    jira.create_script = ["timeout_after_create"]
    ticket = make_service().create_ticket(make_draft(), OP1)

    assert ticket.key == "KAN-1" and ticket.already_existed is False
    assert jira.posts_to_create() == 1
    assert len(jira.issues) == 1
    assert store.get_op(OP1).status == "created"
    assert store.ticket_keys(EMAIL) == ["KAN-1"]


def test_reconcile_polls_through_search_lag(jira, make_service):
    jira.create_script = ["timeout_after_create"]
    jira.search_lag = 2  # issue exists but the first two searches miss it
    sleeps: list[float] = []
    service = make_service(reconcile_delay_seconds=2.0)
    service._sleep = sleeps.append

    assert service.create_ticket(make_draft(), OP1).key == "KAN-1"
    assert jira.posts_to_create() == 1
    assert sleeps == [2.0, 2.0]


def test_timeout_with_nothing_created_retries_once_after_reconciling(jira, make_service):
    jira.create_script = ["timeout_before_create", "ok"]
    ticket = make_service().create_ticket(make_draft(), OP1)

    assert ticket.key == "KAN-1"
    assert jira.posts_to_create() == 2
    order = [("POST" if r.url.path.endswith("/issue") else "SEARCH") for r in jira.requests]
    assert order == ["POST", "SEARCH", "SEARCH", "SEARCH", "POST"]  # reconciled before the retry


def test_500_after_create_is_reconciled_not_reposted(jira, make_service):
    jira.create_script = ["500_after_create"]
    assert make_service().create_ticket(make_draft(), OP1).key == "KAN-1"
    assert jira.posts_to_create() == 1


def test_exhausted_attempts_raise_uncertain_and_next_call_reconciles_first(jira, store, make_service):
    jira.create_script = ["timeout_before_create", "timeout_before_create"]
    service = make_service(max_create_attempts=2)
    with pytest.raises(TicketCreationUncertain):
        service.create_ticket(make_draft(), OP1)
    op = store.get_op(OP1)
    assert (op.status, op.attempts) == ("unknown", 2)
    assert jira.posts_to_create() == 2

    # The issue from an earlier attempt shows up later: the next call must find it, not post again.
    jira.add_issue(["smartdesk", op_label(OP1), employee_label(EMAIL), "sd-cat-it"])
    ticket = service.create_ticket(make_draft(), OP1)
    assert ticket.already_existed is True
    assert jira.posts_to_create() == 2


def test_unknown_op_with_no_issue_posts_again_after_reconciling(jira, store, make_service):
    jira.create_script = ["timeout_before_create", "timeout_before_create", "ok"]
    service = make_service(max_create_attempts=2)
    with pytest.raises(TicketCreationUncertain):
        service.create_ticket(make_draft(), OP1)
    searches_before = len(jira.searches())

    ticket = service.create_ticket(make_draft(), OP1)
    assert ticket.key == "KAN-1"
    assert len(jira.searches()) > searches_before  # reconciled before the third POST
    assert jira.posts_to_create() == 3


def test_stale_pending_op_is_reconciled_first(jira, store, make_service):
    # Simulates a crash after the POST was counted but before its result was stored.
    store.claim_op(OP1, EMAIL)
    store.record_attempt(OP1)
    jira.add_issue(["smartdesk", op_label(OP1)])

    ticket = make_service(in_flight_seconds=0).create_ticket(make_draft(), OP1)
    assert ticket.key == "KAN-1" and ticket.already_existed is True
    assert jira.posts_to_create() == 0


def test_recent_pending_op_is_treated_as_in_flight(jira, store, make_service):
    store.claim_op(OP1, EMAIL)
    with pytest.raises(TicketCreationUncertain, match="already being created"):
        make_service(in_flight_seconds=60).create_ticket(make_draft(), OP1)
    assert jira.requests == []


@pytest.mark.parametrize(("action", "error"), [(400, JiraRequestRejected), ("connect_error", JiraUnavailable)])
def test_definite_failure_marks_failed_and_allows_retry(jira, store, make_service, action, error):
    jira.create_script = [action, "ok"]
    service = make_service()
    with pytest.raises(error):
        service.create_ticket(make_draft(), OP1)
    assert store.get_op(OP1).status == "failed"
    assert jira.searches() == []  # nothing ambiguous, so no reconciliation needed

    assert service.create_ticket(make_draft(), OP1).key == "KAN-1"
    assert jira.posts_to_create() == 2


def test_failed_reconcile_search_is_uncertain_not_unavailable(jira, store, make_service):
    # A POST may have created the issue; if Jira cannot be searched, "not created" would be a lie.
    jira.create_script = ["timeout_after_create"]
    jira.read_script = ["timeout"] * 10
    with pytest.raises(TicketCreationUncertain):
        make_service(max_create_attempts=1).create_ticket(make_draft(), OP1)
    assert store.get_op(OP1).status == "unknown"
    assert jira.posts_to_create() == 1


def test_reconcile_keeps_the_oldest_of_several_matches(jira, store, make_service):
    jira.add_issue([op_label(OP1)])
    jira.add_issue([op_label(OP1)])
    store.claim_op(OP1, EMAIL)
    store.mark_unknown(OP1, "ReadTimeout")
    assert make_service().create_ticket(make_draft(), OP1).key == "KAN-1"


def test_op_id_for_another_email_is_rejected(store, make_service):
    store.claim_op(OP1, OTHER)
    store.mark_created(OP1, "KAN-1", "IT")
    with pytest.raises(ValueError):
        make_service().create_ticket(make_draft(), OP1)


# --- lookup ---


def test_no_tickets_returns_empty_list(make_service):
    assert make_service().list_tickets(EMAIL) == []


def test_multiple_tickets_are_listed_newest_update_first(jira, make_service):
    old = jira.add_issue(["smartdesk", "sd-cat-it", employee_label(EMAIL)], summary="VPN drops")
    new = jira.add_issue(["smartdesk", "sd-cat-hr", employee_label(EMAIL)], summary="Payslip missing",
                         status="In Progress", status_category="In Progress")
    jira.add_issue(["smartdesk", "sd-cat-it", employee_label(OTHER)], summary="Someone else's")

    tickets = make_service().list_tickets(" Jane.Doe@NovaTech.example ")
    assert [t.key for t in tickets] == [new, old]
    assert tickets[0].category == "HR" and tickets[0].status == "In Progress"
    assert tickets[1].url == f"{BASE_URL}/browse/{old}"


def test_listing_writes_back_jira_only_tickets(jira, store, make_service):
    key = jira.add_issue(["sd-cat-it", employee_label(EMAIL)])
    make_service().list_tickets(EMAIL)
    assert store.ticket_keys(EMAIL) == [key]


def test_listing_includes_locally_mapped_tickets_missing_from_search(jira, store, make_service):
    key = jira.add_issue(["sd-cat-it", employee_label(EMAIL)])
    store.add_mapping(EMAIL, key, "IT")
    jira.search_lag = 1  # just created, not indexed yet
    assert [t.key for t in make_service().list_tickets(EMAIL)] == [key]


def test_listing_drops_deleted_tickets(store, make_service):
    store.add_mapping(EMAIL, "KAN-42", "IT")
    assert make_service().list_tickets(EMAIL) == []


def test_get_ticket_returns_status_and_comments(jira, make_service):
    key = jira.add_issue(["sd-cat-it", employee_label(EMAIL)], status="Waiting for Customer",
                         status_category="In Progress", description={"type": "doc", "content": [
                             {"type": "paragraph", "content": [{"type": "text", "text": "Flickers on dock"}]}]})
    jira.comments[key] = [{
        "author": {"displayName": "Sam (IT)"},
        "created": "2026-11-01T11:00:00.000+0000",
        "body": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Try a new cable."}]}],
        },
    }]

    ticket = make_service().get_ticket(EMAIL, key.lower())
    assert ticket.key == key
    assert (ticket.status, ticket.status_category, ticket.category) == ("Waiting for Customer", "In Progress", "IT")
    assert ticket.priority == "Medium"
    assert ticket.description == "Flickers on dock"
    assert [(c.author, c.body) for c in ticket.comments] == [("Sam (IT)", "Try a new cable.")]


def test_get_ticket_hides_other_employees_tickets(jira, make_service):
    key = jira.add_issue(["sd-cat-it", employee_label(OTHER)])
    assert make_service().get_ticket(EMAIL, key) is None


def test_get_ticket_accepts_locally_mapped_ownership(jira, store, make_service):
    key = jira.add_issue(["sd-cat-it"])  # label missing on the issue
    store.add_mapping(EMAIL, key, "IT")
    assert make_service().get_ticket(EMAIL, key).key == key


@pytest.mark.parametrize("key", ["KAN-999", "OPS-1", "KAN-1 OR project = X", "kan", ""])
def test_get_ticket_returns_none_for_missing_or_invalid_keys(jira, make_service, key):
    jira.add_issue(["sd-cat-it", employee_label(EMAIL)])
    assert make_service().get_ticket(EMAIL, key) is None


def test_lookup_rejects_invalid_email(make_service):
    with pytest.raises(ValueError):
        make_service().list_tickets("not-an-email")


def test_build_ticket_service_uses_settings(make_settings, tmp_path):
    settings = make_settings(
        JIRA_BASE_URL=BASE_URL, JIRA_EMAIL="bot@novatech.example", JIRA_API_TOKEN="t", JIRA_PROJECT_KEY="KAN",
        JIRA_ISSUE_TYPE="Service Request", JIRA_MAX_CREATE_ATTEMPTS="3", SMARTDESK_DB_PATH=str(tmp_path / "x.db"),
    )
    service = build_ticket_service(settings)
    assert (service.project_key, service.issue_type, service.max_create_attempts) == ("KAN", "Service Request", 3)
    assert service.in_flight_seconds == 20.0
    assert (tmp_path / "x.db").exists()
