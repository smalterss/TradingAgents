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
    state = {"run": deepcopy(IDLE), "config": deepcopy(CONFIG), "posts": [], "error": None, "defer_poll": False, "pending_poll": None}
    errors = []
    external_requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def respond(route):
        req = route.request
        parsed = urlparse(req.url)
        path = parsed.path
        if parsed.netloc != urlparse(ORIGIN).netloc:
            external_requests.append(req.url)
            route.abort()
            return
        if path == "/api/config":
            route.fulfill(json=state["config"])
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
        elif path in ("/", "/static/app.js", "/static/style.css", "/static/workspace.css",
                      "/static/motion.js", "/static/anime.min.js", "/static/github-markdown.css"):
            name = "index.html" if path == "/" else path.removeprefix("/static/")
            mime = "text/html" if name == "index.html" else (
                "text/javascript" if name.endswith(".js") else "text/css")
            route.fulfill(body=(ASSETS / name).read_bytes(), content_type=mime)
        else:
            route.abort()

    page.route("**/*", respond)
    page.goto(ORIGIN)
    playwright.expect(page.locator("#run-status")).to_have_text("READY")
    yield page, state
    assert errors == []
    assert external_requests == []
    page.close()


def start(page):
    page.get_by_label("Instrument", exact=False).fill("NVDA")
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#run-status")).to_have_text("RESEARCHING")


