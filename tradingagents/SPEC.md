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

The package can read Alpaca paper-account cash, currency and open positions into this same broker-neutral context. Environment credential presence enables automatic snapshots by default; the typed `alpaca_portfolio_enabled` configuration / `TRADINGAGENTS_ALPACA_PORTFOLIO_ENABLED` override disables them. Explicit caller portfolios take precedence. Each CLI, browser or Python analysis resolves one snapshot before state creation and checkpoint identity. Fetch or validation failure stops the analysis rather than inventing a flat book. Cash means account cash, not margin buying power; short quantities are signed negative.

The portfolio reader permits only fixed paper-API GET requests, with bounded timeouts, redirects rejected and sanitized errors. Credentials stay in environment/request headers, never configuration, agent state, prompts or reports. Credential names are `ALPACA_API_KEY` / `ALPACA_API_SECRET`, with `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` aliases. Automatic snapshots require today's New York date: other dates require explicit context or disabling the integration, avoiding current holdings masquerading as historical data. Backtest grids never auto-fetch broker holdings.

User-confirmed limit: the framework does not reconcile balances, translate currencies, or update holdings after a decision. A portfolio is not an executable order or account ledger.

## Paper execution

A dedicated execution service is separate from portfolio validation, graph research and report serialization. Only the dashboard worker invokes it, explicitly opted in through typed `alpaca_paper_execution_enabled` / `TRADINGAGENTS_ALPACA_PAPER_EXECUTION_ENABLED` (default false). Credentials alone never authorize orders. CLI/Python analyses and backtest grids remain non-executing even if this setting is present.

User-confirmed policy: exact structured Buy/Sell decisions on today's New York date may trade eligible active US stocks/ETFs. Buy uses the manager's positive finite USD notional, with exact cent precision and no fixed per-stock cap, bounded by fresh cash rather than margin buying power; fractional eligibility is required. Sell uses the available positive long quantity with explicit sell-to-close intent, never a short-opening instruction. Other ratings, text-only decisions, missing sizing, blocked/non-USD accounts, unsupported instruments and closed markets skip. Broker clock is checked again before submission, with a 60-second-to-close safety margin. Conflicting target orders block execution; any pending Buy conservatively blocks new buys rather than estimating reserved cash.

The service uses fixed paper HTTPS endpoints only, bounded non-redirecting GET/POST calls and no automatic HTTP retries. A persistent SQLite intent journal under the application home and a separate SQLite mutex serialize local preflight/submission across processes. Per-account/run identity produces a deterministic client order ID. Intent is committed before POST; a timeout, ambiguous response or crash cannot authorize reposting. Unresolved intents are reconciled by client ID and block new account submissions while unresolved. Local processes coordinate; multiple hosts and simultaneous external/manual account activity are not isolated by this mutex.

Market/day orders are requested without extended-hours eligibility; the broker remains authoritative for acceptance, rejection, fills and account state. The application does not mutate holdings, simulate a cash ledger or continuously poll fills. It reports the last confirmed broker response, distinguishing submitted from filled. Stopping a worker cannot recall an order already sent. Research exports precede order submission; execution results are exported afterward and retained in the journal if a later export fails. Unknown results require inspection rather than blind retry. No live trading, shorts, leverage, historical execution, arbitrary smoke trades or retrospective orders are authorized.

## Evaluation

`run_backtest` analyzes independent ticker/date cells through the ordinary graph. Each sweep has its own results and memory log, leaving live memory untouched. Fresh sweeps claim unique IDs; supplying an existing ID resumes by skipping recorded cells. A supplied portfolio is the same standing book for every cell, never a carried-forward position.

Failures are collected per cell and settlement failures are surfaced separately. Summaries group settled alpha by rating; Hold claims no direction, review-required decisions are unscored, and pending decisions are not counted as resolved. Stored alpha has 0.1 percentage-point precision. User-confirmed: one model sample per cell and unarchived text feeds make the results indicative, not repeatable. Outcome-price semantics belong to `tradingagents-memory`.

## Reports and configuration

API and CLI use one report-tree writer. It writes populated sections and a consolidated Markdown report, optionally HTML, with analysis date and producing settings. Reusing a destination removes only obsolete generated files, preserving unrelated user files. HTML treats model text as untrusted: raw HTML and images are disabled, metadata escaped, and a content security policy blocks scripts and fetching.

Completed-run summaries pair the exact portfolio prompt block returned by the Portfolio Manager with its unaltered decision and canonical rating, without additional broker reads or model calls. Missing context stays explicitly unavailable rather than becoming a flat book. Shared Markdown/HTML reports retain `5_portfolio/context.md` alongside `decision.md`; both generated files participate in cleanup. Summaries do not infer executable quantities or claim an order occurred. A separately supplied `paper_execution_report` is written under `6_paper_execution/execution.md` and included in consolidated exports; it reports the actual broker outcome, not an inferred fill.

Environment overrides are centrally mapped and invalid typed values fail explicitly. Import loads dotenv files without replacing already-set environment values and builds defaults at import time; callers can rebuild defaults to observe later changes.

## Boundary

Portfolio models, evaluation, research orchestration and report writers do not execute orders or imply fills. Only the explicitly authorized paper-execution service submits dashboard orders under the policy above; live execution is excluded.
