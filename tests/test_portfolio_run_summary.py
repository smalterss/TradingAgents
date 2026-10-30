"""Completion summaries preserve the manager's input and unabridged output."""

from types import SimpleNamespace

import pytest

from tradingagents.agents.context import get_portfolio_context_from_state
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.portfolio import PortfolioContext
from tradingagents.reporting import manager_summary, write_report_tree

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("context", [None, "  EXACT PORTFOLIO BLOCK\nCash: USD 123\n"])
def test_node_returns_exact_prompt_context_and_original_decision(structured, context):
    decision = PortfolioDecision(
        rating="Underweight", executive_summary="Reduce gradually.",
        investment_thesis="Evidence favors caution; opponents proposed Buy.",
    )
    original = "**Rating**: Underweight\n\nReduce gradually.\n\nFull original thesis."
    prompts = []

    class LLM:
        def with_structured_output(self, schema):
            assert schema is PortfolioDecision
            if not structured:
                raise NotImplementedError
            return self

        def invoke(self, prompt):
            prompts.append(prompt)
            return decision if structured else SimpleNamespace(content=original)

    state = {
        "company_of_interest": "AAPL", "instrument_context": "Instrument AAPL",
        "investment_plan": "Research", "trader_investment_plan": "Trader",
        "risk_debate_state": {
            "history": "Debate", "aggressive_history": "", "conservative_history": "",
            "neutral_history": "", "current_aggressive_response": "",
            "current_conservative_response": "", "current_neutral_response": "", "count": 1,
        },
    }
    if context is not None:
        state["portfolio_context"] = context
    expected = get_portfolio_context_from_state(state)
    result = create_portfolio_manager(LLM())(state)
    assert len(prompts) == 1
    assert f"\n{expected}\n" in prompts[0]
    assert result["portfolio_context"] == expected
    assert result["final_trade_decision"] == (render_pm_decision(decision) if structured else original)
    assert manager_summary(result) == {
        "portfolio": expected, "recommendation": result["final_trade_decision"],
        "rating": "Underweight",
    }


@pytest.mark.parametrize("context", [None, "", "  "])
def test_missing_context_is_unavailable_not_flat(context):
    state = {} if context is None else {"portfolio_context": context}
    summary = manager_summary(state)
    assert summary["portfolio"] == get_portfolio_context_from_state({})
    assert "not provided" in summary["portfolio"]
    assert "No current position" not in summary["portfolio"]
    assert summary["recommendation"] == ""
    assert summary["rating"] == "REVIEW"


def test_explicit_flat_book_and_canonical_rating_are_preserved():
    flat = PortfolioContext(cash=1000, positions=[]).render("AAPL")
    original = "**Rating**: Buy\n\nOriginal narrative quotes a different call."
    summary = manager_summary({"portfolio_context": flat, "final_trade_decision": original,
                               "final_rating": "Overweight"})
    assert summary == {"portfolio": flat, "recommendation": original, "rating": "Overweight"}
    assert "No current position in AAPL" in summary["portfolio"]


@pytest.mark.parametrize("legacy", [False, True])
def test_saved_markdown_and_html_include_context_before_original_decision(tmp_path, legacy):
    original = "**Rating**: Sell\n\nOriginal executive summary.\n\nFull investment thesis."
    state = {"final_trade_decision": original}
    if not legacy:
        state["portfolio_context"] = "Portfolio context: Current position in AAPL: 12 units"
    expected = manager_summary(state)["portfolio"]
    out = write_report_tree(state, "AAPL", tmp_path)
    assert (tmp_path / "5_portfolio/context.md").read_text(encoding="utf-8") == expected
    assert (tmp_path / "5_portfolio/decision.md").read_text(encoding="utf-8") == original
    markdown = out.read_text(encoding="utf-8")
    assert "## V. Portfolio Manager Decision" in markdown
    assert "### Portfolio Manager\n" + original in markdown
    assert markdown.index(expected) < markdown.index(original)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert page.index(expected) < page.index("Original executive summary.")
    assert "Full investment thesis." in page


def test_reusing_destination_cleans_context_and_decision_but_preserves_notes(tmp_path):
    write_report_tree({"portfolio_context": "Old context", "final_trade_decision": "Rating: Hold"},
                      "AAPL", tmp_path)
    notes = tmp_path / "5_portfolio/notes.md"
    notes.write_text("User notes", encoding="utf-8")
    out = write_report_tree({"portfolio_context": "New context without decision"},
                            "AAPL", tmp_path, html=False)
    assert not (tmp_path / "5_portfolio/context.md").exists()
    assert not (tmp_path / "5_portfolio/decision.md").exists()
    assert not (tmp_path / "complete_report.html").exists()
    assert notes.read_text(encoding="utf-8") == "User notes"
    assert "Portfolio Manager Decision" not in out.read_text(encoding="utf-8")


def test_portfolio_and_recommendation_are_untrusted_html(tmp_path):
    attack = '<script>alert("portfolio")</script>'
    recommendation = '**Rating**: Sell\n\n<img src="https://evil.test/x" onerror="alert(1)">'
    state = {"portfolio_context": attack, "final_trade_decision": recommendation}
    write_report_tree(state, "AAPL", tmp_path)
    page = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert "<script>" not in page and "<img" not in page
    assert "&lt;script&gt;" in page and "&lt;img" in page
    assert (tmp_path / "5_portfolio/context.md").read_text(encoding="utf-8") == attack
    assert (tmp_path / "5_portfolio/decision.md").read_text(encoding="utf-8") == recommendation
