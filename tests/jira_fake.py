"""An in-memory Jira Cloud served through httpx.MockTransport.

It implements just the endpoints SmartDesk uses, so tests exercise the real
JiraClient (URLs, payloads, error classification) without network access.
Failures are scripted per endpoint:

- `create_script`: actions consumed by successive POST /issue calls:
  "ok", "timeout_after_create" (issue is created but the response is lost),
  "timeout_before_create", "connect_error", "500_after_create", or an int status code.
- `read_script`: actions consumed by successive read requests: "ok", "timeout",
  or (status_code, headers).
- `search_lag`: number of upcoming searches that return no issues, simulating
  Jira's eventually consistent search index.
- `on_search`: a one-shot callable run at the start of the next search request
  (cleared before it runs), e.g. to interleave a second caller deterministically.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from smartdesk.tickets.jira import JiraClient

BASE_URL = "https://novatech-test.atlassian.net"


@dataclass
class FakeJira:
    project_key: str = "KAN"
    issues: dict[str, dict[str, Any]] = field(default_factory=dict)
    comments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    create_script: list[Any] = field(default_factory=list)
    read_script: list[Any] = field(default_factory=list)
    search_lag: int = 0
    on_search: Callable[[], None] | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    _counter: int = 0
    _clock: int = 0

    # --- helpers for tests ---

    def add_issue(self, labels: list[str], summary: str = "Existing issue", status: str = "To Do",
                  status_category: str = "To Do", **fields: Any) -> str:
        self._counter += 1
        self._clock += 1
        key = f"{self.project_key}-{self._counter}"
        stamp = f"2026-11-01T10:{self._clock:02d}:00.000+0000"
        self.issues[key] = {
            "key": key,
            "fields": {
                "summary": summary,
                "labels": list(labels),
                "status": {"name": status, "statusCategory": {"name": status_category}},
                "priority": {"name": "Medium"},
                "created": stamp,
                "updated": stamp,
                "description": None,
                **fields,
            },
        }
        return key

    def posts_to_create(self) -> int:
        return sum(1 for r in self.requests if r.method == "POST" and r.url.path == "/rest/api/3/issue")

    def searches(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/rest/api/3/search/jql"]

    def client(self, **kwargs: Any) -> JiraClient:
        return JiraClient(
            BASE_URL, "bot@novatech.example", "token-123",
            transport=httpx.MockTransport(self.handle), sleep=kwargs.pop("sleep", lambda s: None), **kwargs,
        )

    # --- transport ---

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/rest/api/3/issue":
            return self._create(request)

        action = self.read_script.pop(0) if self.read_script else "ok"
        if action == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(action, tuple):
            status, headers = action
            return httpx.Response(status, headers=headers, json={"errorMessages": ["scripted"]})

        if request.method == "POST" and path == "/rest/api/3/search/jql":
            if (hook := self.on_search) is not None:
                self.on_search = None
                hook()
            return self._search(json.loads(request.content))
        match = re.fullmatch(r"/rest/api/3/issue/([A-Z0-9_]+-\d+)(/comment)?", path)
        if match and request.method == "GET":
            key = match.group(1)
            if key not in self.issues:
                return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})
            if match.group(2):
                found = self.comments.get(key, [])
                return httpx.Response(200, json={"comments": found, "total": len(found), "startAt": 0})
            return httpx.Response(200, json=self.issues[key])
        return httpx.Response(404, json={"errorMessages": [f"unhandled {request.method} {path}"]})

    def _create(self, request: httpx.Request) -> httpx.Response:
        action = self.create_script.pop(0) if self.create_script else "ok"
        if action == "connect_error":
            raise httpx.ConnectError("connection refused", request=request)
        if action == "timeout_before_create":
            raise httpx.ReadTimeout("timed out", request=request)
        if isinstance(action, int):
            return httpx.Response(action, json={"errorMessages": ["scripted"], "errors": {"summary": "bad"}})

        fields = json.loads(request.content)["fields"]
        key = self.add_issue(fields["labels"], summary=fields["summary"], description=fields.get("description"))
        if action == "timeout_after_create":
            raise httpx.ReadTimeout("timed out", request=request)
        if action == "500_after_create":
            return httpx.Response(500, json={"errorMessages": ["internal error"]})
        return httpx.Response(201, json={"id": "10001", "key": key, "self": f"{BASE_URL}/rest/api/3/issue/{key}"})

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        if self.search_lag > 0:
            self.search_lag -= 1
            return httpx.Response(200, json={"issues": [], "isLast": True})
        label = re.search(r'labels = "([^"]+)"', body["jql"])
        found = [i for i in self.issues.values() if label and label.group(1) in i["fields"]["labels"]]
        if "ORDER BY updated DESC" in body["jql"]:
            found.sort(key=lambda i: i["fields"]["updated"], reverse=True)
        else:
            found.sort(key=lambda i: i["fields"]["created"])
        wanted = set(body.get("fields", []))
        issues = [{"key": i["key"], "fields": {k: v for k, v in i["fields"].items() if k in wanted}} for i in found]
        return httpx.Response(200, json={"issues": issues[: body.get("maxResults", 50)], "isLast": True})
