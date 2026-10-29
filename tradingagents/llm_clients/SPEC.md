---
id: tradingagents-llm
type: submodule-design
status: draft
title: Provider adaptation and authentication
parent: tradingagents-package
---

## Responsibility

Translate provider-neutral model configuration into LangChain-compatible clients, including model metadata, credential discovery, provider-specific capabilities, endpoints, reasoning controls and optional subscription authentication. Client factories lazily load adapters so merely importing the factory does not require every SDK or credential.

## Provider contract

Each quick/deep tier inherits the main provider unless explicitly overridden. A tier using another provider uses that provider's credentials and default endpoint, unless its own endpoint is set; the main endpoint must not leak across providers. Optional Bedrock support uses its extra and AWS credential mechanisms.

Capability metadata controls supported request fields and reasoning behavior; arbitrary served model IDs remain usable rather than being restricted to a curated picker. Unknown models use optimistic capability defaults, not proven compatibility. Retry budgets, output-token limits and thinking/sampling controls are adapted where supported; a setting does not guarantee deterministic output.

## Subscription authentication

ChatGPT subscription access is distinct from OpenAI API-key access. It uses PKCE browser login with loopback or pasted redirect, verified identity tokens, a pinned Responses endpoint, local token storage and a cross-process refresh lock. Rotated refresh credentials must not be replayed by concurrent clients. Transient refresh failures can reuse an unexpired token with a cooldown; expired/refused credentials require an actionable authentication error. Logout revokes/removes the saved sign-in.

Token files are written atomically and request restrictive POSIX permissions. Equivalent Windows ACL protection is unconfirmed; this import makes no cross-platform encryption-at-rest guarantee.

## Boundary

Adapters own protocol and provider-specific arguments, not analyst prompts, data vendors, research sequencing, or terminal UI. Agents receive client interfaces rather than selecting SDK implementations themselves. Subscription plan limits and unsupported options remain provider constraints, not promises that ordinary API settings always apply.
