"""Deterministic web tests: no models, network or credentials are contacted."""

import socket
import sys
from datetime import date
from queue import Queue
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tradingagents.default_config import build_default_config
from tradingagents.web.app import create_app, render_markdown
from tradingagents.web.config import MissingCredentials, run_config, validate_run
from tradingagents.web.worker import execute_run

_REAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def windows_asyncio_socketpair(_no_network, monkeypatch):
    """Windows asyncio uses a TCP socketpair internally, not for HTTP transport.

    Permit only socket.py's own socketpair connection; all app networking remains blocked.
    """
    blocked = socket.socket.connect

    def connect(sock, address):
        caller = sys._getframe(1)
        if (
            caller.f_code.co_name == "_fallback_socketpair"
            and caller.f_globals.get("__name__") == "socket"
            and address[0] in ("127.0.0.1", "::1")
        ):
            return _REAL_CONNECT(sock, address)
        return blocked(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


class FakeQueue(Queue):
    def close(self):
        pass


class FakeProcess:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.alive = False
        self.terminated = False
        self.joined = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False

    def join(self, timeout=None):
        assert not self.alive, "Never join a live queue producer"
        self.joined = True

    def close(self):
        pass


class FakeContext:
    Queue = FakeQueue
    Process = FakeProcess


@pytest.fixture
def base(tmp_path):
    config = build_default_config()
    config.update(
        results_dir=str(tmp_path),
        llm_provider="ollama",
        quick_think_provider=None,
        deep_think_provider=None,
    )
    return config


@pytest.fixture
def selection():
    return {
        "ticker": "aapl",
        "trade_date": date.today().isoformat(),
        "analysts": ["market", "social"],
        "quick_provider": "ollama",
        "deep_provider": "ollama",
        "quick_model": "qwen3:latest",
        "deep_model": "qwen3:latest",
        "output_language": "English",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    }


@pytest.fixture
def client(base):
    app = create_app(config=base, context=FakeContext())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def headers(client):
    return {
        "Origin": "http://127.0.0.1:8000",
        "X-CSRF-Token": client.get("/api/config").json()["csrf_token"],
    }


def test_lifecycle_complete_and_downloads(client, selection):
    assert client.get("/api/run").json()["status"] == "idle"
    assert client.get("/api/reports/markdown").status_code == 404
    h = headers(client)
    assert client.post("/api/run", json=selection, headers=h).json()["ticker"] == "AAPL"
    assert client.post("/api/run", json=selection, headers=h).status_code == 409
    manager = client.app.state.runs
    process = manager.process
    manager.events.put({"type": "running"})
    manager.events.put(
        {
            "type": "progress",
            "sections": {"market": "<script>alert(1)</script>"},
            "analyst_status": {"market": "completed"},
            "stage": "research",
        }
    )
    partial = client.get("/api/run").json()
    assert partial["status"] == "running"
    assert partial["analyst_status"]["market"] == "completed"
    assert "<script>" not in next(s for s in partial["sections"] if s["id"] == "market")["html"]
    from tradingagents.reporting import write_report_tree

    write_report_tree(
        {"final_trade_decision": "# Report\n<script>x</script>\n![x](https://evil/x)",
         "trade_date": selection["trade_date"]},
        "AAPL", manager.report_dir,
    )
    manager.events.put({"type": "completed", "rating": "Buy"})
    process.alive = False
    final = client.get("/api/run").json()
    assert final["status"] == "completed" and final["downloads"]
    assert final["rating"] == "Buy" and final["sections"] == partial["sections"]
    assert process.joined
    assert client.get("/api/reports/markdown").status_code == 200
    html = client.get("/api/reports/html")
    assert "<script>" not in html.text and "<img" not in html.text
    assert html.content == (manager.report_dir / "complete_report.html").read_bytes()
    assert "attachment" in html.headers["content-disposition"]
    assert client.get("/api/run/unknown").status_code == 404
    assert [
        s["id"] for s in client.post("/api/run", json=selection, headers=h).json()["sections"]
    ] == ["overview"]
    assert client.get("/api/reports/markdown").status_code == 404


@pytest.mark.parametrize("event", ["failed", "death", "stop"])
def test_terminal_partial(client, selection, event):
    client.post("/api/run", json=selection, headers=headers(client))
    manager = client.app.state.runs
    process = manager.process
    manager.events.put({"type": "progress", "sections": {"news": "Observed evidence"}})
    if event == "failed":
        manager.events.put({"type": "failed", "error": "SECRET"})
    elif event == "death":
        process.alive = False
    if event == "stop":
        result = client.post("/api/run/stop", headers=headers(client)).json()
        assert process.terminated and process.joined
    else:
        result = client.get("/api/run").json()
    assert result["status"] == ("stopped" if event == "stop" else "failed")
    assert any(s["id"] == "news" for s in result["sections"])
    assert not result["downloads"] and result["rating"] is None
    assert "SECRET" not in str(result)
    assert client.get("/api/reports/html").status_code == 404


def test_lifespan_terminates(base, selection):
    app = create_app(config=base, context=FakeContext())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.post("/api/run", json=selection, headers=headers(client))
        process = app.state.runs.process
    assert process.terminated and process.joined


@pytest.mark.parametrize(
    "host",
    ["evil.com", "127.0.0.1.evil.com", "127.1", "0.0.0.0", "user@localhost", "localhost/evil"],
)
def test_host_security(client, host):
    assert client.get("/api/config", headers={"host": host}).status_code == 403


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.com", "http://localhost:8000", "http://127.0.0.1:9999"]
)
def test_origin_security(client, selection, origin):
    h = headers(client)
    if origin is None:
        h.pop("Origin")
    else:
        h["Origin"] = origin
    assert client.post("/api/run", json=selection, headers=h).status_code == 403
    assert client.post("/api/run/stop", headers=h).status_code == 403


