"""All HTTP is mocked: this suite must never submit an actual order."""

import json
import sqlite3
from decimal import Decimal

import pytest
import requests

from tradingagents import paper_execution as pe


class Response:
    def __init__(self, data=None, status=200):
        self.status_code = status
        self.data = data

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Broker:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.posts = []
        self.account = {
            "id": "private-account",
            "status": "ACTIVE",
            "currency": "USD",
            "cash": "1000",
            "buying_power": "999999",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }
        self.clock = {
            "is_open": True,
            "timestamp": "2026-06-15T12:00:00-04:00",
            "next_close": "2026-06-15T16:00:00-04:00",
        }
        self.asset = dict(
            symbol="AAPL",
            **{"class": "us_equity"},
            status="active",
            tradable=True,
            fractionable=True,
        )
        self.orders = []
        self.positions = [{"symbol": "AAPL", "side": "long", "qty": "5", "qty_available": "4.25"}]
        self.lookup = Response(status=404)
        self.post_response = None
        self.before_post = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.check(url, kwargs)
        path = url.removeprefix(pe.PAPER_URL)
        self.calls.append((path, kwargs))
        if path == "/v2/orders:by_client_order_id":
            return self.lookup
        data = {
            "/v2/account": self.account,
            "/v2/clock": self.clock,
            "/v2/assets/AAPL": self.asset,
            "/v2/orders": self.orders,
            "/v2/positions": self.positions,
        }[path]
        return Response(data)

    def check(self, url, kwargs):
        assert url.startswith("https://paper-api.alpaca.markets/v2/")
        assert kwargs["timeout"] == 15
        assert kwargs["allow_redirects"] is False

    def post(self, url, **kwargs):
        self.check(url, kwargs)
        self.posts.append(kwargs["json"])
        if self.before_post:
            self.before_post()
        if isinstance(self.post_response, BaseException):
            raise self.post_response
        return self.post_response or Response(
            dict(kwargs["json"], status="accepted", filled_qty="0")
        )


@pytest.fixture
def env(monkeypatch, tmp_path):
    broker = Broker()
    monkeypatch.setattr(pe.requests, "Session", lambda: broker)
    monkeypatch.setattr(pe, "_today", lambda: "2026-06-15")
    for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "SECRET-KEY")
    monkeypatch.setenv("ALPACA_API_SECRET", "SECRET-TOKEN")
    config = {
        "alpaca_paper_execution_enabled": True,
        "paper_execution_journal_path": str(tmp_path / "paper.sqlite3"),
    }
    state = {"final_rating": "Buy", "portfolio_decision_structured": True, "buy_notional_usd": 100}

    def execute(**overrides):
        args = {
            "final_state": state,
            "ticker": "AAPL",
            "trade_date": "2026-06-15",
            "run_key": "run1",
            "config": config,
        }
        args.update(overrides)
        return pe.execute_paper_decision(**args)

    return broker, config, state, execute


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_disabled_no_io(env, value):
    broker, config, _, execute = env
    config["alpaca_paper_execution_enabled"] = value
    assert execute()["status"] == "skipped"
    assert not broker.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"final_rating": "Hold"},
        {"final_rating": "Overweight"},
        {"final_rating": "Underweight"},
        {"final_rating": "REVIEW"},
        {"final_rating": "buy"},
        {"final_rating": "Buy now"},
        {"portfolio_decision_structured": False},
        {"portfolio_decision_structured": 1},
        {"buy_notional_usd": True},
        {"buy_notional_usd": "100"},
        {"buy_notional_usd": None},
        {"buy_notional_usd": float("nan")},
        {"buy_notional_usd": float("inf")},
        {"buy_notional_usd": 0},
        {"buy_notional_usd": -1},
        {"buy_notional_usd": 1.001},
        {"buy_notional_usd": "Buy $100"},
        {"buy_notional_usd": 10**30},
    ],
)
def test_structured_gate(env, changes):
    broker, _, state, execute = env
    state.update(changes)
    assert execute()["status"] == "skipped"
    assert not broker.posts


