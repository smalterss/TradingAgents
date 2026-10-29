"""Optional browser checks against real dashboard assets and intercepted test responses.

Run with Playwright and its Chromium binary installed. No server, API keys or
external service is used; every browser request is fulfilled inside the test.
"""

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ASSETS = Path(__file__).resolve().parents[1] / "tradingagents" / "web" / "static"
ORIGIN = "http://127.0.0.1:8000"
CONFIG = {
    "csrf_token": "test-only-token",
    "defaults": {
        "ticker": "", "trade_date": "2026-01-05",
        "analysts": ["market", "social", "news", "fundamentals"],
        "quick_provider": "ollama", "deep_provider": "ollama",
        "quick_model": "local-model", "deep_model": "local-model",
        "output_language": "English", "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    },
    "providers": [{"id": "ollama", "label": "Ollama", "configured": True,
                   "credential_hint": "Local runtime; no API key required.",
                   "models": [{"id": "local-model", "label": "Local model"}]}],
}
IDLE = {
    "id": None, "status": "idle", "ticker": "", "trade_date": "",
    "selected_analysts": [], "started_at": None, "elapsed_seconds": 0,
    "sections": [], "stage": "analysts", "analyst_status": {},
    "rating": None, "error": None, "memory_note": "", "downloads": False,
}


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as engine:
        try:
            instance = engine.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Chromium with python -m playwright install chromium")
            raise
        yield instance
        instance.close()


@pytest.fixture
def dashboard(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    state = {"run": deepcopy(IDLE), "posts": [], "error": None, "defer_poll": False, "pending_poll": None}
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def respond(route):
        req = route.request
        path = urlparse(req.url).path
        if path == "/api/config":
            route.fulfill(json=CONFIG)
        elif path == "/api/run" and req.method == "POST":
            state["posts"].append(req.post_data_json)
            assert req.headers["x-csrf-token"] == CONFIG["csrf_token"]
            if state["error"]:
                route.fulfill(status=400, json={"detail": state["error"]})
                return
            data = req.post_data_json
            state["run"] = {**deepcopy(IDLE), "id": "test-run", "status": "running",
                            "ticker": data["ticker"], "trade_date": data["trade_date"],
                            "selected_analysts": data["analysts"],
                            "analyst_status": dict.fromkeys(data["analysts"], "running")}
            route.fulfill(json=state["run"])
        elif path == "/api/run/stop":
            assert req.headers["x-csrf-token"] == CONFIG["csrf_token"]
            state["run"]["status"] = "stopped"
            route.fulfill(json=state["run"])
        elif path == "/api/run":
            if state["defer_poll"]:
                state["pending_poll"] = route
                state["defer_poll"] = False
            else:
                route.fulfill(json=state["run"])
        elif path in ("/", "/static/app.js", "/static/style.css"):
            name = "index.html" if path == "/" else path.rsplit("/", 1)[1]
            mime = {"index.html": "text/html", "app.js": "text/javascript",
                    "style.css": "text/css"}[name]
            route.fulfill(body=(ASSETS / name).read_bytes(), content_type=mime)
        else:
            route.abort()

    page.route("**/*", respond)
    page.goto(ORIGIN)
    playwright.expect(page.locator("#run-status")).to_have_text("READY")
    yield page, state
    assert errors == []
    page.close()


def start(page):
    page.get_by_label("Instrument", exact=False).fill("NVDA")
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#run-status")).to_have_text("RESEARCHING")


@pytest.mark.parametrize("width", [1440, 390])
def test_completed_manager_summary_and_next_run_reset(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    playwright.expect(page.locator("#manager-summary")).to_be_hidden()
    start(page)
    state["run"].update(status="completed", rating="Hold", manager_summary={
        "portfolio": "<p>Cash available: 5,000.00 USD</p><p>No current position in NVDA</p>",
        "recommendation": "<p><strong>Rating: Hold</strong></p><p>Wait for earnings before adding exposure.</p>",
    })
    playwright.expect(page.locator("#manager-summary")).to_be_visible()
    playwright.expect(page.locator("#manager-portfolio")).to_contain_text("5,000.00 USD")
    playwright.expect(page.locator("#manager-recommendation")).to_contain_text("Wait for earnings")
    page.reload()
    playwright.expect(page.locator("#manager-portfolio")).to_contain_text("5,000.00 USD")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    shots = ASSETS.parents[2] / ".thinkrail" / "context" / "qa"
    shots.mkdir(parents=True, exist_ok=True)
    page.locator("#manager-summary").screenshot(path=str(shots / f"manager-summary-{width}.png"))
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#run-status")).to_have_text("RESEARCHING")
    playwright.expect(page.locator("#manager-summary")).to_be_hidden()
    assert page.locator("#manager-portfolio").text_content() == ""
    state["run"].update(status="failed", manager_summary={"portfolio": "STALE", "recommendation": "Buy"})
    playwright.expect(page.locator("#run-status")).to_have_text("FAILED")
    playwright.expect(page.locator("#manager-summary")).to_be_hidden()


def test_dashboard_setup_start_stop_and_partial_reports(dashboard):
    page, state = dashboard
    playwright.expect(page.get_by_role("heading", name="Let the evidence lead the conversation.")).to_be_visible()
    start(page)
    assert state["posts"][0]["ticker"] == "NVDA"
    playwright.expect(page.locator("#ticker")).to_be_disabled()
    state["run"]["sections"] = [{"id": "market", "title": "Market", "html": "<h2>Technical evidence</h2><p>Partial report.</p>"}]
    playwright.expect(page.locator("#report-content")).to_contain_text("Technical evidence")
    page.get_by_role("button", name="Stop analysis").click()
    playwright.expect(page.locator("#run-status")).to_have_text("STOPPED")
    playwright.expect(page.locator("#run-notice")).to_contain_text("partial")
    playwright.expect(page.locator("#decision-card")).to_be_hidden()
    playwright.expect(page.locator("#downloads")).to_be_hidden()
    playwright.expect(page.locator("#report-content")).to_contain_text("Partial report.")
    playwright.expect(page.get_by_role("button", name="Run analysis")).to_be_enabled()


def test_dashboard_completion_tabs_reload_and_review(dashboard, tmp_path):
    page, state = dashboard
    start(page)
    state["run"].update(status="completed", rating="REVIEW", downloads=True,
                        sections=[{"id": "overview", "title": "Overview", "html": "<p>Needs review.</p>"},
                                  {"id": "news", "title": "News", "html": "<h2>News evidence</h2>"}])
    playwright.expect(page.locator("#rating")).to_have_text("Review required")
    playwright.expect(page.locator("#downloads")).to_be_visible()
    page.get_by_role("tab", name="Overview").focus()
    page.keyboard.press("ArrowRight")
    playwright.expect(page.get_by_role("tab", name="News")).to_have_attribute("aria-selected", "true")
    playwright.expect(page.locator("#report-content")).to_contain_text("News evidence")
    page.screenshot(path=str(tmp_path / "dashboard-completed.png"), full_page=True)
    page.reload()
    playwright.expect(page.locator("#run-status")).to_have_text("COMPLETED")
    playwright.expect(page.locator("#rating")).to_have_text("Review required")
    assert len(state["posts"]) == 1


def test_dashboard_validation_failure_and_mobile_layout(dashboard, tmp_path):
    page, state = dashboard
    for checkbox in page.locator('input[name="analyst"]').all():
        checkbox.uncheck()
    page.locator("#ticker").fill("AAPL")
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#form-error")).to_have_text("Select at least one analyst.")
    assert state["posts"] == []
    page.locator('input[value="market"]').check()
    state["error"] = "Set OPENAI_API_KEY locally before starting."
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#form-error")).to_contain_text("OPENAI_API_KEY")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(tmp_path / "dashboard-mobile.png"), full_page=True)


def test_dashboard_failed_run_and_safe_text(dashboard):
    page, state = dashboard
    start(page)
    state["run"].update(status="failed", error='<script>alert("unsafe")</script>',
                        sections=[{"id": "market", "title": "Market", "html": "<p>Available evidence.</p>"}])
    playwright.expect(page.locator("#run-status")).to_have_text("FAILED")
    playwright.expect(page.locator("#run-notice")).to_contain_text("<script>")
    assert page.locator("#run-notice script").count() == 0
    playwright.expect(page.locator("#decision-card")).to_be_hidden()
    playwright.expect(page.locator("#downloads")).to_be_hidden()
    playwright.expect(page.locator("#report-content")).to_contain_text("Available evidence.")


def test_dashboard_reveals_invalid_model_in_collapsed_settings(dashboard):
    page, state = dashboard
    page.locator("#ticker").fill("NVDA")
    page.locator(".model-details summary").click()
    page.locator("#quick-model").fill("")
    page.locator(".model-details summary").click()
    page.locator("#run-button").click()
    playwright.expect(page.locator("#quick-model")).to_be_visible()
    assert state["posts"] == []


def test_dashboard_ignores_old_poll_after_new_run(dashboard):
    page, state = dashboard
    state["defer_poll"] = True
    page.wait_for_timeout(1200)
    assert state["pending_poll"] is not None
    start(page)
    state["pending_poll"].fulfill(json=deepcopy(IDLE))
    page.wait_for_timeout(100)
    playwright.expect(page.locator("#run-status")).to_have_text("RESEARCHING")
    playwright.expect(page.locator("#ticker")).to_be_disabled()


def test_dashboard_desktop_screenshot(dashboard, tmp_path):
    page, _state = dashboard
    page.screenshot(path=str(tmp_path / "dashboard-desktop.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    playwright.expect(page.locator("#run-button")).to_be_enabled()
