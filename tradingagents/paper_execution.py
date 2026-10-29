"""Opt-in paper execution, never called implicitly by research.

A separate SQLite mutex is held across journal commits and HTTP calls. This
serializes local processes while allowing the submission intent to be durable
BEFORE POST. It is not a multi-host lock. Enabled-run skips are durable too;
the disabled gate deliberately performs no IO. No broker errors are published.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PAPER_URL = "https://paper-api.alpaca.markets"
_SYMBOL = re.compile(r"[A-Z]{1,5}(?:[.-][A-Z]{1,2})?\Z")
_BROKER_STATUSES = frozenset({
    "new", "partially_filled", "filled", "done_for_day", "canceled", "expired",
    "replaced", "pending_cancel", "pending_replace", "accepted", "pending_new",
    "accepted_for_bidding", "stopped", "rejected", "suspended", "calculated",
})
_REASONS = {
    "disabled": "Paper execution is disabled.",
    "gate": "The decision is not eligible for paper execution.",
    "credentials": "Paper credentials are unavailable.",
    "account": "The paper account is not eligible for trading.",
    "closed": "The market is closed or the trading date changed.",
    "asset": "The asset is not eligible for this paper order.",
    "pending": "Pending orders prevent safe execution.",
    "cash": "Available cash is insufficient or uncertain.",
    "position": "No available positive long position can be closed.",
    "submitted": "The broker confirmed the paper order; submission is not a fill.",
    "filled": "The broker confirmed the paper order was filled.",
    "rejected": "The broker rejected the paper order.",
    "unknown": "The paper order outcome is unknown; it will not be resubmitted.",
    "error": "Paper execution could not safely complete.",
}


def _today():
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("number")
    result = Decimal(str(value))
    if not result.is_finite() or abs(result) > Decimal("1e18"):
        raise ValueError("number")
    return result


def _number(value):
    return format(_decimal(value), "f")


def _result(status, reason, symbol="", side="", client_order_id="", **fields):
    return dict(status=status, reason=_REASONS[reason], symbol=symbol, side=side,
                client_order_id=client_order_id, **fields)


def _get(session, path, **params):
    response = session.get(PAPER_URL + path, params=params or None,
                           timeout=15, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError("preflight")
    return response.json()


def _order_result(order, base):
    """Treat malformed/mismatched broker responses as ambiguous, not success."""
    unknown = dict(base, status="unknown", reason=_REASONS["unknown"])
    if not isinstance(order, dict) or any(order.get(k) != base[k] for k in
                                           ("symbol", "side", "client_order_id")):
        return unknown
    status = order.get("status")
    if not isinstance(status, str) or status not in _BROKER_STATUSES:
        return unknown
    fields = {}
    try:
        for key in ("filled_qty", "filled_avg_price"):
            if order.get(key) is not None:
                if _decimal(order[key]) < 0:
                    return unknown
                fields[key] = _number(order[key])
        if status == "filled":
            qty = _decimal(fields.get("filled_qty", "0"))
            price = _decimal(fields.get("filled_avg_price", "0"))
            if qty <= 0 or price <= 0:
                return unknown
            if "quantity" in base and qty != _decimal(base["quantity"]):
                return unknown
    except (ValueError, InvalidOperation):
        return unknown
    public_status = "filled" if status == "filled" else "rejected" if status == "rejected" else "submitted"
    return dict(base | fields, status=public_status, reason=_REASONS[public_status], broker_status=status)


def _lookup(session, base):
    response = session.get(PAPER_URL + "/v2/orders:by_client_order_id",
                           params={"client_order_id": base["client_order_id"]},
                           timeout=15, allow_redirects=False)
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ValueError("lookup")
    return _order_result(response.json(), base)


def execute_paper_decision(final_state: dict, ticker: str, trade_date: str,
                           run_key: str, config: dict) -> dict:
    """Execute one explicitly opted-in current structured decision, at most once.

    Callers must restrict invocation to new dashboard runs. Numeric manager
    sizing accepts numbers/Decimal, not numeric strings; broker decimals are
    strings. Buy amounts must be exact cents (no implicit rounding).
    """
    symbol = ticker if isinstance(ticker, str) and _SYMBOL.fullmatch(ticker) else ""
    rating = final_state.get("final_rating")
    side = {"Buy": "buy", "Sell": "sell"}.get(rating, "") if isinstance(rating, str) else ""
    base = _result("skipped", "gate", symbol, side)
    if config.get("alpaca_paper_execution_enabled") is not True:
        return dict(base, reason=_REASONS["disabled"])
    if not isinstance(run_key, str) or not run_key.strip():
        return dict(base, status="error", reason=_REASONS["error"])
    lock = db = None
    try:
        path = Path(config.get("paper_execution_journal_path") or
                    Path.home() / ".tradingagents" / "paper_execution.sqlite3").expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = sqlite3.connect(str(path) + ".lock", timeout=30)
        lock.execute("BEGIN IMMEDIATE")
        db = sqlite3.connect(str(path), timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS executions (account_id TEXT NOT NULL, run_key TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(account_id, run_key))")
        db.commit()

        def load(account):
            row = db.execute("SELECT result FROM executions WHERE account_id=? AND run_key=?",
                             (account, run_key)).fetchone()
            return json.loads(row[0]) if row else None

        def save(account, result):
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO executions VALUES (?, ?, ?)",
                       (account, run_key, json.dumps(result)))
            db.commit()
            return result

        prior = load("")
        if prior:
            return prior
        amount = None
        eligible = (symbol and side and final_state.get("portfolio_decision_structured") is True
                    and trade_date == _today())
        if eligible and side == "buy":
            raw = final_state.get("buy_notional_usd")
            try:
                if isinstance(raw, (str, bool)):
                    raise ValueError("sizing")
                amount = _decimal(raw)
                eligible = amount > 0 and amount == amount.quantize(Decimal("0.01"))
            except (ValueError, InvalidOperation):
                eligible = False
        if not eligible:
            recorded = db.execute(
                "SELECT 1 FROM executions WHERE run_key=? AND account_id != ''", (run_key,)
            ).fetchone()
            if not recorded:
                return save("", base)
        key = next((os.environ[n].strip() for n in ("ALPACA_API_KEY", "APCA_API_KEY_ID") if os.environ.get(n, "").strip()), "")
        secret = next((os.environ[n].strip() for n in ("ALPACA_API_SECRET", "APCA_API_SECRET_KEY") if os.environ.get(n, "").strip()), "")
        if not key or not secret:
            return save("", dict(base, reason=_REASONS["credentials"]))
        with requests.Session() as session:
            session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
            account = _get(session, "/v2/account")
            account_id = account.get("id")
            if not isinstance(account_id, str) or not account_id:
                raise ValueError("account")
            prior = load(account_id)
            if prior:
                if prior["status"] not in ("unknown", "submitting", "submitted"):
                    return prior
                base = dict(prior, status="unknown", reason=_REASONS["unknown"])
                found = _lookup(session, base)
                return save(account_id, found or base)
            if not eligible:
                return save("", base)
            client_id = "paper-" + hashlib.sha256((account_id + "\0" + run_key).encode()).hexdigest()[:40]
            base["client_order_id"] = client_id
            if amount is not None:
                base["notional"] = format(amount, ".2f")

            def skip(reason):
                return save(account_id, dict(base, reason=_REASONS[reason]))

            # Reconcile even a lost journal before considering any new submission.
            found = _lookup(session, base)
            if found is not None:
                return save(account_id, found)
            unresolved = db.execute(
                "SELECT run_key, result FROM executions WHERE account_id=? AND run_key != ?",
                (account_id, run_key),
            ).fetchall()
            for previous_key, encoded in unresolved:
                previous = json.loads(encoded)
                if previous.get("status") not in ("unknown", "submitting"):
                    continue
                reconciled = _lookup(session, previous)
                if reconciled is None or reconciled["status"] == "unknown":
                    return skip("pending")
                db.execute("UPDATE executions SET result=? WHERE account_id=? AND run_key=?",
                           (json.dumps(reconciled), account_id, previous_key))
                db.commit()
            if (account.get("status") != "ACTIVE" or account.get("currency") != "USD"
                    or any(account.get(k) is not False for k in
                           ("trading_blocked", "account_blocked", "trade_suspended_by_user"))):
                return skip("account")
            def market_open():
                clock = _get(session, "/v2/clock")
                stamp = datetime.fromisoformat(clock["timestamp"].replace("Z", "+00:00"))
                return (clock.get("is_open") is True and stamp.tzinfo is not None
                        and stamp.astimezone(ZoneInfo("America/New_York")).date().isoformat() == trade_date
                        and _today() == trade_date)
            if not market_open():
                return skip("closed")
            asset = _get(session, "/v2/assets/" + symbol)
            if (asset.get("symbol") != symbol or asset.get("class") != "us_equity"
                    or asset.get("status") != "active" or asset.get("tradable") is not True
                    or (side == "buy" and asset.get("fractionable") is not True)):
                return skip("asset")
            orders = _get(session, "/v2/orders", status="open", limit=500)
            if (not isinstance(orders, list) or len(orders) >= 500
                    or any(not isinstance(o, dict) or not isinstance(o.get("symbol"), str)
                           or o.get("side") not in ("buy", "sell") for o in orders)):
                return skip("pending")
            if any(o["symbol"] == symbol or (side == "buy" and o["side"] == "buy") for o in orders):
                return skip("pending")
            if side == "buy":
                # Refresh cash after open-order checks; never use buying_power.
                fresh = _get(session, "/v2/account")
                if (fresh.get("id") != account_id or fresh.get("status") != "ACTIVE"
                        or fresh.get("currency") != "USD" or any(fresh.get(k) is not False for k in
                        ("trading_blocked", "account_blocked", "trade_suspended_by_user"))
                        or _decimal(fresh["cash"]) < amount):
                    return skip("cash")
            else:
                positions = _get(session, "/v2/positions")
                if not isinstance(positions, list) or any(not isinstance(p, dict) for p in positions):
                    return skip("position")
                matches = [p for p in positions if p.get("symbol") == symbol]
                if len(matches) != 1 or matches[0].get("side") != "long":
                    return skip("position")
                position = matches[0]
                qty, total = _decimal(position.get("qty_available")), _decimal(position.get("qty"))
                if qty <= 0 or total <= 0 or qty > total:
                    return skip("position")
                base["quantity"] = _number(qty)
            if not market_open():
                return skip("closed")
            body = dict(symbol=symbol, side=side, type="market", time_in_force="day",
                        extended_hours=False, client_order_id=client_id,
                        position_intent="buy_to_open" if side == "buy" else "sell_to_close")
            body.update({"notional": base["notional"]} if side == "buy" else {"qty": base["quantity"]})
            # Durable ambiguous marker: any interruption from here forbids reposting.
            base = save(account_id, dict(base, status="unknown", reason=_REASONS["unknown"]))
            try:
                response = session.post(PAPER_URL + "/v2/orders", json=body,
                                        timeout=15, allow_redirects=False)
                if 200 <= response.status_code < 300:
                    result = _order_result(response.json(), base)
                elif 400 <= response.status_code < 500:
                    result = dict(base, status="rejected", reason=_REASONS["rejected"])
                else:
                    result = base
            except Exception:
                result = base
            return save(account_id, result)
    except Exception:
        # If a durable intent exists, preserve its ambiguity even on local failure.
        if base.get("status") == "unknown":
            return base
        return dict(base, status="error", reason=_REASONS["error"])
    finally:
        if db is not None:
            db.close()
        if lock is not None:
            lock.close()


def render_paper_execution(result: dict) -> str:
    """Render only validated scalar fields; never echo caller/broker prose."""
    status = result.get("status")
    if not isinstance(status, str) or status not in {"skipped", "submitted", "filled", "rejected", "unknown", "error"}:
        status = "error"
    reason = result.get("reason")
    if reason not in _REASONS.values():
        reason = _REASONS["error"]
    lines = ["### Alpaca paper execution", "", f"Status: **{status}**. {reason}"]
    for key in ("symbol", "side", "notional", "quantity", "client_order_id", "broker_status", "filled_qty", "filled_avg_price"):
        value = result.get(key)
        valid = isinstance(value, str) and bool(value) and len(value) <= 64
        if key == "symbol":
            valid = valid and bool(_SYMBOL.fullmatch(value))
        elif key == "side":
            valid = value in ("buy", "sell")
        elif key == "client_order_id":
            valid = valid and bool(re.fullmatch(r"paper-[a-f0-9]{40}", value))
        elif key == "broker_status":
            valid = valid and value in _BROKER_STATUSES
        else:
            valid = valid and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value))
        if valid:
            lines.append(f"- {key.replace('_', ' ').capitalize()}: `{value}`")
    lines.append("\nLast confirmed broker response only; no background fill tracking.")
    return "\n".join(lines)
