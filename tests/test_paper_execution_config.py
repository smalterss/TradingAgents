"""Paper execution is an explicit opt-in; credential presence is not authorization."""
import pytest

from tradingagents.default_config import build_default_config
from tradingagents.web.config import public_config


def test_paper_execution_defaults_off_even_with_credentials(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_ALPACA_PAPER_EXECUTION_ENABLED", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    assert build_default_config()["alpaca_paper_execution_enabled"] is False


def test_execution_opt_in_is_typed(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ALPACA_PAPER_EXECUTION_ENABLED", "true")
    assert build_default_config()["alpaca_paper_execution_enabled"] is True
    monkeypatch.setenv("TRADINGAGENTS_ALPACA_PAPER_EXECUTION_ENABLED", "not-a-boolean")
    with pytest.raises(ValueError, match="TRADINGAGENTS_ALPACA_PAPER_EXECUTION_ENABLED"):
        build_default_config()


def test_public_execution_indicator_only_exposes_boolean(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-private-key")
    base = build_default_config()
    base["alpaca_paper_execution_enabled"] = True
    public = public_config(base, "csrf-test")
    assert public["paper_execution_enabled"] is True
    assert "test-private-key" not in str(public)
