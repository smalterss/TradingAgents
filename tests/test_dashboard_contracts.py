"""Regression checks for the dashboard's shared research contracts."""

from queue import Queue

import pytest

from tradingagents.default_config import build_default_config
from tradingagents.web.config import credential_status, public_config
from tradingagents.web.worker import execute_run, progress


def test_model_suggestions_never_offer_cli_custom_sentinel():
    public = public_config(build_default_config(), "test-only-token")
    assert all(model["id"] != "custom" for provider in public["providers"] for model in provider["models"])
    assert next(p for p in public["providers"] if p["id"] == "openai_compatible")["models"] == []


@pytest.mark.parametrize("ticker,expected", [("BTC-USD", "crypto"), ("0700.HK", "stock")])
def test_worker_passes_asset_mode_through_checkpoint_lifecycle(tmp_path, ticker, expected):
    calls = []

    class Graph:
        def __init__(self, *args, **kwargs):
            self.propagator = self

        def get_graph_args(self):
            return {}

        def create_run_state(self, ticker, day, asset_type):
            calls.append(("state", asset_type))
            return {}

        def begin_checkpoint(self, ticker, day, asset_type):
            calls.append(("begin", asset_type))

        def checkpoint_input(self, state):
            return state

        def stream_run(self, state, **kwargs):
            yield [], {"final_trade_decision": "Rating: Hold"}

        def record_decision(self, *args):
            calls.append(("record", None))

        def clear_checkpoint_on_success(self, ticker, day, asset_type):
            calls.append(("clear", asset_type))

        def end_checkpoint(self):
            calls.append(("end", None))

        def save_reports(self, *args, **kwargs):
            calls.append(("save", None))

    events = Queue()
    execute_run(events, {"ticker": ticker, "trade_date": "2025-01-02", "analysts": ["market"]},
                {}, tmp_path, graph_factory=Graph)
    assert calls == [("state", expected), ("begin", expected), ("record", None),
                     ("clear", expected), ("end", None), ("save", None)]
    completed = []
    while not events.empty():
        completed.append(events.get_nowait())
    assert completed[-1]["type"] == "completed"
    assert completed[-1]["rating"] == "Hold"


@pytest.mark.parametrize("state,stage", [
    ({"market_report": "Evidence"}, "research"),
    ({"market_report": "Evidence", "investment_plan": "Plan"}, "trader"),
    ({"trader_investment_plan": "Proposal"}, "risk"),
    ({"final_trade_decision": "Rating: Buy"}, "decision"),
])
def test_progress_moves_to_next_work_after_completed_outputs(state, stage):
    assert progress(state, ["market"])["stage"] == stage


def test_memory_note_is_actionable_without_disclosing_provider_text():
    note = progress({"memory_note": "Provider failed at https://secret?api_key=PRIVATE"})["memory_note"]
    assert "could not be fully updated or loaded" in note
    assert "PRIVATE" not in note and "https://" not in note


def test_bedrock_does_not_reject_implicit_credential_chain(monkeypatch):
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert credential_status("bedrock")[0]
