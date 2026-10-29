---
id: tradingagents-cli
type: module-design
status: active
title: Interactive and unattended terminal application
parent: tradingagents-architecture
depends-on: [tradingagents-package, tradingagents-graph, tradingagents-llm]
---

## Responsibility

Adapt the framework to interactive and unattended terminal use through the installed `tradingagents` command and `python -m cli.main`. Own prompts, input selection, progress/stats display, saved preferences, report-opening choices, and analysis/backtest/login/logout commands.

## Input and execution contract

Flags and supported environment values answer their own questions. Saved preferences only prefill prompts; they do not suppress them, and ticker/date are not remembered. An unattended run missing required answers fails before model execution with an actionable flag or variable. Explicit checkpoint flags override configuration; omitting the flag preserves configured behavior. Explicit environment debate-depth settings survive interactive depth selection.

Validate portfolio input before execution and check credentials separately for effective model tiers. The CLI streams the graph directly, so it must use the shared state, recording and checkpoint lifecycle described by `tradingagents-graph`, not assume `propagate` has already run. Report generation uses the package writer rather than a CLI-specific serialization path.

## Startup notices

Interactive startup may fetch release/notices in the background at most daily, without run data. Non-terminal runs do not check; `TRADINGAGENTS_NO_UPDATE_CHECK=1` disables checking. Notice failure must not determine the investment decision.

## Boundary

Presentation imports public framework helpers and model metadata/authentication, not vendor SDKs. It must not implement investment reasoning, realized-return accounting, or order execution. A displayed decision is not a submitted trade. Credential storage and provider-specific login semantics belong to `tradingagents-llm`.
