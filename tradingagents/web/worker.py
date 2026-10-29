"""Spawn-safe research worker. Only allowlisted report text crosses into the server."""

import logging
from pathlib import Path

from tradingagents.dataflows.symbols import crypto_base
from tradingagents.web.config import ANALYSTS

LOG = logging.getLogger(__name__)
TITLES = {
    "overview": "Run overview",
    "market": "Market analysis",
    "social": "Sentiment analysis",
    "news": "News analysis",
    "fundamentals": "Fundamentals analysis",
    "research": "Research debate",
    "trader": "Trading plan",
    "risk": "Risk debate",
    "decision": "Portfolio decision",
}
FIELDS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
    "trader": "trader_investment_plan",
    "decision": "final_trade_decision",
}


def progress(state, selected_analysts=ANALYSTS):
    sections = {
        key: state[field]
        for key, field in FIELDS.items()
        if isinstance(state.get(field), str) and state[field]
    }
    for section, field, histories, final in (
        (
            "research",
            "investment_debate_state",
            ("bull_history", "bear_history"),
            "investment_plan",
        ),
        (
            "risk",
            "risk_debate_state",
            ("aggressive_history", "conservative_history", "neutral_history"),
            None,
        ),
    ):
        debate = state.get(field) or {}
        texts = [debate[k] for k in histories if isinstance(debate.get(k), str) and debate[k]]
        if final and state.get(final):
            texts.append(state[final])
        if texts:
            sections[section] = "\n\n".join(texts)
    if "decision" in sections:
        stage = "decision"
    elif "risk" in sections or "trader" in sections:
        stage = "risk"
    elif state.get("investment_plan"):
        stage = "trader"
    elif "research" in sections or all(a in sections for a in selected_analysts):
        stage = "research"
    else:
        stage = "analysts"
    return {
        "sections": sections,
        "stage": stage,
        "analyst_status": {a: "completed" if a in sections else "running" for a in ANALYSTS},
        # Error disclosure policy: see tradingagents-web SPEC.
        "memory_note": "Past decision memory could not be fully updated or loaded. Research continued; unresolved decisions remain pending."
        if state.get("memory_note")
        else "",
    }


def execute_run(events, selection, config, report_dir, graph_factory=None):
    """Use exactly the graph's streaming/recording/checkpoint lifecycle, without CLI imports."""
    graph = None
    try:
        if graph_factory is None:
            from tradingagents.graph.trading_graph import TradingAgentsGraph

            graph_factory = TradingAgentsGraph
        from tradingagents.agents.rating import run_rating

        graph = graph_factory(selection["analysts"], config=config, debug=False)
        ticker, day = selection["ticker"], selection["trade_date"]
        asset_type = "crypto" if crypto_base(ticker) else "stock"
        events.put({"type": "running"})
        try:
            state = graph.create_run_state(ticker, day, asset_type=asset_type)
            args = graph.propagator.get_graph_args()
            thread_id = graph.begin_checkpoint(ticker, day, asset_type=asset_type)
            if thread_id is not None:
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = (
                    thread_id
                )
            final_state = {}
            for _messages, chunk in graph.stream_run(graph.checkpoint_input(state), **args):
                if chunk:
                    final_state.update(chunk)
                    events.put({"type": "progress", **progress(final_state, selection["analysts"])})
            graph.record_decision(ticker, day, final_state)
            graph.clear_checkpoint_on_success(ticker, day, asset_type=asset_type)
        finally:
            graph.end_checkpoint()
        # A unique directory owned by this run, never a browser-supplied path.
        report_state = dict(final_state)
        if report_state.get("memory_note"):
            report_state["memory_note"] = progress(final_state)["memory_note"]
        graph.save_reports(report_state, ticker, Path(report_dir), html=True)
        events.put(
            {"type": "completed", **progress(final_state, selection["analysts"]), "rating": run_rating(final_state)}
        )
    except Exception as exc:
        # Error disclosure policy: see tradingagents-web SPEC.
        LOG.error("Research worker failed (%s)", type(exc).__name__)
        events.put({"type": "failed"})
