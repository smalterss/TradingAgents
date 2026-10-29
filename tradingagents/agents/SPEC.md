---
id: tradingagents-agents
type: submodule-design
status: active
title: Evidence-based agent decisions
parent: tradingagents-package
depends-on: [tradingagents-dataflows]
---

## Responsibility

Define specialist role prompts, state and structured decision schemas, instrument context, the model-facing evidence tools, and canonical decision vocabulary. Analyst roles gather evidence; downstream roles weigh the supplied reports rather than independently searching for facts.

## Decision contract

Research and portfolio managers use Buy, Overweight, Hold, Underweight, or Sell. The trader proposes Buy, Hold, or Sell; its transaction direction is not a replacement for the final investment rating. Prose remains the artifact read by users and downstream roles. Structured manager/trader schemas render back to that narrative form; unsupported binding or failed structured invocation falls back to ordinary text generation.

An absent or ambiguous final rating yields `REVIEW`, not Hold. `REVIEW` is non-tradeable and callers must guard it before converting to the rating enum. Deterministic parsing favors the decision's own explicit rating over quoted opposing calls; mere rating words in prose are not a decision.

## Evidence and context

Model-facing tools hide run ticker/date fields from model schemas and obtain them from injected state. Date arguments cannot extend beyond the run cutoff. Exact price/indicator claims are grounded in retrieved evidence; downstream structured agents are instructed to use provided evidence and not call external search tools. Prompt instructions are not a guarantee of model factuality.

Holdings context reaches trader, risk roles and portfolio manager rather than the research team's directional debate. The configured output language also applies to researcher and risk-debater responses stored in debate history; machine-readable rating labels and values remain English. This implemented behavior, covered by `tests/test_i18n_coverage.py`, differs from the default-config comment claiming internal debate stays English. Optional Jev screening filters off-company social posts and supplies stance counts; without configured credentials posts pass through unscreened.

## Boundary

Roles consume injected model interfaces and routed evidence. They do not instantiate provider SDK clients, import vendor libraries directly, control checkpoint persistence, mutate holdings, or submit orders. Knowledge-time and unavailable-data semantics are owned by `tradingagents-dataflows`; the graph controls role sequencing and budgets.
