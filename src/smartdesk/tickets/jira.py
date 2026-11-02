"""Thin Jira Cloud REST API v3 adapter.

Reads (GET, search) are idempotent and get bounded retries with exponential
backoff on timeouts, 429 and 5xx, honouring `Retry-After` on 429. Issue
creation is never retried here: `create_issue` classifies a failure as either
definite (nothing was created) or ambiguous (it may have been), and leaves
retrying to the service, which reconciles first.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from smartdesk.config import Settings
from smartdesk.tickets.models import JiraAuthError, JiraError, JiraRequestRejected, JiraUnavailable

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_BACKOFF_BASE_SECONDS = 0.5
_MAX_RETRY_AFTER_SECONDS = 30.0
_PAGE_SIZE = 50


class AmbiguousCreateError(JiraError):
    """The create request may have reached Jira, but no answer came back."""


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse `Retry-After` (delta-seconds or HTTP date), capped so a bad header cannot stall a turn."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase or "no detail"
    messages = list(body.get("errorMessages") or [])
    messages += [f"{field}: {message}" for field, message in (body.get("errors") or {}).items()]
    return "; ".join(messages) or response.reason_phrase or "no detail"


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            auth=(email, api_token),
            timeout=timeout,
            headers={"Accept": "application/json"},
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    # --- writes (never retried here) ---

    def create_issue(self, fields: dict[str, Any]) -> str:
        """POST /rest/api/3/issue and return the new issue key.

        Raises JiraUnavailable when the request definitely did not reach Jira,
        JiraAuthError/JiraRequestRejected on a 4xx (nothing created), and
        AmbiguousCreateError when the issue may or may not exist.
        """
        try:
            response = self._http.post("/rest/api/3/issue", json={"fields": fields})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise JiraUnavailable(f"could not connect to Jira: {type(exc).__name__}") from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise AmbiguousCreateError(f"no response to create request: {type(exc).__name__}") from exc

        if response.status_code >= 500:
            raise AmbiguousCreateError(f"Jira returned {response.status_code} to create request")
        if response.status_code == 429:
            raise JiraUnavailable("Jira rate limit hit on create; nothing was created")
        self._raise_for_client_error(response)
        return str(response.json()["key"])

    def delete_issue(self, key: str) -> None:
        response = self._http.delete(f"/rest/api/3/issue/{key}")
        self._raise_for_client_error(response)

    def transition_issue(self, key: str, transition_id: str) -> None:
        response = self._http.post(f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition_id}})
        self._raise_for_client_error(response)

    # --- reads (bounded retries) ---

    def get_issue(self, key: str, fields: list[str]) -> dict[str, Any] | None:
        response = self._read("GET", f"/rest/api/3/issue/{key}", params={"fields": ",".join(fields)}, allow_404=True)
        return None if response is None else response.json()

    def get_comments(self, key: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        start = 0
        while True:
            response = self._read(
                "GET",
                f"/rest/api/3/issue/{key}/comment",
                params={"startAt": start, "maxResults": _PAGE_SIZE, "orderBy": "created"},
            )
            assert response is not None
            body = response.json()
            page = body.get("comments", [])
            comments.extend(page)
            start += len(page)
            if not page or start >= body.get("total", 0):
                return comments

    def get_transitions(self, key: str) -> list[dict[str, Any]]:
        response = self._read("GET", f"/rest/api/3/issue/{key}/transitions")
        assert response is not None
        return response.json().get("transitions", [])

    def search_issues(self, jql: str, fields: list[str], max_results: int = 100) -> list[dict[str, Any]]:
        """POST /rest/api/3/search/jql, following `nextPageToken` up to `max_results` issues."""
        issues: list[dict[str, Any]] = []
        token: str | None = None
        while len(issues) < max_results:
            payload: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": min(_PAGE_SIZE, max_results)}
            if token:
                payload["nextPageToken"] = token
            response = self._read("POST", "/rest/api/3/search/jql", json=payload)
            assert response is not None
            body = response.json()
            issues.extend(body.get("issues", []))
            token = body.get("nextPageToken")
            if not token or body.get("isLast", False):
                break
        return issues[:max_results]

    def _read(self, method: str, url: str, *, allow_404: bool = False, **kwargs: Any) -> httpx.Response | None:
        for attempt in range(self.max_retries + 1):
            last_attempt = attempt == self.max_retries
            try:
                response = self._http.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if last_attempt:
                    raise JiraUnavailable(
                        f"Jira read failed after {attempt + 1} attempts: {type(exc).__name__}"
                    ) from exc
                self._backoff(attempt, None)
                continue

            if response.status_code in _RETRYABLE_STATUS:
                if last_attempt:
                    raise JiraUnavailable(f"Jira returned {response.status_code} after {attempt + 1} attempts")
                self._backoff(attempt, _retry_after_seconds(response) if response.status_code == 429 else None)
                continue
            if allow_404 and response.status_code == 404:
                return None
            self._raise_for_client_error(response)
            return response
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        delay = retry_after if retry_after is not None else _BACKOFF_BASE_SECONDS * 2**attempt
        log.info("Retrying Jira read in %.1fs (attempt %d)", delay, attempt + 1)
        self._sleep(delay)

    @staticmethod
    def _raise_for_client_error(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise JiraAuthError(f"Jira refused the credentials or permission ({response.status_code})")
        if response.status_code >= 400:
            raise JiraRequestRejected(response.status_code, _error_detail(response))


def build_jira_client(settings: Settings) -> JiraClient:
    if not settings.jira_configured:
        raise JiraError("Jira is not configured; set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN and JIRA_PROJECT_KEY")
    assert settings.jira_base_url and settings.jira_email and settings.jira_api_token
    return JiraClient(
        settings.jira_base_url,
        settings.jira_email,
        settings.jira_api_token.get_secret_value(),
        timeout=settings.jira_timeout_seconds,
        max_retries=settings.jira_max_retries,
    )
