---
id: tradingagents-dataflows
type: submodule-design
status: draft
title: Market evidence and knowledge-time boundaries
parent: tradingagents-package
---

## Responsibility

Own vendor access, symbol normalization and safe filesystem components, evidence-date filtering, price caches, HTTP failure scrubbing, and configurable tool-to-vendor routing. Distinguish absent evidence from failed acquisition so an outage cannot become a bearish market fact.

## Routing and isolation

A tool override takes precedence over its category configuration. An explicit ordered vendor chain is exclusive; only `default` expands to registered alternatives. This prevents silently mixing evidence from sources the caller did not choose. Run configuration is isolated through a ContextVar and propagated into worker execution rather than relying only on process-global settings.

Typed failures distinguish no usable data, unavailable service/request, and missing configuration. The router falls through the configured chain on failures; returned text, including a withholding notice, is a completed response. Exhausted unavailable errors, or unexpected errors mixed with no-data, yield `DATA_UNAVAILABLE`; clean no-data yields `NO_DATA_AVAILABLE`. Remaining configuration/unexpected failures can raise for core tools, while optional macro/prediction paths may degrade. These are evidence-status outcomes, not investment ratings.

## Knowledge-time contract

Date windows are normalized and capped to the analysis date. Reversed windows fail; wholly future windows can move backward while retaining their span. Timestamp comparisons normalize to UTC and include the full final day. Historical windows exclude undated items and distinguish incomplete feed coverage from no matching events.

Historical statements require filing-time knowledge, not merely a fiscal-period end. SEC EDGAR uses filings known by the cutoff, preserving the then-known restatement vintage; unsupported filers fall through by typed failure. Yahoo/Alpha statements lacking disclosure timestamps are withheld historically, as are current profiles, transaction-dated insider trades, and live-only prediction odds. FRED pins observation and revision vintage.

Cached or downloaded OHLCV is filtered to the requested cutoff and checked for staleness; current unfinished bars are excluded from outcome scoring. Date-capped vendor outputs supplement the model-tool enforcement, not replace it. Direct tools called without run state retain their documented standalone behavior and do not automatically acquire a run cutoff.

## Recognized limits

User-confirmed: recent news/social feeds are not historical archives; old windows can be incomplete. Prices downloaded now are not an archive of historical data vintages. SEC coverage depends on supported filings/tags and does not derive an unsupported fourth quarter from an annual total. Current identity names may be explicitly labeled current rather than represented as historical facts.

## Boundary

Market-data SDK imports and cache writes stay here; callers use routed tools or explicit data services. HTTP errors must not leak API query secrets through exception text/chains. Safe ticker path components reject traversal. Data acquisition does not choose investment ratings, run debates, or render user reports.
