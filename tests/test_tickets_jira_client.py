import base64
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from smartdesk.tickets.jira import AmbiguousCreateError, JiraClient, build_jira_client
from smartdesk.tickets.models import JiraAuthError, JiraError, JiraRequestRejected, JiraUnavailable
from tests.jira_fake import BASE_URL, FakeJira

FIELDS = {"project": {"key": "KAN"}, "issuetype": {"name": "Task"}, "summary": "s", "labels": ["smartdesk"]}


def test_create_issue_posts_fields_with_basic_auth():
    jira = FakeJira()
    assert jira.client().create_issue(FIELDS) == "KAN-1"
    request = jira.requests[0]
    assert json.loads(request.content) == {"fields": FIELDS}
    expected = base64.b64encode(b"bot@novatech.example:token-123").decode()
    assert request.headers["Authorization"] == f"Basic {expected}"


@pytest.mark.parametrize("action", ["timeout_after_create", "timeout_before_create", "500_after_create"])
def test_ambiguous_create_failures(action):
    jira = FakeJira(create_script=[action])
    with pytest.raises(AmbiguousCreateError):
        jira.client().create_issue(FIELDS)
    assert jira.posts_to_create() == 1  # never retried by the transport


def test_connect_error_on_create_is_definite():
    jira = FakeJira(create_script=["connect_error"])
    with pytest.raises(JiraUnavailable):
        jira.client().create_issue(FIELDS)


def test_client_errors_on_create():
    with pytest.raises(JiraRequestRejected, match="summary: bad") as info:
        FakeJira(create_script=[400]).client().create_issue(FIELDS)
    assert info.value.status_code == 400
    with pytest.raises(JiraAuthError):
        FakeJira(create_script=[401]).client().create_issue(FIELDS)
    with pytest.raises(JiraUnavailable):
        FakeJira(create_script=[429]).client().create_issue(FIELDS)


def test_get_issue_returns_none_on_404():
    assert FakeJira().client().get_issue("KAN-99", ["summary"]) is None


def test_reads_retry_transient_failures_with_backoff():
    jira = FakeJira(read_script=["timeout", (503, {})])
    key = jira.add_issue(["smartdesk"])
    sleeps: list[float] = []
    issue = jira.client(sleep=sleeps.append, max_retries=2).get_issue(key, ["summary"])
    assert issue["key"] == key
    assert sleeps == [0.5, 1.0]


def test_reads_honour_retry_after_seconds_on_429():
    jira = FakeJira(read_script=[(429, {"Retry-After": "7"})])
    key = jira.add_issue([])
    sleeps: list[float] = []
    jira.client(sleep=sleeps.append).get_issue(key, ["summary"])
    assert sleeps == [7.0]


def test_reads_honour_retry_after_http_date_and_cap_it():
    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    jira = FakeJira(read_script=[(429, {"Retry-After": soon}), (429, {"Retry-After": "3600"})])
    key = jira.add_issue([])
    sleeps: list[float] = []
    jira.client(sleep=sleeps.append).get_issue(key, ["summary"])
    assert 3.0 <= sleeps[0] <= 5.0
    assert sleeps[1] == 30.0  # capped


def test_unparseable_retry_after_falls_back_to_backoff():
    jira = FakeJira(read_script=[(429, {"Retry-After": "soon"})])
    key = jira.add_issue([])
    sleeps: list[float] = []
    jira.client(sleep=sleeps.append).get_issue(key, ["summary"])
    assert sleeps == [0.5]


def test_read_retries_are_bounded():
    jira = FakeJira(read_script=["timeout"] * 5)
    with pytest.raises(JiraUnavailable, match="3 attempts"):
        jira.client(max_retries=2).get_issue("KAN-1", ["summary"])
    assert len(jira.requests) == 3


def test_auth_errors_are_not_retried():
    jira = FakeJira(read_script=[(401, {})])
    with pytest.raises(JiraAuthError):
        jira.client().get_issue("KAN-1", ["summary"])
    assert len(jira.requests) == 1


def test_search_follows_next_page_token():
    pages = [
        {"issues": [{"key": "KAN-1"}, {"key": "KAN-2"}], "nextPageToken": "t2", "isLast": False},
        {"issues": [{"key": "KAN-3"}], "isLast": True},
    ]
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=pages[len(bodies) - 1])

    client = JiraClient(BASE_URL, "e", "t", transport=httpx.MockTransport(handler))
    keys = [i["key"] for i in client.search_issues("project = KAN", ["summary"])]
    assert keys == ["KAN-1", "KAN-2", "KAN-3"]
    assert "nextPageToken" not in bodies[0] and bodies[1]["nextPageToken"] == "t2"


def test_browse_url():
    assert FakeJira().client().browse_url("KAN-5") == f"{BASE_URL}/browse/KAN-5"


def test_error_messages_never_contain_the_token():
    jira = FakeJira(create_script=[400])
    with pytest.raises(JiraError) as info:
        jira.client().create_issue(FIELDS)
    assert "token-123" not in str(info.value)


def test_build_jira_client_requires_configuration(make_settings):
    with pytest.raises(JiraError, match="not configured"):
        build_jira_client(make_settings())
    settings = make_settings(
        JIRA_BASE_URL=BASE_URL + "/", JIRA_EMAIL="bot@novatech.example", JIRA_API_TOKEN="t", JIRA_PROJECT_KEY="KAN"
    )
    assert build_jira_client(settings).base_url == BASE_URL
