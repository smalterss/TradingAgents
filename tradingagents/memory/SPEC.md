---
id: tradingagents-memory
type: submodule-design
status: active
title: Decision memory and realized outcomes
parent: tradingagents-package
depends-on: [tradingagents-dataflows, tradingagents-agents]
---

## Responsibility

Persist completed decisions in a readable Markdown log, settle mature decisions with realized raw and benchmark-relative returns, generate concise lessons with an injected quick model, and supply temporally eligible context to the portfolio manager. This is a decision/lesson store, not vector retrieval or an account ledger.

## Persistence and context

Writes are locked and decision insertion is idempotent by ticker/date. User-confirmed limit: changing models, settings, or holdings does not replace a recorded cell under that identity. Settlement rewrites pending entries atomically; the file is not strictly append-only. Optional rotation removes old resolved entries but never pending ones.

Context selects recent same-ticker decisions and recent cross-ticker lessons. For historical runs, lessons must have a stored resolution date no later than the run date; legacy undated resolutions are excluded. Current-date context retains the live behavior without that historical filter.

## Outcome semantics

Entry is the first final instrument close strictly after the decision date because the analysis may consume that date's after-close news. Exit follows the configured number of instrument trading sessions. Today's unfinished bar and nonpositive prices cannot score a decision; closures and insufficient data keep it pending rather than inventing a return.

An explicit benchmark overrides regional suffix mapping. Benchmark as-of closes span the same entry/exit interval across differing calendars and must have traded through the exit. Alpha subtracts benchmark percentage return, without currency conversion or an execution-cost model.

Settlement serializes passes and persists each reflected outcome immediately. Data or reflection failure leaves that decision pending and returns failure details; it does not erase completed outcomes or prevent research from continuing. The graph's parallel settlement path may defer to an already-running pass.

## Boundary

Memory reads price services through dataflows and invokes a supplied reflector; it does not instantiate model providers, alter holdings, simulate fills, or own graph recovery. Its realized-return labels measure a decision over a stated horizon, not account profit. Backtest isolation is owned by `tradingagents-package`.
