import pytest

from security.secret_loader import SecretProvider, MissingSecretError


def test_require_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_MISSING_SECRET", raising=False)
    sp = SecretProvider()
    with pytest.raises(MissingSecretError):
        sp.require("SOME_MISSING_SECRET")


def test_require_returns_value_when_present(monkeypatch):
    monkeypatch.setenv("SOME_SECRET", "value-123")
    sp = SecretProvider()
    assert sp.require("SOME_SECRET") == "value-123"


def test_get_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    sp = SecretProvider()
    assert sp.get("MISSING_KEY", "fallback") == "fallback"