def test_token_and_headers(client, selection):
    h = headers(client)
    h["X-CSRF-Token"] = "wrong"
    assert client.post("/api/run", json=selection, headers=h).status_code == 403
    response = client.get("/api/config")
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ticker", "../../secret"),
        ("ticker", ".."),
        ("trade_date", "2999-01-01"),
        ("trade_date", "20250101"),
        ("trade_date", "2025-02-30"),
        ("analysts", []),
        ("analysts", ["bad"]),
        ("analysts", [123]),
        ("max_debate_rounds", True),
        ("max_debate_rounds", 0),
        ("max_risk_discuss_rounds", 11),
        ("max_risk_discuss_rounds", float("inf")),
        ("quick_provider", "bad"),
        ("quick_model", "<script>"),
        ("output_language", "x" * 81),
    ],
)
def test_validation(selection, key, value):
    selection[key] = value
    with pytest.raises(ValueError):
        validate_run(selection)


def test_credentials_and_private_config(client, selection, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    selection["quick_provider"] = "openai"
    response = client.post("/api/run", json=selection, headers=headers(client))
    assert response.status_code == 422 and "OPENAI_API_KEY" in response.text
    monkeypatch.setenv("OPENAI_API_KEY", "supersecret")
    config = client.get("/api/config").json()
    assert "supersecret" not in str(config)
    assert "backend_url" not in str(config) and "results_dir" not in str(config)
    assert next(p for p in config["providers"] if p["id"] == "openai")["configured"]
    validate_run(selection)


def test_endpoint_inheritance(base, selection):
    base.update(
        llm_provider="openai",
        backend_url="main-secret",
        deep_think_provider="anthropic",
        deep_think_backend_url="deep-secret",
    )
    selection.update(quick_provider="google", deep_provider="anthropic")
    result = run_config(base, selection)
    assert result["llm_provider"] == "google" and result["backend_url"] is None
    assert result["quick_think_backend_url"] is None
    assert result["deep_think_backend_url"] == "deep-secret"
    selection.update(quick_provider="openai", deep_provider="openai")
    result = run_config(base, selection)
    assert result["backend_url"] == "main-secret"
    assert result["deep_think_backend_url"] is None


def test_markdown_no_active_content():
    html = render_markdown(
        "<img src=x onerror=alert(1)>\n[click](javascript:alert(1))\n![x](//evil/x)\n<https://evil>"
    )
    assert "<img" not in html and "<a " not in html and "onerror=" in html
    assert "&lt;img" in html


class Graph:
    def __init__(self, analysts, config, debug):
        self.calls = []
        self.propagator = SimpleNamespace(get_graph_args=lambda: {})

    def create_run_state(self, ticker, day, asset_type="stock"):
        self.asset_type = asset_type
        self.calls.append("state")
        return {"trade_date": day}

    def begin_checkpoint(self, *args, **kwargs):
        self.calls.append("begin")
        return "saved-thread"

    def checkpoint_input(self, state):
        self.calls.append("input")
        return None

    def stream_run(self, state, **args):
        assert state is None
        assert args["config"]["configurable"]["thread_id"] == "saved-thread"
        yield [], {"market_report": "Evidence"}
        if getattr(self, "fail", False):
            raise RuntimeError("SECRET_KEY")
        yield [], {"final_trade_decision": "FINAL TRANSACTION PROPOSAL: **BUY**"}

    def record_decision(self, ticker, day, state):
        assert state["market_report"] == "Evidence"
        self.calls.append("record")

    def clear_checkpoint_on_success(self, *args, **kwargs):
        self.calls.append("clear")

    def end_checkpoint(self):
        self.calls.append("end")

    def save_reports(self, *args, **kwargs):
        self.calls.append("save")


@pytest.mark.parametrize("fail", [False, True])
def test_worker_checkpoint_lifecycle(base, selection, tmp_path, fail, caplog):
    queue = Queue()
    graph = Graph([], base, False)
    graph.fail = fail
    execute_run(queue, selection, base, tmp_path, graph_factory=lambda *a, **k: graph)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events[-1]["type"] == ("failed" if fail else "completed")
    assert any(e.get("sections", {}).get("market") == "Evidence" for e in events)
    assert graph.calls == (
        ["state", "begin", "input", "end"]
        if fail
        else ["state", "begin", "input", "record", "clear", "end", "save"]
    )
    assert "SECRET_KEY" not in caplog.text and "SECRET_KEY" not in str(events)


def test_chatgpt_presence_does_not_authenticate(selection, monkeypatch):
    from tradingagents.llm_clients import chatgpt_auth

    monkeypatch.setattr(chatgpt_auth, "signed_in_as", lambda: None)
    monkeypatch.setattr(chatgpt_auth, "sign_in", lambda: pytest.fail("Must not log in"))
    selection["quick_provider"] = "chatgpt"
    with pytest.raises(MissingCredentials, match="Sign in"):
        validate_run(selection)


def _spawn_complete(events, selection, config, report_dir):
    events.put({"type": "running"})
    # Larger than a pipe buffer: joining before consuming would deadlock.
    events.put({"type": "progress", "sections": {"market": "Evidence " * 20000}})
    events.put({"type": "completed", "rating": "Hold"})


def _spawn_wait(events, selection, config, report_dir):
    import time

    events.put({"type": "running"})
    time.sleep(60)


class SpawnTestContext:
    def __init__(self, target):
        import multiprocessing

        self.context = multiprocessing.get_context("spawn")
        self.target = target

    def Queue(self):
        return self.context.Queue()

    def Process(self, *, target, args):
        return self.context.Process(target=self.target, args=args)


def test_real_spawn_full_queue_completion(base, selection):
    import time

    from tradingagents.web.app import RunManager

    manager = RunManager(base, SpawnTestContext(_spawn_complete))
    try:
        manager.start(validate_run(selection))
        deadline = time.monotonic() + 15
        while manager.process is not None and time.monotonic() < deadline:
            manager.refresh()
            time.sleep(0.02)
        assert manager.process is None
        assert manager.snapshot()["status"] == "completed"
        assert any(s["id"] == "market" for s in manager.snapshot()["sections"])
    finally:
        manager.stop()


def test_real_spawn_termination(base, selection):
    from tradingagents.web.app import RunManager

    manager = RunManager(base, SpawnTestContext(_spawn_wait))
    manager.start(validate_run(selection))
    assert manager.process.is_alive()
    assert manager.stop()["status"] == "stopped"
    assert manager.process is None


@pytest.mark.parametrize("method", ["create_run_state", "begin_checkpoint", "record_decision"])
def test_worker_cleanup_on_lifecycle_failure(base, selection, tmp_path, method):
    graph = Graph([], base, False)

    def fail(*args, **kwargs):
        raise RuntimeError("secret response body")

    setattr(graph, method, fail)
    queue = Queue()
    execute_run(queue, selection, base, tmp_path, graph_factory=lambda *a, **k: graph)
    assert graph.calls[-1] == "end"
    assert "clear" not in graph.calls and "save" not in graph.calls
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events[-1] == {"type": "failed"}
    assert "secret response body" not in str(events)
