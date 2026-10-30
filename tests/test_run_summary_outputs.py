"""Completion summaries cross presentation boundaries without live account access."""
from io import StringIO
from queue import Queue

import pytest
from rich.console import Console

from tradingagents.web.app import RunManager, idle_snapshot


def manager_with_queue():
    manager = RunManager({})
    manager.current = {**idle_snapshot(), "status": "running"}
    manager.events = Queue()
    return manager


def test_completion_summary_allowlists_and_safely_renders_input():
    manager = manager_with_queue()
    manager.events.put({"type": "completed", "rating": "Hold", "manager_summary": {
        "portfolio": 'Cash: 500 USD <script>alert(1)</script>',
        "recommendation": "**Hold** the 10 units. ![x](https://evil.invalid/x)",
        "api_key": "MUST NOT APPEAR",
    }})
    snapshot = manager.snapshot()
    summary = snapshot["manager_summary"]
    assert set(summary) == {"portfolio", "recommendation"}
    assert "500 USD" in summary["portfolio"]
    assert "<script>" not in summary["portfolio"]
    assert "&lt;script&gt;" in summary["portfolio"]
    assert "<img" not in summary["recommendation"]
    assert "<strong>Hold</strong>" in summary["recommendation"]
    assert "MUST NOT APPEAR" not in str(snapshot)
    assert manager.snapshot()["manager_summary"] == summary


@pytest.mark.parametrize("kind", ["progress", "failed"])
def test_noncompletion_does_not_publish_final_summary(kind):
    manager = manager_with_queue()
    manager.events.put({"type": kind, "manager_summary": {"portfolio": "private", "recommendation": "Buy"}})
    assert manager.snapshot()["manager_summary"] is None


def test_cli_prints_original_context_and_recommendation(monkeypatch):
    import cli.run as cli_run

    output = StringIO()
    monkeypatch.setattr(cli_run, "console", Console(file=output, width=110, color_system=None))
    cli_run._display_manager_summary({
        "portfolio_context": "Cash available: 123.45 USD\nNo current position in AAPL",
        "final_trade_decision": "**Rating: Hold**\nWait for earnings. Do not buy yet.",
    })
    text = output.getvalue()
    for part in ("123.45 USD", "No current position in AAPL", "Rating: Hold", "Wait for earnings.", "No order has been placed"):
        assert part in text


def test_worker_emits_captured_manager_input(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tradingagents.web.worker import execute_run

    context = "Cash available: 999.00 USD\nCurrent position in AAPL: 5 units"
    decision = "Rating: Hold\nMaintain the five units."

    class Graph:
        propagator = SimpleNamespace(get_graph_args=lambda: {})

        def create_run_state(self, *args, **kwargs):
            return {}

        def begin_checkpoint(self, *args, **kwargs):
            return None

        def checkpoint_input(self, state):
            return state

        def stream_run(self, *args, **kwargs):
            yield [], {"portfolio_context": context, "final_trade_decision": decision}

        def record_decision(self, *args):
            pass

        def clear_checkpoint_on_success(self, *args, **kwargs):
            pass

        def end_checkpoint(self):
            pass

        def save_reports(self, state, *args, **kwargs):
            assert state["portfolio_context"] == context

    monkeypatch.setattr("tradingagents.web.worker.resolve_portfolio", lambda *args: None)
    events = Queue()
    execute_run(events, {"ticker": "AAPL", "trade_date": "2020-01-02", "analysts": ["market"]},
                {}, tmp_path, graph_factory=lambda *args, **kwargs: Graph())
    output = []
    while not events.empty():
        output.append(events.get_nowait())
    assert output[-1]["type"] == "completed"
    assert output[-1]["manager_summary"] == {"portfolio": context, "recommendation": decision, "rating": "Hold"}
