"""Single-user loopback dashboard; one spawn worker and one current run."""

import asyncio
import copy
import logging
import multiprocessing
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt

from tradingagents.web.config import (
    ANALYSTS,
    MissingCredentials,
    public_config,
    run_config,
    validate_run,
)
from tradingagents.web.worker import TITLES, execute_run

LOG = logging.getLogger(__name__)
ACTIVE = ("starting", "running")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def render_markdown(text):
    # No raw HTML, clickable links, images, autolinks or remote resources.
    return (
        MarkdownIt("commonmark", {"html": False})
        .enable("table")
        .disable(["image", "link", "autolink"])
        .render(text)
    )


def idle_snapshot():
    return {
        "id": None,
        "status": "idle",
        "ticker": "",
        "trade_date": "",
        "selected_analysts": [],
        "started_at": None,
        "elapsed_seconds": 0,
        "sections": [],
        "stage": "analysts",
        "analyst_status": dict.fromkeys(ANALYSTS, "pending"),
        "rating": None,
        "error": None,
        "memory_note": "",
        "downloads": False,
    }


class RunManager:
    def __init__(self, base, context=None):
        self.base = copy.deepcopy(base)
        self.context = context or multiprocessing.get_context("spawn")
        self.lock = threading.RLock()
        self.current = idle_snapshot()
        self.process = self.events = None
        self.started = self.ended = None
        self.report_dir = None
        self.sections = {}

    def _drain(self):
        if self.events is None:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except Empty:
                break
            kind = event.get("type")
            if self.current["status"] not in ACTIVE:
                continue
            if kind == "running":
                self.current["status"] = "running"
                for a in self.current["selected_analysts"]:
                    self.current["analyst_status"][a] = "running"
            if kind in ("progress", "completed"):
                for key, text in event.get("sections", {}).items():
                    if key in TITLES and isinstance(text, str):
                        self.sections[key] = {
                            "id": key,
                            "title": TITLES[key],
                            "html": render_markdown(text),
                        }
                if event.get("stage") in ("analysts", "research", "trader", "risk", "decision"):
                    self.current["stage"] = event["stage"]
                for a in self.current["selected_analysts"]:
                    status = event.get("analyst_status", {}).get(a)
                    if status in ("pending", "running", "completed"):
                        self.current["analyst_status"][a] = status
                self.current["memory_note"] = event.get("memory_note", "")
            if kind in ("completed", "failed"):
                self.current["status"] = kind
                self.ended = time.monotonic()
                if kind == "completed":
                    self.current["rating"] = event.get("rating")
                    self.current["downloads"] = True
                else:
                    self.current["error"] = (
                        "Alpaca paper portfolio unavailable. Check credentials and connectivity. "
                        "Past-date analyses require disabling TRADINGAGENTS_ALPACA_PORTFOLIO_ENABLED."
                        if event.get("reason") == "alpaca_portfolio"
                        else "Analysis failed. Check local configuration and server logs."
                    )

    def refresh(self):
        with self.lock:
            self._drain()
            if self.process is not None and not self.process.is_alive():
                # Queue completion ordering: see tradingagents-web SPEC.
                self.process.join(timeout=0)
                self._drain()
                if self.current["status"] in ACTIVE:
                    self.current["status"] = "failed"
                    self.current["error"] = "Analysis worker exited unexpectedly."
                    self.ended = time.monotonic()
                self._release()

    def _release(self):
        if self.events is not None:
            self.events.close()
        if self.process is not None:
            self.process.close()
        self.events = self.process = None

    def snapshot(self):
        with self.lock:
            self.refresh()
            result = copy.deepcopy(self.current)
            result["sections"] = [
                copy.deepcopy(self.sections[k]) for k in TITLES if k in self.sections
            ]
            if self.started is not None:
                result["elapsed_seconds"] = round(
                    (self.ended or time.monotonic()) - self.started, 1
                )
            return result

    def start(self, selection):
        with self.lock:
            self.refresh()
            if self.process is not None or self.current["status"] in ACTIVE:
                raise HTTPException(409, "An analysis is already active.")
            run_id = uuid.uuid4().hex
            self.current = idle_snapshot()
            self.current.update(
                id=run_id,
                status="starting",
                ticker=selection["ticker"],
                trade_date=selection["trade_date"],
                selected_analysts=selection["analysts"],
                started_at=datetime.now(UTC).isoformat(),
            )
            self.started, self.ended = time.monotonic(), None
            self.sections = {
                "overview": {
                    "id": "overview",
                    "title": TITLES["overview"],
                    "html": render_markdown(
                        f"## {selection['ticker']} · {selection['trade_date']}\n\n"
                        "Investment research only. No trades are executed."
                    ),
                }
            }
            self.report_dir = Path(self.base["results_dir"]) / "web" / run_id
            self.events = self.context.Queue()
            self.process = self.context.Process(
                target=execute_run,
                args=(
                    self.events,
                    selection,
                    run_config(self.base, selection),
                    str(self.report_dir),
                ),
            )
            try:
                self.process.start()
            except Exception as exc:
                LOG.error("Unable to start research worker (%s)", type(exc).__name__)
                self.current.update(status="failed", error="Unable to start analysis worker.")
                self.ended = time.monotonic()
                self._release()
            return self.snapshot()

    def stop(self):
        with self.lock:
            self.refresh()
            if self.process is not None:
                if self.process.is_alive():
                    # Termination and queue ownership: see tradingagents-web SPEC.
                    self.process.terminate()
                    self.process.join(timeout=5)
                    if self.process.is_alive():
                        self.process.kill()
                        self.process.join()
                # Do not read the queue after termination (tradingagents-web SPEC).
                self._release()
            if self.current["status"] in ACTIVE:
                self.current.update(status="stopped", downloads=False, rating=None)
                self.ended = time.monotonic()
            return self.snapshot()


