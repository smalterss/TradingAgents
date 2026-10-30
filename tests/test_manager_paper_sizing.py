"""Manager sizing is structured-only; prose is never an order-size source."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.state import AgentState

pytestmark = pytest.mark.unit


def decision(**overrides):
    return PortfolioDecision(**{
        "rating": "Buy", "executive_summary": "Allocate 1250 USD from cash.",
        "investment_thesis": "Original full thesis, including opposing Sell call.",
        **overrides,
    })


@pytest.mark.parametrize("amount", [1, 1250.25, "1250.25", " 1250.25 ", "1e3", 1e12])
def test_valid_buy_amount(amount):
    parsed = decision(buy_notional_usd=amount)
    assert parsed.buy_notional_usd == float(amount)
    rendered = render_pm_decision(parsed)
    assert f"**Recommended Buy Amount USD**: {float(amount)}" in rendered
    assert parsed.executive_summary in rendered
    assert parsed.investment_thesis in rendered
    assert "**Rating**: Buy" in rendered


@pytest.mark.parametrize("amount", [
    True, False, 0, -1, float("nan"), float("inf"), -float("inf"),
    "NaN", "Infinity", "0", "-10", "1e999", "$1,250", "1250 USD",
    "10%", "around 1250", "1_250", "1,250", "None", "", [], {},
])
def test_invalid_buy_amount_is_rejected(amount):
    with pytest.raises(ValidationError):
        decision(buy_notional_usd=amount)


def test_optional_size_defaults_to_none():
    assert decision().buy_notional_usd is None
    assert decision(buy_notional_usd=None).buy_notional_usd is None
    assert "Recommended Buy Amount USD" not in render_pm_decision(decision())


def state():
    return {
        "company_of_interest": "AAPL", "instrument_context": "Instrument AAPL",
        "portfolio_context": "Available cash: USD 5000",
        "investment_plan": "Research", "trader_investment_plan": "Trader",
        "buy_notional_usd": 9999, "portfolio_decision_structured": True,
        "risk_debate_state": {
            "history": "Debate", "aggressive_history": "", "conservative_history": "",
            "neutral_history": "", "current_aggressive_response": "",
            "current_conservative_response": "", "current_neutral_response": "", "count": 1,
        },
    }


class Model:
    def __init__(self, result=None, *, unsupported=False, invalid=False):
        self.result = result
        self.unsupported = unsupported
        self.invalid = invalid
        self.prompts = []

    def with_structured_output(self, schema):
        assert schema is PortfolioDecision
        if self.unsupported:
            raise NotImplementedError
        return SimpleNamespace(invoke=self.typed_invoke)

    def typed_invoke(self, prompt):
        self.prompts.append(prompt)
        if self.invalid:
            return decision(buy_notional_usd="$1250")
        return self.result

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content="**Rating**: Buy\nBuy $1250 (25% of cash).")


@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
def test_typed_output_exposes_size_only_for_buy(rating):
    parsed = decision(rating=rating, buy_notional_usd=1250)
    model = Model(parsed)
    result = create_portfolio_manager(model)(state())
    assert result["portfolio_decision_structured"] is True
    assert result["buy_notional_usd"] == (1250 if rating == "Buy" else None)
    assert result["final_rating"] == rating
    assert result["final_trade_decision"] == render_pm_decision(parsed)
    assert ("Recommended Buy Amount USD" in result["final_trade_decision"]) == (rating == "Buy")
    assert "buy_notional_usd" in model.prompts[0]
    assert "executive_summary" in model.prompts[0]
    assert "Do not use\nmargin" in model.prompts[0]


def test_typed_buy_without_amount_clears_stale_amount():
    result = create_portfolio_manager(Model(decision()))(state())
    assert result["portfolio_decision_structured"] is True
    assert result["buy_notional_usd"] is None


@pytest.mark.parametrize("model", [
    Model(unsupported=True), Model(invalid=True), Model(None),
    Model({"rating": "Buy", "buy_notional_usd": 1250}),
    Model(SimpleNamespace(content="Buy 1250 USD")),
])
def test_text_fallback_never_sizes_and_clears_stale_flags(model):
    result = create_portfolio_manager(model)(state())
    assert result["portfolio_decision_structured"] is False
    assert result["buy_notional_usd"] is None
    assert result["final_rating"] == "Buy"
    assert result["final_trade_decision"] == "**Rating**: Buy\nBuy $1250 (25% of cash)."


def test_agent_state_has_sizing_fields():
    assert "buy_notional_usd" in AgentState.__annotations__
    assert "portfolio_decision_structured" in AgentState.__annotations__
