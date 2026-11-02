"""Live checks against the real Jira Cloud project.

Run with SMARTDESK_LIVE_TESTS=1 and the JIRA_* variables set; skipped otherwise.
Each run creates one ticket for a test email, labelled `sd-live-test`, and
removes it afterwards. If the account may not delete issues, the ticket is
transitioned to Done instead and keeps its `sd-live-test` label so it can be
found and cleaned up by hand.
"""

import uuid

import pytest

from smartdesk.config import Settings
from smartdesk.tickets import TicketDraft, build_ticket_service, derive_op_id
from smartdesk.tickets.models import JiraError

pytestmark = pytest.mark.jira_live

LIVE_LABEL = "sd-live-test"


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    settings = Settings()  # type: ignore[call-arg]  # reads the real .env
    svc = build_ticket_service(
        settings.model_copy(update={"db_path": tmp_path_factory.mktemp("jira") / "live.db"}),
        extra_labels=[LIVE_LABEL],
    )
    yield svc
    svc.client.close()
    svc.store.close()


@pytest.fixture(scope="module")
def created(service):
    run = uuid.uuid4().hex[:8]
    draft = TicketDraft(
        email=f"smartdesk-live-{run}@example.com",
        summary=f"[SmartDesk live test {run}] Monitor flickers on dock",
        description="Created by tests/test_live_jira.py. Safe to delete.",
        category="IT",
        priority="Low",
    )
    op_id = derive_op_id(f"live-{run}", draft)
    ticket = service.create_ticket(draft, op_id)
    yield draft, op_id, ticket
    _cleanup(service, ticket.key)


def _cleanup(service, key: str) -> None:
    try:
        service.client.delete_issue(key)
        return
    except JiraError as exc:
        delete_error = exc
    done = [
        t
        for t in service.client.get_transitions(key)
        if (t.get("to") or {}).get("statusCategory", {}).get("key") == "done"
    ]
    if not done:
        pytest.fail(f"Could not delete {key} ({delete_error}) and no Done transition exists; clean it up by hand")
    service.client.transition_issue(key, done[0]["id"])
    print(f"\nCould not delete {key} ({delete_error}); moved it to Done with label {LIVE_LABEL}")


def test_create_returns_real_key_and_url(service, created):
    _, _, ticket = created
    assert ticket.key.startswith(f"{service.project_key}-")
    assert ticket.url == f"{service.client.base_url}/browse/{ticket.key}"
    assert ticket.already_existed is False


def test_resubmitting_the_same_op_returns_the_same_ticket(service, created):
    draft, op_id, ticket = created
    again = service.create_ticket(draft, op_id)
    assert (again.key, again.already_existed) == (ticket.key, True)


def test_ticket_is_found_by_email_with_status(service, created):
    draft, _, ticket = created
    listed = service.list_tickets(draft.email)
    assert [t.key for t in listed] == [ticket.key]
    assert listed[0].category == "IT" and listed[0].status

    details = service.get_ticket(draft.email, ticket.key)
    assert details is not None
    assert details.summary == draft.summary
    assert f"Employee email: {draft.email}" in details.description
    assert details.comments == []


def test_ticket_is_hidden_from_other_emails(service, created):
    _, _, ticket = created
    assert service.get_ticket("someone-else@example.com", ticket.key) is None
    assert service.list_tickets("someone-else@example.com") == []
