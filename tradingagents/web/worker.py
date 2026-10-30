"""Spawn-safe research worker. Only allowlisted report text crosses into the server."""

import inspect
import logging
from pathlib import Path

from tradingagents.alpaca_portfolio import AlpacaPortfolioError, resolve_portfolio
from tradingagents.dataflows.symbols import crypto_base
from tradingagents.graph.activity import AGENT_IDS, SUMMARIES, published_agents
from tradingagents.paper_execution import execute_paper_decision, render_paper_execution
from tradingagents.reporting import manager_summary
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
        "analyst_status": {a: "completed" if a in sections else "pending" for a in ANALYSTS},
        "published_agents": published_agents(state),
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

        ticker, day = selection["ticker"], selection["trade_date"]
        portfolio = resolve_portfolio(None, config, day)
        graph = graph_factory(selection["analysts"], config=config, debug=False)
        asset_type = "crypto" if crypto_base(ticker) else "stock"
        events.put({"type": "running"})
        try:
            portfolio_args = {"portfolio": portfolio} if portfolio is not None else {}
            state = graph.create_run_state(ticker, day, asset_type=asset_type, **portfolio_args)
            args = graph.propagator.get_graph_args()
            thread_id = graph.begin_checkpoint(ticker, day, asset_type=asset_type, **portfolio_args)
            if thread_id is not None:
                args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = (
                    thread_id
                )
            final_state = {}
            def activity_callback(activity):
                agent, kind = activity.get("agent"), activity.get("kind")
                if agent not in AGENT_IDS or kind not in SUMMARIES:
                    return
                event = {"type": "activity", "agent": agent, "kind": kind,
                         "summary": SUMMARIES[kind]}
                if kind == "completed" and isinstance(activity.get("output"), str):
                    event["output"] = activity["output"][:32_000]
                events.put(event)

            # Older adapters/fakes may forward **args blindly to LangGraph.
            # Only pass this local extension when explicitly supported.
            if "activity_callback" in inspect.signature(graph.stream_run).parameters:
                args["activity_callback"] = activity_callback
            for _messages, chunk in graph.stream_run(graph.checkpoint_input(state), **args):
                if chunk:
                    final_state.update(chunk)
                    events.put({"type": "progress", **progress(final_state, selection["analysts"])})
            graph.record_decision(ticker, day, final_state)
            graph.clear_checkpoint_on_success(ticker, day, asset_type=asset_type, **portfolio_args)
        finally:
            graph.end_checkpoint()
        # A unique directory owned by this run, never a browser-supplied path.
        report_state = dict(final_state)
        if report_state.get("memory_note"):
            report_state["memory_note"] = progress(final_state)["memory_note"]
        graph.save_reports(report_state, ticker, Path(report_dir), html=True)
        execution_report = ""
        if config.get("alpaca_paper_execution_enabled") is True:
            try:
                execution = execute_paper_decision(
                    final_state, ticker, day, str(Path(report_dir).resolve()), config
                )
                execution_report = render_paper_execution(execution)
            except Exception as exc:
                LOG.error("Paper execution failed unexpectedly (%s)", type(exc).__name__)
                execution_report = (
                    "### Alpaca paper execution\n\nStatus: **unknown**. "
                    "Check Alpaca before another run; an unexpected execution error occurred."
                )
            report_state["paper_execution_report"] = execution_report
            try:
                graph.save_reports(report_state, ticker, Path(report_dir), html=True)
            except Exception as exc:
                LOG.error("Paper execution report export failed (%s)", type(exc).__name__)
                execution_report += "\n\nExecution result could not be saved to the report; check Alpaca and the local execution journal."
        events.put(
            {"type": "completed", **progress(final_state, selection["analysts"]),
             "rating": run_rating(final_state), "manager_summary": manager_summary(final_state),
             "paper_execution_report": execution_report}
        )
    except Exception as exc:
        # Error disclosure policy: see tradingagents-web SPEC.
        LOG.error("Research worker failed (%s)", type(exc).__name__)
        failure = {"type": "failed"}
        if isinstance(exc, AlpacaPortfolioError):
            failure["reason"] = "alpaca_portfolio"
        events.put(failure)
