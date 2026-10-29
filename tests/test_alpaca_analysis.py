"""Run-boundary wiring for read-only broker context (no external calls)."""
from contextlib import contextmanager
from queue import Queue
from types import SimpleNamespace

import pytest

from tradingagents.alpaca_portfolio import AlpacaPortfolioError
from tradingagents.portfolio import PortfolioContext


def test_python_run_reuses_resolved_book_for_checkpoint_and_execution(monkeypatch):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"alpaca_portfolio_enabled": True}
    book = PortfolioContext(cash=123, currency="USD")
    calls = []

    def resolve(supplied, config, day):
        calls.append(("resolve", supplied, day))
        return book

    @contextmanager
    def checkpoint(ticker, day, asset_type, portfolio):
        calls.append(("checkpoint", portfolio))
        yield "thread"

    def run(*args, **kwargs):
        calls.append(("execute", kwargs["portfolio"]))
        return {"result": "ok"}, "Hold"

    monkeypatch.setattr("tradingagents.alpaca_portfolio.resolve_portfolio", resolve)
    monkeypatch.setattr(graph, "checkpoint_scope", checkpoint)
    monkeypatch.setattr(graph, "_run_graph", run)
    assert graph.propagate("AAPL", "2020-01-02")[1] == "Hold"
    assert calls == [("resolve", None, "2020-01-02"), ("checkpoint", book), ("execute", book)]


def test_worker_uses_same_snapshot_for_state_and_checkpoint(monkeypatch, tmp_path):
    from tradingagents.web.worker import execute_run

    book = PortfolioContext(cash=123, currency="USD")
    calls = []

    class Graph:
        propagator = SimpleNamespace(get_graph_args=lambda: {})

        def create_run_state(self, *args, **kwargs):
            calls.append(("state", kwargs["portfolio"]))
            return {}

        def begin_checkpoint(self, *args, **kwargs):
            calls.append(("begin", kwargs["portfolio"]))
            return None

        def checkpoint_input(self, state):
            return state

        def stream_run(self, *args, **kwargs):
            yield [], {"final_rating": "Hold"}

        def record_decision(self, *args):
            calls.append(("record",))

        def clear_checkpoint_on_success(self, *args, **kwargs):
            calls.append(("clear", kwargs["portfolio"]))

        def end_checkpoint(self):
            calls.append(("end",))

        def save_reports(self, *args, **kwargs):
            calls.append(("save",))

    def resolve(*args):
        calls.append(("resolve",))
        return book

    monkeypatch.setattr("tradingagents.web.worker.resolve_portfolio", resolve)
    events = Queue()
    execute_run(events, {"ticker": "AAPL", "trade_date": "2020-01-02", "analysts": ["market"]},
                {}, tmp_path, graph_factory=lambda *a, **k: Graph())
    assert calls == [("resolve",), ("state", book), ("begin", book), ("record",),
                     ("clear", book), ("end",), ("save",)]
    output = []
    while not events.empty():
        output.append(events.get_nowait())
    assert output[-1]["type"] == "completed"


def test_worker_stops_before_graph_creation_on_portfolio_failure(monkeypatch, tmp_path):
    from tradingagents.web.worker import execute_run

    def fail(*args):
        raise AlpacaPortfolioError("private details")

    def forbidden(*args, **kwargs):
        pytest.fail("graph must not be constructed")

    monkeypatch.setattr("tradingagents.web.worker.resolve_portfolio", fail)
    events = Queue()
    execute_run(events, {"ticker": "AAPL", "trade_date": "2020-01-02", "analysts": ["market"]},
                {}, tmp_path, graph_factory=forbidden)
    assert events.get_nowait() == {"type": "failed", "reason": "alpaca_portfolio"}
    assert events.empty()


def test_cli_stops_before_graph_creation_on_portfolio_failure(monkeypatch):
    import typer

    import cli.run as cli_run

    monkeypatch.setattr(cli_run, "get_user_selections", lambda flags: {"analysis_date": "2020-01-02"})
    monkeypatch.setattr(cli_run, "_build_run_config", lambda *args: {"alpaca_portfolio_enabled": True})

    def fail(*args):
        raise AlpacaPortfolioError("Portfolio unavailable")

    monkeypatch.setattr("tradingagents.alpaca_portfolio.resolve_portfolio", fail)
    with pytest.raises(typer.Exit) as exc:
        cli_run.run_analysis()
    assert exc.value.exit_code == 1