@pytest.mark.parametrize(
    "overrides",
    [
        {"trade_date": "2020-01-01"},
        {"ticker": "BTC/USD"},
        {"ticker": "aapl"},
        {"ticker": "AAPL<script>"},
    ],
)
def test_date_symbol_gate(env, overrides):
    broker, _, _, execute = env
    assert execute(**overrides)["status"] == "skipped"
    assert not broker.posts


def test_buy_body_and_durable_intent_and_duplicate(env):
    broker, config, state, execute = env
    state["buy_notional_usd"] = Decimal("100.25")

    def inspect_intent():
        with sqlite3.connect(config["paper_execution_journal_path"]) as db:
            row = db.execute("SELECT result FROM executions").fetchone()
            assert json.loads(row[0])["status"] == "unknown"
        # The separate process mutex still holds a write lock through the POST.
        with (
            sqlite3.connect(config["paper_execution_journal_path"] + ".lock", timeout=0) as db,
            pytest.raises(sqlite3.OperationalError),
        ):
            db.execute("BEGIN IMMEDIATE")

    broker.before_post = inspect_intent
    result = execute()
    assert result["status"] == "submitted"
    assert result["broker_status"] == "accepted"
    body = broker.posts[0]
    assert body == {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "extended_hours": False,
        "client_order_id": result["client_order_id"],
        "position_intent": "buy_to_open",
        "notional": "100.25",
    }
    assert len(result["client_order_id"]) == 46
    assert execute()["status"] == "unknown"  # 404 never authorizes another POST
    assert len(broker.posts) == 1
    assert sum(path == "/v2/clock" for path, _ in broker.calls) == 2


@pytest.mark.parametrize(
    "change,reason",
    [
        ("closed", "closed"),
        ("fractionable", "asset"),
        ("not_tradable", "asset"),
        ("asset_symbol", "asset"),
        ("crypto", "asset"),
        ("inactive", "account"),
        ("blocked", "account"),
        ("currency", "account"),
        ("cash", "cash"),
        ("target_buy", "pending"),
        ("target_sell", "pending"),
        ("other_buy", "pending"),
        ("truncated", "pending"),
        ("malformed_orders", "pending"),
    ],
)
def test_preflight_gates(env, change, reason):
    broker, _, _, execute = env
    if change == "closed":
        broker.clock["is_open"] = False
    elif change == "fractionable":
        broker.asset["fractionable"] = False
    elif change == "not_tradable":
        broker.asset["tradable"] = False
    elif change == "asset_symbol":
        broker.asset["symbol"] = "MSFT"
    elif change == "crypto":
        broker.asset["class"] = "crypto"
    elif change == "inactive":
        broker.account["status"] = "INACTIVE"
    elif change == "blocked":
        broker.account["trade_suspended_by_user"] = True
    elif change == "currency":
        broker.account["currency"] = "EUR"
    elif change == "cash":
        broker.account["cash"] = "99.99"
    elif change == "target_buy":
        broker.orders = [{"symbol": "AAPL", "side": "buy"}]
    elif change == "target_sell":
        broker.orders = [{"symbol": "AAPL", "side": "sell"}]
    elif change == "other_buy":
        broker.orders = [{"symbol": "MSFT", "side": "buy"}]
    elif change == "truncated":
        broker.orders = [{"symbol": "MSFT", "side": "sell"}] * 500
    elif change == "malformed_orders":
        broker.orders = [{}]
    result = execute()
    assert result["status"] == "skipped"
    assert result["reason"] == pe._REASONS[reason]
    assert not broker.posts
    # A gate changing later cannot turn this run into a trade.
    broker.clock["is_open"] = True
    assert execute() == result


def test_unrelated_sell_does_not_block_buy(env):
    broker, _, _, execute = env
    broker.orders = [{"symbol": "MSFT", "side": "sell"}]
    assert execute()["status"] == "submitted"


def test_sell_closes_all_available_ignores_size(env):
    broker, _, state, execute = env
    state.update(final_rating="Sell", buy_notional_usd="garbage")
    broker.asset["fractionable"] = False
    broker.account["cash"] = "-100"
    assert execute()["quantity"] == "4.25"
    assert broker.posts[0]["qty"] == "4.25"
    assert "notional" not in broker.posts[0]


