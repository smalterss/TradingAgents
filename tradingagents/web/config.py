"""Browser-safe configuration and validation (no provider construction)."""

import copy
import os
import re
from datetime import date

from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS


class MissingCredentials(ValueError):
    """An actionable error containing environment variable names only."""


ANALYSTS = ("market", "social", "news", "fundamentals")
PROVIDERS = tuple(dict.fromkeys((*MODEL_OPTIONS, *PROVIDER_API_KEY_ENV)))


def credential_status(provider):
    if provider == "chatgpt":
        from tradingagents.llm_clients.chatgpt_auth import signed_in_as

        return bool(signed_in_as()), "Sign in with tradingagents login chatgpt before running."
    if provider == "bedrock":
        return True, "Uses AWS_BEARER_TOKEN_BEDROCK or the AWS credential chain; verified when running."
    env = PROVIDER_API_KEY_ENV.get(provider)
    if provider in ("ollama", "openai_compatible"):
        return (
            True,
            "No API key required" if provider == "ollama" else "Optional OPENAI_COMPATIBLE_API_KEY",
        )
    return bool(env and os.getenv(env)), env or "Provider credentials required"


def public_config(base, token):
    providers = []
    for provider in PROVIDERS:
        configured, hint = credential_status(provider)
        models = {}
        for options in MODEL_OPTIONS.get(provider, {}).values():
            for label, model in options:
                if model != "custom":
                    models[model] = {"id": model, "label": label}
        providers.append(
            {
                "id": provider,
                "label": provider.replace("_", " ").title(),
                "configured": configured,
                "credential_hint": hint,
                "models": list(models.values()),
            }
        )
    return {
        "csrf_token": token,
        "providers": providers,
        "defaults": {
            "ticker": "",
            "trade_date": date.today().isoformat(),
            "analysts": list(ANALYSTS),
            "quick_provider": base.get("quick_think_provider") or base["llm_provider"],
            "deep_provider": base.get("deep_think_provider") or base["llm_provider"],
            "quick_model": base["quick_think_llm"],
            "deep_model": base["deep_think_llm"],
            "output_language": base["output_language"],
            "max_debate_rounds": base["max_debate_rounds"],
            "max_risk_discuss_rounds": base["max_risk_discuss_rounds"],
        },
    }


def validate_run(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    required = {
        "ticker",
        "trade_date",
        "analysts",
        "quick_provider",
        "deep_provider",
        "quick_model",
        "deep_model",
        "output_language",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
    }
    if set(data) != required:
        raise ValueError("Supply exactly the supported run settings.")
    result = dict(data)
    for key, limit in [
        ("ticker", 32),
        ("trade_date", 10),
        ("quick_provider", 40),
        ("deep_provider", 40),
        ("quick_model", 200),
        ("deep_model", 200),
        ("output_language", 80),
    ]:
        value = data[key]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError(f"Invalid {key}.")
        result[key] = value.strip()
    result["ticker"] = safe_ticker_component(normalize_symbol(result["ticker"]))
    try:
        day = date.fromisoformat(data["trade_date"])
        if day.isoformat() != data["trade_date"] or day > date.today():
            raise ValueError
    except ValueError:
        raise ValueError("trade_date must be YYYY-MM-DD and not in the future.") from None
    analysts = data["analysts"]
    if (
        not isinstance(analysts, list)
        or not analysts
        or any(not isinstance(a, str) or a not in ANALYSTS for a in analysts)
    ):
        raise ValueError("Select at least one supported analyst.")
    result["analysts"] = [a for a in ANALYSTS if a in analysts]
    for key in ("max_debate_rounds", "max_risk_discuss_rounds"):
        if type(data[key]) is not int or not 1 <= data[key] <= 10:
            raise ValueError(f"{key} must be an integer from 1 to 10.")
    for tier in ("quick", "deep"):
        provider = result[f"{tier}_provider"]
        if provider not in PROVIDERS:
            raise ValueError("Unsupported provider.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}", result[f"{tier}_model"]):
            raise ValueError("Invalid model ID.")
        available, hint = credential_status(provider)
        if not available:
            raise MissingCredentials(f"Missing credentials for {provider}: {hint}")
    return result


def run_config(base, selection):
    config = copy.deepcopy(base)
    old_primary = base["llm_provider"]
    primary = selection["quick_provider"]
    config["llm_provider"] = primary
    config["backend_url"] = base.get("backend_url") if primary == old_primary else None
    for tier in ("quick", "deep"):
        previous = base.get(f"{tier}_think_provider") or old_primary
        provider = selection[f"{tier}_provider"]
        # Provider/endpoint inheritance: see tradingagents-web SPEC.
        endpoint = base.get(f"{tier}_think_backend_url")
        if endpoint is None and previous == old_primary:
            endpoint = base.get("backend_url")
        config[f"{tier}_think_provider"] = provider
        config[f"{tier}_think_backend_url"] = endpoint if provider == previous else None
        config[f"{tier}_think_llm"] = selection[f"{tier}_model"]
    for key in ("output_language", "max_debate_rounds", "max_risk_discuss_rounds"):
        config[key] = selection[key]
    return config
