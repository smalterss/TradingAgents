"""Public activity projection. Never expose task inputs, messages or error details."""

AGENT_NODES = {
    "Market Analyst": "market", "Sentiment Analyst": "social",
    "News Analyst": "news", "Fundamentals Analyst": "fundamentals",
    "Bull Researcher": "bull", "Bear Researcher": "bear",
    "Research Manager": "research_manager", "Trader": "trader",
    "Aggressive Analyst": "aggressive", "Conservative Analyst": "conservative",
    "Neutral Analyst": "neutral", "Portfolio Manager": "portfolio_manager",
}
AGENT_IDS = tuple(AGENT_NODES.values())
SUMMARIES = {
    "started": "Agent started.", "completed": "Agent completed.",
    "failed": "Agent failed.", "tool_started": "Evidence tool activity started.",
    "tool_completed": "Evidence tool activity completed.",
    "tool_failed": "Evidence tool activity failed.",
}
REPORT_FIELDS = {
    "market": "market_report", "social": "sentiment_report", "news": "news_report",
    "fundamentals": "fundamentals_report", "research_manager": "investment_plan",
    "trader": "trader_investment_plan", "portfolio_manager": "final_trade_decision",
}


def task_activity(namespace, chunk):
    """Map genuine LangGraph task start/result events to an allowlisted record."""
    if not isinstance(chunk, dict):
        return None
    tool = False
    if namespace:
        # Analyst subgraph task names are generic; identity comes only from its parent.
        parent = namespace[0].split(":", 1)[0]
        agent = AGENT_NODES.get(parent)
        if agent not in ("market", "social", "news", "fundamentals") or chunk.get("name") != "tools":
            return None
        tool = True
    else:
        agent = AGENT_NODES.get(chunk.get("name"))
    if agent is None:
        return None
    finished = "result" in chunk or "error" in chunk
    kind = "failed" if chunk.get("error") else "completed" if finished else "started"
    if tool:
        kind = "tool_" + kind
    event = {"agent": agent, "kind": kind, "summary": SUMMARIES[kind]}
    if kind == "completed":
        result = chunk.get("result")
        if isinstance(result, (list, tuple)):
            result = dict(result)
        if isinstance(result, dict):
            output = result.get(REPORT_FIELDS.get(agent))
            if agent in ("bull", "bear"):
                debate = result.get("investment_debate_state")
                output = debate.get("current_response") if isinstance(debate, dict) else None
            elif agent in ("aggressive", "conservative", "neutral"):
                debate = result.get("risk_debate_state")
                output = debate.get(f"current_{agent}_response") if isinstance(debate, dict) else None
            if isinstance(output, str) and output:
                event["output"] = output
    return event