@pytest.mark.parametrize(
    "position",
    [
        None,
        {"side": "short", "qty": "5", "qty_available": "5"},
        {"side": "long", "qty": "5", "qty_available": "0"},
        {"side": "long", "qty": "5"},
        {"side": "long", "qty": "5", "qty_available": "6"},
        {"side": "long", "qty": "-5", "qty_available": "4"},
    ],
)
def test_no_short_or_unavailable_sells(env, position):
    broker, _, state, execute = env
    state["final_rating"] = "Sell"
    broker.positions = [dict(symbol="AAPL", **position)] if position else []
    assert execute()["status"] in ("skipped", "error")
    assert not broker.posts


@pytest.mark.parametrize(
    "response",
    [
        requests.Timeout("SECRET-TOKEN"),
        Response(status=503),
        Response(status=302),
        Response(ValueError("SECRET-KEY")),
        Response({}),
        Response({"symbol": "MSFT", "side": "buy", "client_order_id": "wrong", "status": "filled"}),
    ],
)
def test_ambiguous_never_resubmits_and_reconciles(env, response):
    broker, _, _, execute = env
    broker.post_response = response
    result = execute()
    assert result["status"] == "unknown"
    assert execute()["status"] == "unknown"
    assert len(broker.posts) == 1
    broker.lookup = Response(
        {
            "symbol": "AAPL",
            "side": "buy",
            "client_order_id": result["client_order_id"],
            "status": "filled",
            "filled_qty": "0.5",
            "filled_avg_price": "200",
        }
    )
    filled = execute()
    assert filled["status"] == "filled"
    assert filled["filled_avg_price"] == "200"
    assert len(broker.posts) == 1
    assert execute() == filled


def test_rejection_terminal_and_sanitized(env):
    broker, _, _, execute = env
    broker.post_response = Response({"message": "SECRET-KEY SECRET-TOKEN private-account"}, 422)
    result = execute()
    assert result["status"] == "rejected"
    assert execute() == result
    assert len(broker.posts) == 1
    for secret in ("SECRET-KEY", "SECRET-TOKEN", "private-account"):
        assert secret not in json.dumps(result)
        assert secret not in pe.render_paper_execution(result)


@pytest.mark.parametrize(
    "status,extra,expected",
    [
        ("filled", {}, "unknown"),
        ("filled", {"filled_qty": "1", "filled_avg_price": "0"}, "unknown"),
        ("hacked", {}, "unknown"),
        ("partially_filled", {"filled_qty": "0.1"}, "submitted"),
    ],
)
def test_broker_status_and_fill_evidence(env, status, extra, expected):
    broker, _, _, execute = env

    def respond():
        broker.post_response = Response(dict(broker.posts[-1], status=status, **extra))

    broker.before_post = respond
    assert execute()["status"] == expected


def test_lost_journal_lookup_prevents_submit(env):
    broker, config, _, execute = env
    first = execute()
    with sqlite3.connect(config["paper_execution_journal_path"]) as db:
        db.execute("DELETE FROM executions")
    broker.lookup = Response(
        {
            "symbol": "AAPL",
            "side": "buy",
            "client_order_id": first["client_order_id"],
            "status": "new",
        }
    )
    assert execute()["status"] == "submitted"
    assert len(broker.posts) == 1


def test_crash_marker_recovery(env):
    broker, config, _, execute = env
    result = execute()
    result.update(status="submitting", reason=pe._REASONS["unknown"])
    with sqlite3.connect(config["paper_execution_journal_path"]) as db:
        db.execute("UPDATE executions SET result=?", (json.dumps(result),))
    assert execute()["status"] == "unknown"
    assert len(broker.posts) == 1


def test_local_database_failure_never_posts(env, tmp_path):
    broker, config, _, execute = env
    config["paper_execution_journal_path"] = str(tmp_path)  # directory, not database
    assert execute()["status"] == "error"
    assert not broker.posts


