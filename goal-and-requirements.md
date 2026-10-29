---
id: tradingagents-goals
type: goal-and-requirements
status: active
title: TradingAgents purpose and scope
---

## Goal

TradingAgents is a Python multi-agent financial research framework. Specialized analysts, opposing researchers, a trader, and risk managers turn market evidence into an explained investment decision. It is research software, not financial, investment, or trading advice.

Audience inference — unconfirmed: researchers and developers studying LLM-assisted investment analysis, through either a Python API or terminal application.

## Current capabilities

- Analyze an instrument on a specified non-future date using selected technical, fundamentals, news, and sentiment analysts, followed by research and risk debates.
- Produce narrative reports and a canonical investment rating, with explicit review-required output when no reliable rating can be read. Completed-run summaries pair the portfolio information supplied to the Portfolio Manager with its original recommendation.
- Support multiple hosted or local model providers, separately configurable reasoning tiers, and configurable evidence vendors.
- Incorporate caller-supplied holdings or read-only Alpaca paper-account context, persist decisions and outcome lessons, and optionally recover interrupted analyses.
- Evaluate independent ticker/date decisions against realized benchmark-relative returns; export shared Markdown and optional self-contained HTML reports.
- Run a single analysis from a local browser dashboard with environment-based credentials, visible agent progress, stoppable local work, and a readable/downloadable report.
- When explicitly enabled, automatically submit validated current-day dashboard Buy/Sell decisions to an Alpaca paper account and show the actual submission outcome separately from research.

## Intended scope and implementation gap

User-confirmed: automatic Alpaca paper execution is authorized for future dashboard runs under the `tradingagents-package` safeguards. The Portfolio Manager chooses a Buy dollar amount without a fixed per-stock cap, constrained by fresh account cash; Sell closes available long holdings. Only Buy/Sell execute, and only eligible US stocks/ETFs during the current regular session. CLI/Python research and backtests do not execute. Live trading, shorts and margin are not implemented or authorized. Alpaca remains the authority for account state and fills; there is no local simulated exchange or cash ledger.

The existing backtest remains a decision-quality evaluator, not a portfolio simulator; execution intent does not override that boundary (see `tradingagents-package`).

## Recognized limits

User-confirmed: historical feeds have coverage gaps; model sampling and unarchived feeds make evaluation indicative rather than repeatable; completed memory cells are identified by ticker/date; supplied portfolios are context only. Their concrete contracts live in `tradingagents-dataflows`, `tradingagents-memory`, and `tradingagents-package`.

The framework makes no guarantee of profitable decisions or reproducible published returns.
