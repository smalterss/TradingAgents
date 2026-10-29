"""Read-only Alpaca paper snapshots, with no ambient credentials or network."""
from datetime import datetime as real_datetime
from unittest.mock import MagicMock, Mock

import pytest
import requests

from tradingagents import alpaca_portfolio as alpaca
from tradingagents.portfolio import PortfolioContext

pytestmark = pytest.mark.unit

CREDENTIAL_NAMES = (
    "ALPACA_API_KEY", "APCA_API_KEY_ID",
    "ALPACA_API_SECRET", "APCA_API_SECRET_KEY",
)
KEY = "test-only-key"
SECRET = "test-only-secret"
SAFE_ERROR = (
    "Alpaca paper portfolio could not be loaded. "
    "Check credentials, connectivity, and account access."
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("TRADINGAGENTS_ALPACA_PORTFOLIO_ENABLED", raising=False)


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", KEY)
    monkeypatch.setenv("ALPACA_API_SECRET", SECRET)


def response(payload, status=200):
    result = Mock(spec=["status_code", "json"])
    result.status_code = status
    result.json.return_value = payload
    return result


@pytest.fixture
def session(monkeypatch):
    # Only GET exists: an accidental trading verb fails rather than reaching HTTP.
    client = MagicMock(spec=["headers", "get", "__enter__", "__exit__"])
    client.headers = {}
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = [
        response({"cash": "123.45", "currency": "USD", "buying_power": "9999"}),
        response([]),
    ]
    factory = Mock(return_value=client)
    monkeypatch.setattr(alpaca.requests, "Session", factory)
    client.factory = factory
    return client


@pytest.fixture
def today(monkeypatch):
    clock = Mock()
    clock.now.return_value = real_datetime(2026, 2, 11, 12)
    monkeypatch.setattr(alpaca, "datetime", clock)
    return clock


def test_fixed_paper_get_endpoints_headers_timeout_and_no_redirects(credentials, session):
    book = alpaca.load_alpaca_portfolio()
    session.factory.assert_called_once_with()
    session.__enter__.assert_called_once_with()
    session.__exit__.assert_called_once_with(None, None, None)
    assert session.headers == {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}
    assert session.get.call_args_list == [
        (("https://paper-api.alpaca.markets/v2/account",),
         {"timeout": 15, "allow_redirects": False}),
        (("https://paper-api.alpaca.markets/v2/positions",),
         {"timeout": 15, "allow_redirects": False}),
    ]
    assert KEY not in book.model_dump_json()
    assert SECRET not in book.model_dump_json()


def test_long_short_and_fractional_numeric_mapping(credentials, session):
    session.get.side_effect = [
        response({"cash": "-12.50", "currency": "USD"}),
        response([
            {"symbol": "AAPL", "qty": "4", "side": "long", "avg_entry_price": "125.25"},
            {"symbol": "TSLA", "qty": "-2.5", "side": "short", "avg_entry_price": "200"},
            {"symbol": "BTCUSD", "qty": "0.125", "side": "long", "avg_entry_price": "45000.50"},
            {"symbol": "MSFT", "qty": "0.25", "side": "short", "avg_entry_price": "300.75"},
        ]),
    ]
    book = alpaca.load_alpaca_portfolio()
    assert book.model_dump() == {
        "cash": -12.5, "currency": "USD", "positions": [
            {"ticker": "AAPL", "quantity": 4.0, "average_price": 125.25},
            {"ticker": "TSLA", "quantity": -2.5, "average_price": 200.0},
            {"ticker": "BTCUSD", "quantity": 0.125, "average_price": 45000.5},
            {"ticker": "MSFT", "quantity": -0.25, "average_price": 300.75},
        ],
    }


def test_empty_book_and_cash_not_buying_power(credentials, session):
    book = alpaca.load_alpaca_portfolio()
    assert isinstance(book, PortfolioContext)
    assert book.positions == []
    assert book.cash == 123.45
    assert book.currency == "USD"
    assert "buying_power" not in book.model_dump()


@pytest.mark.parametrize("key_name", CREDENTIAL_NAMES[:2])
@pytest.mark.parametrize("secret_name", CREDENTIAL_NAMES[2:])
def test_credential_aliases(monkeypatch, session, key_name, secret_name):
    monkeypatch.setenv(key_name, "  " + KEY + "  ")
    monkeypatch.setenv(secret_name, "  " + SECRET + "  ")
    assert alpaca.alpaca_credentials_present()
    alpaca.load_alpaca_portfolio()
    assert session.headers == {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}


def test_primary_credentials_win_over_aliases(monkeypatch, credentials, session):
    monkeypatch.setenv("APCA_API_KEY_ID", "unused-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "unused-secret")
    alpaca.load_alpaca_portfolio()
    assert session.headers == {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}


def test_blank_primary_credentials_fall_back_to_aliases(monkeypatch, session):
    monkeypatch.setenv("ALPACA_API_KEY", "  ")
    monkeypatch.setenv("ALPACA_API_SECRET", "  ")
    monkeypatch.setenv("APCA_API_KEY_ID", KEY)
    monkeypatch.setenv("APCA_API_SECRET_KEY", SECRET)
    alpaca.load_alpaca_portfolio()
    assert session.headers == {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}


@pytest.mark.parametrize("name", [None, *CREDENTIAL_NAMES])
def test_missing_or_partial_credentials_fail_before_session(monkeypatch, session, name):
    if name:
        monkeypatch.setenv(name, KEY)
    assert alpaca.alpaca_credentials_present() is (name is not None)
    with pytest.raises(alpaca.AlpacaPortfolioError, match="requires an API key and secret"):
        alpaca.load_alpaca_portfolio()
    session.factory.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 429, 500])