def test_changed_clock_before_post(env):
    broker, _, _, execute = env
    get = broker.get
    count = 0

    def changing(url, **kwargs):
        nonlocal count
        if url.endswith("/v2/clock"):
            count += 1
            if count == 2:
                broker.clock["is_open"] = False
        return get(url, **kwargs)

    broker.get = changing
    assert execute()["status"] == "skipped"
    assert not broker.posts


def test_does_not_submit_near_market_close(env):
    broker, _, _, execute = env
    broker.clock["timestamp"] = "2026-06-15T15:59:30-04:00"
    assert execute()["reason"] == pe._REASONS["closed"]
    assert not broker.posts


def test_unknown_submission_blocks_new_run_until_reconciled(env):
    broker, _, _, execute = env
    broker.post_response = requests.Timeout("private")
    first = execute()
    assert first["status"] == "unknown"
    assert execute(run_key="run2")["reason"] == pe._REASONS["pending"]
    assert len(broker.posts) == 1


def test_prior_order_can_reconcile_after_date_changes(env, monkeypatch):
    broker, _, _, execute = env
    first = execute()
    broker.lookup = Response(
        {
            "symbol": "AAPL",
            "side": "buy",
            "client_order_id": first["client_order_id"],
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "100",
        }
    )
    monkeypatch.setattr(pe, "_today", lambda: "2026-06-16")
    assert execute()["status"] == "filled"
    assert len(broker.posts) == 1


def test_renderer_does_not_echo_arbitrary_text():
    text = pe.render_paper_execution(
        {
            "status": "<script>",
            "reason": "SECRET",
            "symbol": "<img>",
            "broker_status": "SECRET",
            "filled_qty": "SECRET",
            "side": "SECRET",
        }
    )
    assert "SECRET" not in text and "<" not in text


def test_credentials_aliases_and_missing(env, monkeypatch):
    broker, _, _, execute = env
    monkeypatch.delenv("ALPACA_API_KEY")
    monkeypatch.delenv("ALPACA_API_SECRET")
    assert execute()["status"] == "skipped"
    assert not broker.calls
    monkeypatch.setenv("APCA_API_KEY_ID", "alias-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "alias-secret")
    # Missing-credentials skip is durable for the first run.
    assert execute()["status"] == "skipped"
    assert execute(run_key="run2")["status"] == "submitted"
    assert broker.headers["APCA-API-KEY-ID"] == "alias-key"


@pytest.mark.parametrize("code", [301, 401, 500])
def test_preflight_http_failure_sanitized(env, code):
    broker, _, _, execute = env
    broker.get = lambda *a, **k: Response({"message": "SECRET-TOKEN"}, code)
    result = execute()
    assert result["status"] == "error"
    assert "SECRET" not in json.dumps(result)
    assert not broker.posts


def test_fresh_cash_not_initial_cash_or_margin(env):
    broker, _, _, execute = env
    original = broker.get
    count = 0

    def get(url, **kwargs):
        nonlocal count
        if url.endswith("/v2/account"):
            count += 1
            if count == 2:
                broker.account = dict(broker.account, cash="0", buying_power="100000")
        return original(url, **kwargs)

    broker.get = get
    assert execute()["reason"] == pe._REASONS["cash"]
    assert not broker.posts


def test_malformed_rating_and_formatter_are_safe(env):
    _, _, state, execute = env
    state["final_rating"] = ["Buy"]
    assert execute()["status"] == "skipped"
    assert "error" in pe.render_paper_execution({"status": [], "broker_status": []})


def test_interruption_after_intent_commit_never_reposts(env):
    broker, _, _, execute = env
    broker.post_response = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        execute()
    broker.post_response = None
    assert execute()["status"] == "unknown"
    assert len(broker.posts) == 1


def test_mismatched_reconciliation_is_unknown(env):
    broker, _, _, execute = env
    broker.post_response = requests.Timeout()
    result = execute()
    broker.lookup = Response(
        {
            "symbol": "MSFT",
            "side": "buy",
            "status": "filled",
            "client_order_id": result["client_order_id"],
            "filled_qty": "1",
            "filled_avg_price": "100",
        }
    )
    assert execute()["status"] == "unknown"
    assert len(broker.posts) == 1