@pytest.mark.parametrize("width", [1440, 390])
def test_workspace_without_pipeline_preserves_agent_activity(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    for status in ("idle", "running", "completed", "stopped", "failed"):
        state["run"] = {**deepcopy(IDLE), "status": status,
                        "id": None if status == "idle" else "test-run",
                        "ticker": "NVDA", "trade_date": "2026-01-05"}
        page.reload()
        expected_status = {"idle": "READY", "running": "RESEARCHING"}.get(status, status.upper())
        playwright.expect(page.locator("#run-status")).to_have_text(expected_status)
        playwright.expect(page.locator(".pipeline-card, [data-stage], #analyst-progress")).to_have_count(0)
        playwright.expect(page.get_by_role("region", name="Agent teams", exact=True)).to_be_visible()
        playwright.expect(page.locator("#agents-heading, #activity-retention, .agent-roster > .eyebrow")).to_have_count(0)
        playwright.expect(page.get_by_text("Research crew", exact=True)).to_have_count(0)
        playwright.expect(page.locator(".agent-team")).to_have_count(5)
        playwright.expect(page.locator(".activity-stream")).to_have_count(12)
        assert page.locator(".agent-roster").evaluate("""node =>
            [...node.querySelectorAll('[aria-labelledby], [aria-describedby]')].every(element =>
                ['aria-labelledby', 'aria-describedby'].every(attribute =>
                    (element.getAttribute(attribute) || '').split(/\\s+/).filter(Boolean)
                        .every(id => document.getElementById(id))))""")
        playwright.expect(page.locator("#all-agents, #activity-stream, .activity-panel")).to_have_count(0)
        playwright.expect(page.locator(".agent-card")).to_have_count(12)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", [1440, 390])
def test_paper_automation_indicator_and_actual_outcome(dashboard, width):
    page, state = dashboard
    state["config"]["paper_execution_enabled"] = True
    page.set_viewport_size({"width": width, "height": 1100})
    page.reload()
    playwright.expect(page.locator("#execution-mode")).to_have_text("PAPER AUTO ON")
    playwright.expect(page.locator("#paper-automation-notice")).to_contain_text("No live trades")
    start(page)
    playwright.expect(page.locator("#paper-execution")).to_be_hidden()
    state["run"].update(status="completed", rating="Buy", paper_execution=
        "<p>Status: <strong>submitted</strong>. Submission is not a fill.</p>"
        "<p>Buy AAPL · Notional: 25.00 · Broker status: accepted</p>")
    playwright.expect(page.locator("#paper-execution")).to_be_visible()
    playwright.expect(page.locator("#paper-execution-content")).to_contain_text("submitted")
    playwright.expect(page.locator("#paper-execution")).to_contain_text("Submitted does not mean filled")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    shots = ASSETS.parents[2] / ".thinkrail" / "context" / "qa"
    shots.mkdir(parents=True, exist_ok=True)
    page.locator("#paper-execution").screenshot(path=str(shots / f"paper-outcome-{width}.png"))
    page.reload()
    playwright.expect(page.locator("#paper-execution-content")).to_contain_text("submitted")
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(page.locator("#paper-execution")).to_be_hidden()
    assert page.locator("#paper-execution-content").text_content() == ""
    state["run"].update(status="stopped", paper_execution="STALE")
    playwright.expect(page.locator("#run-status")).to_have_text("STOPPED")
    playwright.expect(page.locator("#run-notice")).to_contain_text("check Alpaca")
    playwright.expect(page.locator("#paper-execution")).to_be_hidden()


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


@pytest.mark.parametrize("width", [1440, 390])
def test_compact_research_header_preserves_context(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    start(page)
    playwright.expect(page.locator("#workspace-title")).to_have_text("NVDA / Research")
    playwright.expect(page.locator("#workspace-subtitle")).to_contain_text("2026-01-05")
    playwright.expect(page.locator("#workspace-subtitle")).to_contain_text("4 analysts selected")
    playwright.expect(page.locator("#elapsed")).to_be_visible()
    header = page.locator(".workspace-heading")
    assert header.bounding_box()["height"] <= (72 if width == 1440 else 100)
    assert page.locator("#workspace-title").evaluate("node => parseFloat(getComputedStyle(node).fontSize)") == 18
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    state["run"]["ticker"] = "LONG-TICKER-SYMBOL"
    page.reload()
    playwright.expect(page.locator("#workspace-title")).to_have_text("LONG-TICKER-SYMBOL / Research")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width,columns", [(1440, 3), (1000, 2), (390, 1)])
def test_compact_agent_cards_preserve_streams(dashboard, width, columns):
    page, _state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    playwright.expect(page.locator(".agent-card")).to_have_count(12)
    grid = page.locator(".agent-cards").first
    assert grid.evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length") == columns
    card = page.locator('[data-agent="market"]')
    assert card.bounding_box()["height"] < 260
    stream = card.locator(".activity-stream")
    assert stream.evaluate("node => parseFloat(getComputedStyle(node).height)") == 160
    playwright.expect(stream).to_be_visible()
    playwright.expect(card.get_by_role("button", name="Follow latest for Market Analyst")).to_be_visible()
    assert card.evaluate("node => node.scrollWidth <= node.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_running_agent_animation_tracks_observed_state_and_motion_preference(dashboard):
    page, state = dashboard
    page.emulate_media(reduced_motion="no-preference")
    start(page)
    indicator = page.locator('[data-agent="market"] .agent-state')
    animation = "node => getComputedStyle(node, '::before').animationName"
    assert indicator.evaluate(animation) == "none"
    state["run"]["agent_status"] = {"market": "running", "news": "queued"}
    page.reload()
    playwright.expect(indicator).to_have_text("Running")
    assert indicator.evaluate(animation) == "agent-working"
    assert page.locator('[data-agent="news"] .agent-state').evaluate(animation) == "none"
    page.emulate_media(reduced_motion="reduce")
    assert indicator.evaluate(animation) == "none"
    playwright.expect(indicator).to_have_text("Running")
    page.emulate_media(reduced_motion="no-preference")
    assert indicator.evaluate(animation) == "agent-working"
    for status in ("completed", "failed", "stopped", "output_available"):
        state["run"]["agent_status"]["market"] = status
        page.reload()
        playwright.expect(page.locator('[data-agent="market"]')).to_have_attribute("data-status", status)
        assert indicator.evaluate(animation) == "none"


@pytest.mark.parametrize("width", [1440, 390])
def test_agent_teams_have_separate_boxes(dashboard, width):
    page, _state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    expected = [("Analysts", 4), ("Research Debate", 3), ("Trading", 1),
                ("Risk Review", 3), ("Portfolio Decision", 1)]
    for index, (name, count) in enumerate(expected):
        team = page.get_by_role("region", name=name, exact=True)
        playwright.expect(team.locator(".agent-card")).to_have_count(count)
        assert team.evaluate("node => parseFloat(getComputedStyle(node).borderTopWidth)") == 1
        assert team.evaluate("node => parseFloat(getComputedStyle(node).borderRadius)") == 10
        assert team.evaluate("node => node.scrollWidth <= node.clientWidth")
        if index:
            previous = page.locator(".agent-team").nth(index - 1).bounding_box()
            assert team.bounding_box()["y"] >= previous["y"] + previous["height"] + 13
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_dashboard_desktop_screenshot(dashboard, tmp_path):
    page, _state = dashboard
    page.screenshot(path=str(tmp_path / "dashboard-desktop.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    playwright.expect(page.locator("#run-button")).to_be_enabled()


def activity(seq, agent="market", kind="started", **extra):
    return {"seq": seq, "agent": agent, "kind": kind,
            "summary": f"Observed event {seq}", "timestamp": "2026-01-05T12:00:00Z", **extra}


@pytest.mark.parametrize("width", [1440, 390])
def test_agent_workbench_always_visible_individual_activity(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    playwright.expect(page.locator(".agent-team")).to_have_count(5)
    playwright.expect(page.locator(".agent-card")).to_have_count(12)
    playwright.expect(page.locator(".agent-roster")).to_be_visible()
    page.locator('input[value="social"]').uncheck()
    playwright.expect(page.locator('[data-agent="social"] .agent-state')).to_have_text("Not selected")
    start(page)
    # Legacy analyst_status must never manufacture a working card.
    playwright.expect(page.locator('[data-agent="market"] .agent-state')).to_have_text("Activity unavailable")
    state["run"].update(agent_status={"market": "running", "bull": "completed", "trader": "queued",
                                      "aggressive": "failed", "portfolio_manager": "stopped", "research_manager": "output_available"},
                        activity=[activity(1), activity(2, "bull", "completed", output_html="<h2>Published contribution</h2>"),
                                  activity(3, summary='<img src=x onerror="alert(1)">'),
                                  activity(4, "unknown"), activity(5, kind="private_reasoning"), activity(1)])
    playwright.expect(page.locator(".activity-event")).to_have_count(3)
    playwright.expect(page.locator('[data-agent="market"] .agent-state')).to_have_text("Running")
    playwright.expect(page.locator('[data-agent="bull"] .agent-state')).to_have_text("Completed")
    playwright.expect(page.locator('[data-agent="trader"] .agent-state')).to_have_text("Queued")
    playwright.expect(page.locator('[data-agent="research_manager"] .agent-state')).to_have_text("Output available · activity not recorded")
    playwright.expect(page.locator('[data-agent="aggressive"] .agent-state')).to_have_text("Failed")
    playwright.expect(page.locator('[data-agent="portfolio_manager"] .agent-state')).to_have_text("Stopped")
    assert page.locator(".activity-summary img").count() == 0
    playwright.expect(page.locator(".activity-output h2")).to_have_text("Published contribution")
    market = page.locator('[data-agent="market"]')
    bull = page.locator('[data-agent="bull"]')
    playwright.expect(market.locator(".activity-event")).to_have_count(2)
    playwright.expect(bull.locator(".activity-event")).to_have_count(1)
    playwright.expect(market.locator(".activity-stream")).to_be_visible()
    playwright.expect(bull.locator(".activity-stream")).to_be_visible()
    assert market.evaluate("node => node.tagName") == "SECTION"
    follow = market.get_by_role("button", name="Follow latest for Market Analyst")
    follow.focus()
    page.keyboard.press("Enter")
    playwright.expect(follow).to_have_attribute("aria-pressed", "false")
    page.locator('.activity-event[data-seq="1"]').evaluate("node => window.originalEvent = node")
    state["run"]["activity"].append(activity(6, kind="tool_started"))
    playwright.expect(market.locator(".activity-event")).to_have_count(3)
    playwright.expect(bull.locator(".activity-event")).to_have_count(1)
    playwright.expect(follow).to_be_focused()
    assert page.locator('.activity-event[data-seq="1"]').evaluate("node => node === window.originalEvent")
    playwright.expect(bull.locator(".follow-latest")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Stop analysis").click()
    playwright.expect(page.locator("#run-notice")).to_contain_text("partial")
    playwright.expect(page.locator(".activity-event")).to_have_count(4)
    page.get_by_role("button", name="Run analysis").click()
    playwright.expect(follow).to_have_attribute("aria-pressed", "true")
    playwright.expect(page.locator(".activity-event")).to_have_count(0)
    assert page.locator(".activity-latest").all_text_contents() == [""] * 12
    state["run"].update(status="failed", activity=[], error="Provider unavailable; partial evidence only.")
    playwright.expect(page.locator("#run-status")).to_have_text("FAILED")
    playwright.expect(page.locator('[data-agent="market"] .activity-empty')).to_contain_text("No activity recorded")
    playwright.expect(page.locator("#run-notice")).to_contain_text("partial")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_agent_feed_reading_position_and_retention(dashboard):
    page, state = dashboard
    start(page)
    # Constrain the reader to exercise overflow and retained-record anchoring.
    page.locator("#agent-stream-market").evaluate("node => {node.style.height = '180px'; node.style.overflow = 'auto';}")
    state["run"].update(activity=[activity(seq) for seq in range(1, 202)])
    playwright.expect(page.locator(".activity-event")).to_have_count(200)
    playwright.expect(page.locator(".activity-event").first).to_have_attribute("data-seq", "2")
    stream = page.locator("#agent-stream-market")
    stream.evaluate("node => node.scrollTop = 500")
    anchor = stream.locator('.activity-event[data-seq="10"]')
    before = anchor.evaluate("node => node.getBoundingClientRect().top")
    state["run"]["activity"].append(activity(202, kind="tool_completed"))
    playwright.expect(page.locator(".activity-event").last).to_have_attribute("data-seq", "202")
    assert abs(anchor.evaluate("node => node.getBoundingClientRect().top") - before) < 2
    stream.evaluate("node => node.scrollTop = node.scrollHeight")
    state["run"]["activity"].append(activity(203, kind="tool_failed"))
    playwright.expect(page.locator(".activity-event").last).to_have_attribute("data-seq", "203")
    assert stream.evaluate("node => node.scrollHeight - node.scrollTop - node.clientHeight < 2")
    page.locator('[data-agent="market"] .follow-latest').click()
    stream.evaluate("node => node.scrollTop = 0")
    state["run"]["activity"].append(activity(204, kind="failed"))
    playwright.expect(page.locator(".activity-event").last).to_have_attribute("data-seq", "204")
    assert stream.evaluate("node => node.scrollTop") == 0
    # Switching to a different run clears old events even if it has no activity field.
    state["run"] = {**deepcopy(IDLE), "id": "different-run", "status": "running",
                     "selected_analysts": ["market"]}
    playwright.expect(page.locator(".activity-event")).to_have_count(0)
    playwright.expect(page.locator('[data-agent="market"] .activity-empty')).to_contain_text("Activity unavailable")


@pytest.mark.parametrize("width", [1440, 390])
def test_all_agent_streams_route_and_follow_independently(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    start(page)
    agents = page.locator(".agent-card").evaluate_all("nodes => nodes.map(node => node.dataset.agent)")
    state["run"]["activity"] = [activity(seq, agent) for seq, agent in enumerate(agents, 1)]
    playwright.expect(page.locator(".activity-event")).to_have_count(12)
    for seq, agent in enumerate(agents, 1):
        card = page.locator(f'[data-agent="{agent}"]')
        playwright.expect(card.locator(".activity-stream")).to_be_visible()
        playwright.expect(card.locator(".activity-event")).to_have_count(1)
        playwright.expect(card.locator(".activity-event")).to_have_attribute("data-seq", str(seq))
        playwright.expect(card.locator(".activity-stream")).to_have_attribute("tabindex", "0")
    market = page.locator("#agent-stream-market")
    bull = page.locator("#agent-stream-bull")
    state["run"]["activity"] = [activity(seq, "market" if seq % 2 else "bull") for seq in range(20, 60)]
    playwright.expect(page.locator(".activity-event")).to_have_count(40)
    page.locator('[data-agent="market"] .follow-latest').click()
    market.evaluate("node => node.scrollTop = node.scrollHeight")
    bull.evaluate("node => node.scrollTop = node.scrollHeight")
    previous_top = market.evaluate("node => node.scrollTop")
    market.evaluate("node => {window.originalStream = node; node.focus();}")
    state["run"]["activity"].extend([activity(60, "bull"), activity(61, "market")])
    playwright.expect(page.locator(".activity-event")).to_have_count(42)
    assert market.evaluate("node => node.scrollTop") == previous_top
    assert bull.evaluate("node => node.scrollHeight - node.scrollTop - node.clientHeight < 2")
    assert market.evaluate("node => node === window.originalStream")
    playwright.expect(market).to_be_focused()
    page.locator('[data-agent="market"] .follow-latest').click()
    assert market.evaluate("node => node.scrollHeight - node.scrollTop - node.clientHeight < 2")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", [1440, 390])
def test_local_libraries_motion_and_report_formatting(dashboard, width):
    page, state = dashboard
    page.set_viewport_size({"width": width, "height": 1100})
    font_size = "node => parseFloat(getComputedStyle(node).fontSize)"
    assert page.locator('[data-agent="market"] .activity-empty').evaluate(font_size) == 12
    # Upstream npm 3.2.2 retains the runtime version string from 3.2.1.
    assert page.evaluate("window.anime.version") == "3.2.1"
    assert page.locator('link[href="/static/github-markdown.css"]').count() == 1
    page.emulate_media(reduced_motion="reduce")
    page.evaluate("dashboardMotion.enter(document.querySelector('.agent-roster'))")
    page.wait_for_function("() => { const node = document.querySelector('.agent-roster'); return !node.style.opacity && !node.style.transform; }")
    start(page)
    output = "<h2>Market evidence</h2><p>Published analysis from this agent.</p><blockquote><p>Evidence, not a guarantee.</p></blockquote><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody><tr><td>Sample index</td><td>100.00</td></tr></tbody></table>"
    state["run"].update(agent_status={"market": "completed", "social": "running", "bull": "queued"},
                        activity=[activity(1), activity(2, kind="tool_started"),
                                  activity(3, kind="completed", output_html=output)],
                        sections=[{"id": "market", "title": "Market", "html": output}])
    playwright.expect(page.locator(".activity-output h2")).to_have_text("Market evidence")
    playwright.expect(page.get_by_role("region", name="Market Analyst stream", exact=True)).to_be_visible()
    playwright.expect(page.locator("#report-content table")).to_be_visible()
    assert page.locator(".activity-summary").first.evaluate(font_size) == 12
    assert page.locator(".activity-output").evaluate(font_size) == 12
    assert page.locator(".activity-output p").first.evaluate(font_size) == 12
    assert page.locator(".activity-output table").evaluate(font_size) == 11
    assert page.locator("#report-content").evaluate(font_size) == 14
    assert page.locator("#report-content table").evaluate(font_size) == 12
    assert page.locator("#report-content").evaluate("node => parseFloat(getComputedStyle(node).lineHeight) >= 24")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    shots = ASSETS.parents[2] / ".thinkrail" / "context" / "qa"
    shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shots / f"agent-workspace-{width}.png"), full_page=True)
    page.emulate_media(reduced_motion="no-preference")
    assert page.evaluate("""() => {
        const node = document.querySelector('.agent-card');
        dashboardMotion.enter(node);
        return anime.running.some(animation => animation.animatables.some(item => item.target === node));
    }""")
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("() => { const node = document.querySelector('.agent-card'); return !node.style.opacity && !node.style.transform; }")


def test_dashboard_remains_usable_without_animation_library(dashboard):
    page, state = dashboard
    page.route("**/static/anime.min.js", lambda route: route.abort())
    page.reload()
    playwright.expect(page.locator("#run-status")).to_have_text("READY")
    assert page.evaluate("typeof window.anime") == "undefined"
    start(page)
    state["run"].update(agent_status={"market": "running"}, activity=[activity(1)])
    playwright.expect(page.locator(".activity-event")).to_have_count(1)
    playwright.expect(page.locator('[data-agent="market"] .agent-state')).to_have_text("Running")