def create_app(*, config=None, context=None):
    if config is None:
        from tradingagents.default_config import build_default_config

        config = build_default_config()
    manager = RunManager(config, context)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        async def collect():
            while True:
                manager.refresh()
                await asyncio.sleep(0.1)

        task = asyncio.create_task(collect())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            manager.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runs = manager

    @app.middleware("http")
    async def security(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid = (
                parsed.hostname in ("127.0.0.1", "localhost", "::1")
                and not parsed.username
                and not parsed.password
                and parsed.path == ""
                and not parsed.query
                and not parsed.fragment
            )
            port = parsed.port
            valid = valid and (port is None or 1 <= port <= 65535)
        except ValueError:
            valid = False
        if not valid:
            response = JSONResponse({"detail": "Loopback Host required."}, status_code=403)
        elif request.method not in ("GET", "HEAD", "OPTIONS") and (
            request.headers.get("origin") != f"{request.url.scheme}://{host}"
            or not secrets.compare_digest(
                request.headers.get("x-csrf-token", "").encode("utf-8"), token.encode("ascii")
            )
        ):
            response = JSONResponse(
                {"detail": "Same-origin request and CSRF token required."}, status_code=403
            )
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            }
        )
        return response

    @app.get("/api/config")
    def configuration():
        return public_config(config, token)

    @app.get("/api/run")
    def current_run():
        return manager.snapshot()

    @app.post("/api/run")
    async def start_run(request: Request):
        try:
            if len(await request.body()) > 16_384:
                raise ValueError("Run settings are too large.")
            selection = validate_run(await request.json())
        except MissingCredentials as exc:
            raise HTTPException(422, str(exc)) from None
        except (ValueError, TypeError):
            # Error disclosure policy: see tradingagents-web SPEC.
            raise HTTPException(
                422, "Invalid run settings. Check ticker, date, analysts, models and round counts."
            ) from None
        return manager.start(selection)

    @app.post("/api/run/stop")
    def stop_run():
        return manager.stop()

    @app.get("/api/reports/{format}")
    def download(format: str):
        with manager.lock:
            if format not in ("markdown", "html") or manager.snapshot()["status"] != "completed":
                raise HTTPException(404, "No completed current report.")
            suffix = "html" if format == "html" else "md"
            path = manager.report_dir / f"complete_report.{suffix}"
            if not path.is_file():
                raise HTTPException(404, "Report unavailable.")
            return FileResponse(
                path,
                media_type="text/html" if format == "html" else "text/markdown",
                filename=path.name,
            )

    static = Path(__file__).parent / "static"

    @app.get("/")
    def index():
        if not (static / "index.html").is_file():
            raise HTTPException(503, "Dashboard assets are not installed.")
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")
    return app
