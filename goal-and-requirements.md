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
- Produce narrative reports and a canonical investment rating, with explicit review-required output when no reliable rating can be read.
- Support multiple hosted or local model providers, separately configurable reasoning tiers, and configurable evidence vendors.
- Incorporate caller-supplied holdings, persist decisions and outcome lessons, and optionally recover interrupted analyses.
- Evaluate independent ticker/date decisions against realized benchmark-relative returns; export shared Markdown and optional self-contained HTML reports.

## Intended scope and implementation gap

User-confirmed: order execution is intended product scope. No simulated exchange, filled-order lifecycle, or cash ledger is implemented. The README's execution claim describes intent, not a current capability. Execution venue, authorization, fill rules, and account-state contracts are not established by this import.

The existing backtest remains a decision-quality evaluator, not a portfolio simulator; execution intent does not override that boundary (see `tradingagents-package`).

## Recognized limits

User-confirmed: historical feeds have coverage gaps; model sampling and unarchived feeds make evaluation indicative rather than repeatable; completed memory cells are identified by ticker/date; supplied portfolios are context only. Their concrete contracts live in `tradingagents-dataflows`, `tradingagents-memory`, and `tradingagents-package`.

The framework makes no guarantee of profitable decisions or reproducible published returns.
