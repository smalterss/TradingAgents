---
id: tradingagents-web
type: submodule-design
status: draft
title: Local browser research dashboard
parent: tradingagents-package
depends-on: [tradingagents-graph, tradingagents-llm, tradingagents-dataflows, tradingagents-agents]
---

## Responsibility

Expose the existing research engine as a single-user local browser workspace. Own validated run selection, real progress/report presentation, one stoppable worker, current-run reconnection and completed-report downloads. The dark dashboard separates setup, evidence stages, final rating and a keyboard-accessible report reader. It is a research workspace with explicitly opted-in, policy-limited Alpaca paper automation, not a live-trading or general order-entry terminal.

## Delivery and trust boundary

`tradingagents-web` and `python -m tradingagents.web` launch only on IPv4 loopback with optional web dependencies. Bundled HTML/CSS/JavaScript avoids a separate Node build and keeps ordinary CLI/API installation independent of the web server. Host validation rejects DNS-rebinding names; mutations require an exact matching Origin plus a per-server CSRF token. No CORS or public-listening option is provided. These safeguards do not isolate a hostile process already running as the local user.

Credentials and endpoints stay server-side in existing environment/dotenv settings. Metadata exposes provider/model suggestions, credential availability and required variable names, never secrets, sign-in identities, filesystem paths or endpoint values. ChatGPT uses an existing CLI sign-in; AWS credential-chain validity is deferred to the provider rather than rejected based only on environment presence. Switching model tiers preserves an endpoint only for the same previously effective provider, avoiding credential-bearing endpoint leakage to another provider.

## Current-run contract

Run input permits a safe normalized ticker, canonical non-future date, nonempty supported analyst selection, provider/model choices, language and bounded integer debate depths. Model suggestions are not a closed allowlist. Known crypto symbols select the existing crypto asset mode, including checkpoint identity. All other advanced vendor, endpoint and storage settings remain configuration-owned.

A server-owned lock serializes admission, event collection, stop and current report lookup. One spawn worker runs at a time; a completion event cannot admit another run until that process has exited. The current state survives browser reload while the server lives, not server restart. Starting a new run replaces the current view; generated reports remain in unique server-owned directories, without a history-browsing API.

The worker resolves automatic portfolio context under `tradingagents-package` before creating the graph, then uses the same snapshot for state and checkpoint lifecycle. Alpaca failures cross the process boundary only as a controlled reason code; the browser renders an actionable fixed summary. There is no browser credential entry or portfolio editor.

The worker uses the graph's streaming and shared recovery/recording/export lifecycle. Only allowlisted report text and public progress cross the process boundary. Stages derive from observed report outputs rather than invented completion percentages. Browser polling preserves a selected report tab and discards responses from before a run mutation so an old idle/running snapshot cannot undo start/stop feedback.

## Stop, failure and completion

The parent continuously consumes queue events, including after process exit; joining a producer before consuming a full pipe can deadlock or discard its completion event. Stop first collects available events, then terminates/joins the process and releases it. A forcibly killed queue producer can leave a partial frame, so the parent never reads that queue again after termination. Already-received reports remain visibly partial; remote requests already accepted may still incur charges. Server lifespan cleanup stops an active worker.

Opted-in workers call the dedicated paper executor only after successful research recording and an initial export; policy, journal identity and safety gates are owned by `tradingagents-package`. Execution failure or skip does not erase the research result. A second export retains the actual execution outcome; if that export fails, the dashboard still shows the outcome and a controlled export warning. No post-restart retrospective execution is attempted. Public configuration exposes only the execution-enabled boolean; the header, setup notice and run overview explicitly distinguish paper automation from research-only mode. Completed views show a safely rendered paper outcome separately from the rating, clear it on new/non-completed views, and warn that submission is not a fill. Stopping a run may leave an already-submitted paper order at Alpaca.

Completed, stopped and failed states are distinct. Only successful completion displays a final rating and permits the current Markdown/HTML downloads; those files come from the shared report writer. A missing/ambiguous rating remains review-required under `tradingagents-agents`. Forced stop cannot guarantee an in-flight atomic persistence operation did not complete, and is not a transactional rollback of memory or checkpoint files.

Successful completion also publishes the shared manager summary owned by `tradingagents-package`. Only allowlisted portfolio/recommendation strings are safely rendered by the server. Two responsive panels display the actual portfolio input and original recommendation beside the final rating, survive reload while the server lives, and are cleared/hidden on new, running, stopped or failed runs. Missing recorded summary data is labeled unavailable, not reconstructed from current broker balances.

Model text is rendered as Markdown with raw HTML, links, images and autolinks disabled; table markup is generated by the renderer. Static CSP blocks remote resources, framing and inline scripts; downloads retain the shared report's safe rendering. Browser error text and memory notes are controlled summaries rather than raw provider exception messages, which may contain secrets. Worker logs record exception type only, trading detailed diagnostics for credential protection.

## Verification and exclusions

Deterministic tests cover admission, invalid settings, missing credentials, endpoint inheritance, host/origin/token enforcement, safe rendering, downloads, graph lifecycle, large-queue completion and real process termination. Browser tests intercept all requests and exercise the actual assets without provider calls; a separate loopback smoke exercise verifies browser-to-server wiring. Playwright is an optional test tool, not a runtime dependency. Windows tests narrowly allow Python's internal socketpair connection for asyncio while retaining the external-network prohibition.

No arbitrary real or paper smoke order or paid-model run is authorized for verification. Portfolio editing, backtest/history screens, browser credential entry, live trading, general order entry, shared hosting and guaranteed recall of remote requests are outside this dashboard's scope. User-authorized paper execution applies only to future eligible dashboard runs; verification uses mocked order calls.
