---
id: tradingagents-package
type: module-design
status: active
title: Research package and shared application contracts
parent: tradingagents-architecture
---

## Responsibility

Expose the research framework and shared application contracts independently of terminal presentation. Package-level helpers own configuration defaults, caller portfolio context, independent decision-grid evaluation, and report serialization; these do not warrant separate directory-shaped modules.

## Internal dependency edges

`tradingagents-graph` composes `tradingagents-agents`, `tradingagents-dataflows`, `tradingagents-llm`, and `tradingagents-memory`. Agents reach market evidence through dataflows. Memory uses dataflows for outcome prices and agent rating vocabulary for decision tags; its reflector consumes an injected model rather than creating providers. Model adapters do not orchestrate agent roles. `tradingagents-web` uses the graph lifecycle, model metadata and credential-name mapping, symbol helpers, and shared reports without importing terminal presentation; its server and worker boundary is owned by that spec.

Backtesting invokes the graph and reads its isolated memory log. Reporting consumes final state and shared rating vocabulary, not live providers. Portfolio validation uses data-layer symbol normalization. Child modules may use these shared helpers; they must not depend on CLI presentation.

## Portfolio input

A portfolio is validated, broker-neutral context: finite numeric holdings and cash, signed quantities, and a currency label. Missing context, an explicit flat book, and an existing position are distinct. Aliases match the analyzed instrument without rewriting the caller's holding spellings. A fingerprint distinguishes changed books for recovery.

User-confirmed limit: the framework does not reconcile balances, translate currencies, or update holdings after a decision. A portfolio is not an executable order or account ledger.

## Evaluation

`run_backtest` analyzes independent ticker/date cells through the ordinary graph. Each sweep has its own results and memory log, leaving live memory untouched. Fresh sweeps claim unique IDs; supplying an existing ID resumes by skipping recorded cells. A supplied portfolio is the same standing book for every cell, never a carried-forward position.

Failures are collected per cell and settlement failures are surfaced separately. Summaries group settled alpha by rating; Hold claims no direction, review-required decisions are unscored, and pending decisions are not counted as resolved. Stored alpha has 0.1 percentage-point precision. User-confirmed: one model sample per cell and unarchived text feeds make the results indicative, not repeatable. Outcome-price semantics belong to `tradingagents-memory`.

## Reports and configuration

API and CLI use one report-tree writer. It writes populated sections and a consolidated Markdown report, optionally HTML, with analysis date and producing settings. Reusing a destination removes only obsolete generated files, preserving unrelated user files. HTML treats model text as untrusted: raw HTML and images are disabled, metadata escaped, and a content security policy blocks scripts and fetching.

Environment overrides are centrally mapped and invalid typed values fail explicitly. Import loads dotenv files without replacing already-set environment values and builds defaults at import time; callers can rebuild defaults to observe later changes.

## Boundary

These helpers do not execute orders or imply a filled position. Execution intent is recorded in `tradingagents-goals`, not invented inside the evaluator or report writer.
