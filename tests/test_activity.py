"""Safe public activity projections; no providers or broker calls."""

from queue import Queue

import pytest

from tradingagents.graph.activity import AGENT_IDS, task_activity
from tradingagents.web.app import ACTIVITY_LIMIT, RunManager


def test_task_allowlist_and_private_payloads():
    secret = "PRIVATE arguments credentials raw tool response"
    assert task_activity((), {"name": secret, "input": secret}) is None
    assert task_activity(("Memory Log:123",), {"name": "tools"}) is None
    assert task_activity(("Market Analyst:123",), {"name": "agent", "result": {"messages": secret}}) is None
    for name, expected in (("tools", "tool_completed"),):
        event = task_activity(("Market Analyst:123",), {
            "name": name, "input": secret, "result": {"messages": secret, "market_report": secret}})
        assert event == {"agent": "market", "kind": expected,
                         "summary": "Evidence tool activity completed."}
    failed = task_activity((), {"name": "Trader", "error": secret})
    assert failed == {"agent": "trader", "kind": "failed", "summary": "Agent failed."}
    published = task_activity((), {"name": "Trader", "result": {
        "trader_investment_plan": "Published plan", "messages": secret, "past_context": secret}})
    assert published["output"] == "Published plan"
    assert secret not in str(published)


def manager(tmp_path):
    runs = RunManager({"results_dir": str(tmp_path)})
    runs.current.update(status="running", selected_analysts=["market"])
    runs.events = Queue()
    return runs


def test_retention_fixed_fields_html_and_monotonic_sequence(tmp_path):
    runs = manager(tmp_path)
    runs.events.put({"type": "activity", "agent": "SECRET", "kind": "started"})
    runs.events.put({"type": "activity", "agent": "news", "kind": "started"})
    for _ in range(ACTIVITY_LIMIT + 3):
        runs.events.put({"type": "activity", "agent": "bull", "kind": "completed",
                         "summary": "SECRET", "timestamp": "SECRET", "raw_log": "SECRET",
                         "output": '<script>alert(1)</script> [link](https://secret.invalid)'})
    snapshot = runs.snapshot()
    assert len(snapshot["activity"]) == ACTIVITY_LIMIT
    assert [e["seq"] for e in snapshot["activity"]] == list(range(4, ACTIVITY_LIMIT + 4))
    assert "SECRET" not in str(snapshot)
    item = snapshot["activity"][0]
    assert set(item) == {"seq", "agent", "kind", "summary", "timestamp", "output_html"}
    assert "<script>" not in item["output_html"] and "href=" not in item["output_html"]
    snapshot["activity"].clear()
    assert len(runs.snapshot()["activity"]) == ACTIVITY_LIMIT


@pytest.mark.parametrize("terminal,expected", [("failed", "failed"), ("completed", "failed"), ("stopped", "stopped")])
def test_lifecycle_only_observed_agents_run(tmp_path, terminal, expected):
    runs = manager(tmp_path)
    assert set(runs.snapshot()["agent_status"]) == set(AGENT_IDS)
    runs.events.put({"type": "running"})
    assert set(runs.snapshot()["agent_status"].values()) == {"queued"}
    runs.events.put({"type": "activity", "agent": "market", "kind": "started"})
    runs.events.put({"type": "activity", "agent": "bull", "kind": "completed"})
    runs.events.put({"type": "activity", "agent": "market", "kind": "tool_completed"})
    assert runs.snapshot()["agent_status"]["market"] == "running"
    if terminal == "stopped":
        result = runs.stop()
    else:
        runs.events.put({"type": terminal})
        result = runs.snapshot()
    assert result["agent_status"]["market"] == expected
    assert result["agent_status"]["bull"] == "completed"
    assert result["agent_status"]["trader"] == "queued"
    runs.events.put({"type": "activity", "agent": "trader", "kind": "started"})
    assert runs.snapshot()["agent_status"]["trader"] == "queued"
