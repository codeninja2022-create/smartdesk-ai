import pytest

from smartdesk import observability
from smartdesk.redaction import langfuse_mask

pytestmark = pytest.mark.rubric("F3")


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    monkeypatch.setattr(observability, "_client", None)


def test_tracing_disabled_without_keys(make_settings, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Langfuse must not be constructed when disabled")

    monkeypatch.setattr(observability, "Langfuse", fail)
    assert observability.get_callbacks(make_settings()) == []
    observability.flush()  # no-op, must not raise


def test_tracing_enabled_installs_redaction_mask(make_settings, monkeypatch):
    created: dict = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            created.update(kwargs)

    class FakeHandler:
        def __init__(self, *, public_key):
            self.public_key = public_key

    monkeypatch.setattr(observability, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(observability, "CallbackHandler", FakeHandler)
    settings = make_settings(LANGFUSE_PUBLIC_KEY="pk-lf-abc", LANGFUSE_SECRET_KEY="sk-lf-xyz")

    callbacks = observability.get_callbacks(settings)

    assert created["mask"] is langfuse_mask
    assert created["public_key"] == "pk-lf-abc"
    assert created["secret_key"] == "sk-lf-xyz"
    assert len(callbacks) == 1 and callbacks[0].public_key == "pk-lf-abc"


def test_client_is_created_once(make_settings, monkeypatch):
    count = 0

    class FakeLangfuse:
        def __init__(self, **kwargs):
            nonlocal count
            count += 1

    monkeypatch.setattr(observability, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(observability, "CallbackHandler", lambda **kwargs: object())
    settings = make_settings(LANGFUSE_PUBLIC_KEY="pk-lf-abc", LANGFUSE_SECRET_KEY="sk-lf-xyz")

    observability.get_callbacks(settings)
    observability.get_callbacks(settings)
    assert count == 1
