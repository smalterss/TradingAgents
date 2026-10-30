"""Only completed, opted-in browser work may reach the paper-order boundary."""
from copy import deepcopy
from queue import Queue
from types import SimpleNamespace

import pytest

from tradingagents.paper_execution import render_paper_execution
from tradingagents.reporting import write_report_tree
from tradingagents.web import worker
from tradingagents.web.app import RunManager, idle_snapshot


@pytest.fixture
def run_fixture(monkeypatch, tmp_path):
    calls = []
    saved = []
    final = {"final_rating": "Buy", "final_trade_decision": "**Rating**: Buy",
             "portfolio_decision_structured": True, "buy_notional_usd": 25.0,
             "portfolio_context": "Cash available: 100 USD"}

    class Graph:
        propagator = SimpleNamespace(get_graph_args=lambda: {})

        def create_run_state(self, *args, **kwargs):
            return {}

        def begin_checkpoint(self, *args, **kwargs):
            return None

        def checkpoint_input(self, state):
            return state

        def stream_run(self, *args, **kwargs):
            if getattr(self, "fail_stream", False):
                raise RuntimeError("PRIVATE ERROR")
            yield [], final

        def record_decision(self, *args):
            calls.append("record")

        def clear_checkpoint_on_success(self, *args, **kwargs):
            calls.append("clear")

        def end_checkpoint(self):
            calls.append("end")

        def save_reports(self, state, *args, **kwargs):
            calls.append("save")
            saved.append(deepcopy(state))
            if len(saved) == getattr(self, "fail_save_number", 0):
                raise RuntimeError("PRIVATE ERROR")

    graph = Graph()
    monkeypatch.setattr(worker, "resolve_portfolio", lambda *args: None)
    result = {"status": "submitted", "reason": "The broker confirmed the paper order; submission is not a fill.",
              "symbol": "AAPL", "side": "buy", "notional": "25.00", "broker_status": "accepted"}

    def execute(state, ticker, day, run_key, config):
        assert state == final
        assert ticker == "AAPL"
        assert run_key == str(tmp_path.resolve())
        assert saved and "paper_execution_report" not in saved[0]
        calls.append("execute")
        return result

    monkeypatch.setattr(worker, "execute_paper_decision", execute)

    def run(enabled=True):
        queue = Queue()
        worker.execute_run(queue, {"ticker": "AAPL", "trade_date": "2026-06-15", "analysts": ["market"]},
                           {"alpaca_paper_execution_enabled": enabled}, tmp_path,
                           graph_factory=lambda *a, **k: graph)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return events

    return run, graph, calls, saved, result


def test_only_enabled_completion_submits_and_reports(run_fixture):
    run, _, calls, saved, result = run_fixture
    events = run()
    assert calls == ["record", "clear", "end", "save", "execute", "save"]
    assert events[-1]["type"] == "completed"
    assert events[-1]["paper_execution_report"] == render_paper_execution(result)
    assert saved[-1]["paper_execution_report"] == events[-1]["paper_execution_report"]
    assert "filled" not in result["status"]


def test_disabled_browser_does_not_call_order_boundary(run_fixture):
    run, _, calls, _, _ = run_fixture
    assert run(False)[-1]["paper_execution_report"] == ""
    assert "execute" not in calls


@pytest.mark.parametrize("failure", ["stream", "initial_export"])
def test_failed_research_or_export_never_submits(run_fixture, failure):
    run, graph, calls, _, _ = run_fixture
    if failure == "stream":
        graph.fail_stream = True
    else:
        graph.fail_save_number = 1
    assert run()[-1]["type"] == "failed"
    assert "execute" not in calls


def test_post_submission_export_failure_preserves_visible_outcome(run_fixture):
    run, graph, calls, _, _ = run_fixture
    graph.fail_save_number = 2
    event = run()[-1]
    assert event["type"] == "completed"
    assert "Status: **submitted**" in event["paper_execution_report"]
    assert "could not be saved" in event["paper_execution_report"]
    assert "PRIVATE" not in str(event)
    assert calls.count("execute") == 1


def test_unexpected_executor_failure_is_unknown_not_silent_success(run_fixture, monkeypatch):
    run, _, _, _, _ = run_fixture

    def fail(*args):
        raise RuntimeError("PRIVATE ERROR")

    monkeypatch.setattr(worker, "execute_paper_decision", fail)
    event = run()[-1]
    assert event["type"] == "completed"
    assert "Status: **unknown**" in event["paper_execution_report"]
    assert "PRIVATE" not in str(event)


def test_execution_report_exports_and_cleans_up(tmp_path):
    state = {"final_trade_decision": "**Rating**: Hold", "paper_execution_report": "Skipped: market closed."}
    write_report_tree(state, "AAPL", tmp_path)
    assert (tmp_path / "6_paper_execution" / "execution.md").read_text() == state["paper_execution_report"]
    for name in ("complete_report.md", "complete_report.html"):
        assert "Skipped: market closed." in (tmp_path / name).read_text(encoding="utf-8")
    write_report_tree({"final_trade_decision": "**Rating**: Hold"}, "AAPL", tmp_path)
    assert not (tmp_path / "6_paper_execution" / "execution.md").exists()


def test_execution_html_is_sanitized_and_only_visible_after_completion():
    manager = RunManager({})
    manager.current = {**idle_snapshot(), "status": "running"}
    manager.events = Queue()
    manager.events.put({"type": "progress", "paper_execution_report": "NOT FINAL"})
    assert manager.snapshot()["paper_execution"] is None
    manager.events.put({"type": "completed", "paper_execution_report": "Status: **submitted** <script>bad()</script>"})
    html = manager.snapshot()["paper_execution"]
    assert "<strong>submitted</strong>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
