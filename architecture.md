---
id: tradingagents-architecture
type: architecture-design
status: active
title: TradingAgents system architecture
parent: tradingagents-goals
---

## System shape

Python 3.11+ hosts a LangGraph workflow, LangChain model adapters, vendor-backed evidence retrieval, and local persistence. The terminal application, Python API and optional local browser dashboard expose the same research pipeline. This graph describes the implementation inspected during import; inferred intent remains unconfirmed until review.

`tradingagents-package` owns application-level evaluation, portfolio input, and report contracts. Its child specs define the evidence, model, agent, memory, and orchestration boundaries. `tradingagents-cli` is a separate presentation and configuration adapter, not a second research engine. `tradingagents-web` is the package's loopback-only browser adapter, served by optional FastAPI/Uvicorn dependencies with bundled assets rather than a separate JavaScript build. It owns process-isolated browser jobs, not a new investment engine.

## Cross-cutting contracts

- The graph is the composition root for model clients, agent nodes, data configuration, memory settlement, and checkpoint lifecycle. Role prompts do not own orchestration or account execution.
- Evidence time is bounded at both model-facing tools and vendor data paths; a model cannot enlarge its run's knowledge window by supplying another ticker or future date. Detailed availability semantics belong to `tradingagents-dataflows`.
- SDK-specific model behavior stays in adapters; agent roles consume supplied model interfaces. Configuration can select a different provider for each reasoning tier without leaking the main provider's endpoint to another tier.
- Vendor-library access belongs in dataflows. The current AST layering gate enforces this for `yfinance` only, not all network calls or SDKs.
- A missing or unreadable decision is not silently a neutral investment call. The canonical output contract belongs to `tradingagents-agents`.
- External data/model failures remain distinguishable from market evidence; successful research output does not imply an executed trade. The opted-in dashboard worker may call the dedicated Alpaca paper-execution service after research and an initial report export succeed; graph/agent/report code does not submit orders. Broker outcomes and research outcomes remain separate.

## Verification boundary

`pyproject.toml` defines pytest's default non-integration suite and Ruff rules. Tests isolate settings/storage and prohibit network access outside integration tests. CI runs Python 3.11–3.14, an additional non-UTC job, a clean-install import smoke check, and repository linting. These are existing gates, not evidence that this documentation import has run them.

## Document provenance

README and CHANGELOG supplied context; neither was adopted as a spec node. No existing standalone design or agent-instruction documents were found to adopt. Product execution intent is reconciled in `tradingagents-goals` without changing runtime behavior or the README.