@pytest.mark.parametrize("endpoint", [0, 1], ids=["account", "positions"])
def test_unsuccessful_status_is_sanitized(credentials, session, status, endpoint):
    failed = response({"message": KEY + SECRET}, status)
    replies = [response({"cash": "1", "currency": "USD"}), response([])]
    replies[endpoint] = failed
    session.get.side_effect = replies
    with pytest.raises(alpaca.AlpacaPortfolioError) as caught:
        alpaca.load_alpaca_portfolio()
    assert str(caught.value) == SAFE_ERROR
    assert caught.value.__suppress_context__
    failed.json.assert_not_called()
    assert session.get.call_count == endpoint + 1


@pytest.mark.parametrize("failure", [
    requests.Timeout(KEY + SECRET),
    requests.ConnectionError(KEY + SECRET),
    ValueError("invalid JSON " + KEY + SECRET),
])
@pytest.mark.parametrize("endpoint", [0, 1], ids=["account", "positions"])
def test_transport_and_json_errors_are_sanitized(credentials, session, failure, endpoint):
    failed = response(None)
    failed.json.side_effect = failure
    replies = [response({"cash": "1", "currency": "USD"}), response([])]
    if isinstance(failure, requests.RequestException):
        replies[endpoint] = failure
    else:
        replies[endpoint] = failed
    session.get.side_effect = replies
    with pytest.raises(alpaca.AlpacaPortfolioError) as caught:
        alpaca.load_alpaca_portfolio()
    assert str(caught.value) == SAFE_ERROR
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("account", [
    None, [], {}, {"currency": "USD", "buying_power": "100"},
    {"cash": "bad", "currency": "USD"},
    {"cash": "NaN", "currency": "USD"},
    {"cash": "Infinity", "currency": "USD"},
    {"cash": "1"},
    {"cash": None, "currency": "USD"},
    {"cash": "1", "currency": None},
    {"cash": "1", "currency": "  "},
])
def test_malformed_account_is_sanitized(credentials, session, account):
    session.get.side_effect = [response(account), response([])]
    with pytest.raises(alpaca.AlpacaPortfolioError) as caught:
        alpaca.load_alpaca_portfolio()
    assert str(caught.value) == SAFE_ERROR


@pytest.mark.parametrize("holdings", [None, {}, "positions", [None], [{}]])
def test_malformed_positions_is_sanitized(credentials, session, holdings):
    session.get.side_effect = [response({"cash": "1", "currency": "USD"}), response(holdings)]
    with pytest.raises(alpaca.AlpacaPortfolioError) as caught:
        alpaca.load_alpaca_portfolio()
    assert str(caught.value) == SAFE_ERROR


@pytest.mark.parametrize("field,value", [
    ("qty", "NaN"), ("qty", "Infinity"), ("qty", "not-numeric"),
    ("avg_entry_price", "NaN"), ("avg_entry_price", "-Infinity"),
    ("avg_entry_price", "not-numeric"), ("side", "invalid"), ("symbol", "  "),
])
def test_invalid_position_values_are_sanitized(credentials, session, field, value):
    holding = {"symbol": "AAPL", "qty": "1", "side": "long", "avg_entry_price": "10"}
    holding[field] = value
    session.get.side_effect = [response({"cash": "1", "currency": "USD"}), response([holding])]
    with pytest.raises(alpaca.AlpacaPortfolioError) as caught:
        alpaca.load_alpaca_portfolio()
    assert str(caught.value) == SAFE_ERROR


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_portfolio_has_precedence_even_for_historical_dates(credentials, session, enabled):
    explicit = PortfolioContext(cash=0, positions=[])
    assert alpaca.resolve_portfolio(explicit, {"alpaca_portfolio_enabled": enabled}, "2000-01-01") is explicit
    session.factory.assert_not_called()


def test_disabled_does_not_fetch_even_with_credentials_or_historical_date(credentials, session):
    assert alpaca.resolve_portfolio(None, {"alpaca_portfolio_enabled": False}, "2000-01-01") is None
    session.factory.assert_not_called()


def test_no_credentials_defaults_to_no_context(session):
    assert alpaca.resolve_portfolio(None, {}, "2000-01-01") is None
    session.factory.assert_not_called()


def test_explicitly_enabled_without_credentials_fails(today, session):
    with pytest.raises(alpaca.AlpacaPortfolioError, match="requires an API key and secret"):
        alpaca.resolve_portfolio(None, {"alpaca_portfolio_enabled": True}, "2026-02-11")
    session.factory.assert_not_called()


@pytest.mark.parametrize("date", ["2000-01-01", "2026-02-10", "2026-02-12"])
def test_noncurrent_dates_rejected_before_fetch(credentials, today, session, date):
    with pytest.raises(alpaca.AlpacaPortfolioError, match="historical analysis"):
        alpaca.resolve_portfolio(None, {}, date)
    session.factory.assert_not_called()


@pytest.mark.parametrize("config", [{}, {"alpaca_portfolio_enabled": True}])
def test_current_date_fetches_one_snapshot_in_new_york(credentials, today, session, config):
    book = alpaca.resolve_portfolio(None, config, "2026-02-11")
    assert isinstance(book, PortfolioContext)
    assert book.cash == 123.45
    session.factory.assert_called_once_with()
    assert session.get.call_count == 2
    today.now.assert_called_once()
    assert today.now.call_args.args[0].key == "America/New_York"
