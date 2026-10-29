---
id: tradingagents-graph
type: submodule-design
status: active
title: Run orchestration and recovery
parent: tradingagents-package
depends-on: [tradingagents-agents, tradingagents-dataflows, tradingagents-llm, tradingagents-memory]
---

## Responsibility

Own research-run lifecycle: initialize supplied model tiers and role factories, resolve instrument context, build run state, execute LangGraph, record the result, and manage recovery. `TradingAgentsGraph.propagate` returns `(final_state, signal)`; it does not place an order.

## Workflow contract

Selected analysts run concurrently in subgraphs with private message histories and return only their distinct report fields. Memory settlement runs alongside them. A join waits for all first steps before bull/bear research, research-manager judgment, trader proposal, risk debate, and portfolio-manager judgment. Only the portfolio manager consumes remembered lessons.

Analyst tool rounds are bounded and end in a report-requesting wrap-up turn even if the model keeps asking for tools. Debate and risk depth are configured; shared conditional routers have complete destination maps. Quick models serve analysts, researchers, trader and risk debaters; deep models serve the two managers.

## Run integrity and recovery

Run dates must be canonical `YYYY-MM-DD` and no later than today. Instrument identity is resolved once and injected into agent context; historical identity context does not pass current sector/industry facts as historical evidence. Run-scoped vendor configuration is installed for execution.

Opt-in SQLite checkpoints are per ticker. Thread identity includes date, graph layout, analyst selection, asset mode, portfolio fingerprint and output-affecting settings. Storage locations, checkpoint enablement and retry budget do not alter that signature. Changed effective inputs start fresh; a compatible interrupted thread resumes with `None` input rather than appending initial messages again.

Successful completion records the decision and clears its checkpoint; interruption preserves recoverable progress. Checkpointer resources are released and the plain graph restored. Both `propagate` and CLI streaming must share state creation, recovery, recording, and cleanup semantics.

## Boundary

Orchestration may compose its child services but does not embed vendor SDK access, provider-specific request syntax, or terminal prompts. Memory settlement failure becomes a visible run note rather than aborting otherwise usable research. Rating semantics belong to `tradingagents-agents`; persistent decision identity belongs to `tradingagents-memory`.
