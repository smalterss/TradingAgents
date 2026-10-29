"""Read-only paper-account adapter; credentials never enter graph state."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from tradingagents.portfolio import PortfolioContext, Position

PAPER_URL = "https://paper-api.alpaca.markets"
_KEY_NAMES = ("ALPACA_API_KEY", "APCA_API_KEY_ID")
_SECRET_NAMES = ("ALPACA_API_SECRET", "APCA_API_SECRET_KEY")


class AlpacaPortfolioError(ValueError):
    """Safe-to-display failure without upstream bodies or credential values."""


def _credential(names):
    return next((os.environ[name].strip() for name in names if os.environ.get(name, "").strip()), "")


def alpaca_credentials_present() -> bool:
    return any(os.environ.get(name) for name in (*_KEY_NAMES, *_SECRET_NAMES))


def load_alpaca_portfolio() -> PortfolioContext:
    """Fetch only account balances and open positions from the paper API."""
    key, secret = _credential(_KEY_NAMES), _credential(_SECRET_NAMES)
    if not key or not secret:
        raise AlpacaPortfolioError("Alpaca portfolio requires an API key and secret in the environment.")
    try:
        with requests.Session() as session:
            session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
            def get(path):
                response = session.get(PAPER_URL + path, timeout=15, allow_redirects=False)
                if response.status_code != 200:
                    raise ValueError("unsuccessful response")
                return response.json()

            account = get("/v2/account")
            holdings = get("/v2/positions")
            if not isinstance(holdings, list):
                raise ValueError("invalid positions")
            positions = []
            for holding in holdings:
                quantity = abs(float(holding["qty"]))
                side = holding["side"]
                if side not in ("long", "short") or not holding["symbol"].strip():
                    raise ValueError("invalid position")
                positions.append(Position(
                    ticker=holding["symbol"],
                    quantity=-quantity if side == "short" else quantity,
                    average_price=holding["avg_entry_price"],
                ))
            return PortfolioContext(
                cash=account["cash"], currency=account["currency"], positions=positions
            )
    except Exception:
        raise AlpacaPortfolioError(
            "Alpaca paper portfolio could not be loaded. Check credentials, connectivity, and account access."
        ) from None


def resolve_portfolio(portfolio, config: dict, trade_date: str):
    """Resolve once at the run boundary, before checkpoint identity is computed."""
    if portfolio is not None:
        return portfolio
    if not config.get("alpaca_portfolio_enabled", alpaca_credentials_present()):
        return None
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    if str(trade_date) != today:
        raise AlpacaPortfolioError(
            "Current Alpaca holdings cannot be used for a historical analysis. "
            "Supply an explicit portfolio or disable TRADINGAGENTS_ALPACA_PORTFOLIO_ENABLED."
        )
    return load_alpaca_portfolio()
