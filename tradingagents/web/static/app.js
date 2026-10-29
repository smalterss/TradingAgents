"use strict";

const $ = (id) => document.getElementById(id);
const form = $("analysis-form");
const runningStates = new Set(["starting", "running"]);
const stages = ["analysts", "research", "trader", "risk", "decision"];
const analystNames = {
  market: "Market",
  social: "Sentiment",
  news: "News",
  fundamentals: "Fundamentals",
};
let config = null;
let snapshot = null;
let selectedSection = null;
let currentRunId = null;
let busy = false;
let polling = false;
let lastRender = "";
let revision = 0;

function message(id, text) {
  const element = $(id);
  element.textContent = text || "";
  element.hidden = !text;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : "Please check the form and try again.";
    throw new Error(detail);
  }
  return body;
}

function modelSummary() {
  const quick = $("quick-model").value;
  const deep = $("deep-model").value;
  $("model-summary").textContent =
    quick === deep ? quick : `${quick} / ${deep}`;
}

function credentials(tier) {
  const provider = config.providers.find(
    (item) => item.id === $(`${tier}-provider`).value,
  );
  const hint = $(`${tier}-hint`);
  hint.textContent =
    provider?.credential_hint || "Uses local environment configuration.";
  hint.classList.toggle("missing", provider?.configured === false);
}

function updateModels(tier, keepModel = false) {
  const provider = config.providers.find(
    (item) => item.id === $(`${tier}-provider`).value,
  );
  const models = provider?.models || [];
  const list = $(`${tier}-models`);
  list.replaceChildren(
    ...models.map((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.label = model.label || model.id;
      return option;
    }),
  );
  if (!keepModel) $(`${tier}-model`).value = models[0]?.id || "";
  credentials(tier);
  modelSummary();
}

function countAnalysts() {
  const count = form.querySelectorAll('input[name="analyst"]:checked').length;
  $("analyst-count").textContent = `${count} SELECTED`;
}

function configure(data) {
  config = data;
  const defaults = data.defaults;
  $("ticker").value = defaults.ticker || "";
  $("trade-date").value = defaults.trade_date;
  $("trade-date").max = defaults.trade_date;
  $("language").value = defaults.output_language || "English";
  $("debate-rounds").value = defaults.max_debate_rounds;
  $("risk-rounds").value = defaults.max_risk_discuss_rounds;
  for (const checkbox of form.querySelectorAll('input[name="analyst"]'))
    checkbox.checked = defaults.analysts.includes(checkbox.value);
  for (const tier of ["quick", "deep"]) {
    const select = $(`${tier}-provider`);
    select.replaceChildren(
      ...data.providers.map((provider) => {
        const option = document.createElement("option");
        option.value = provider.id;
        option.textContent = provider.label || provider.id;
        return option;
      }),
    );
    select.value = defaults[`${tier}_provider`];
    $(`${tier}-model`).value = defaults[`${tier}_model`];
    updateModels(tier, true);
    select.addEventListener("change", () => updateModels(tier));
    $(`${tier}-model`).addEventListener("input", modelSummary);
  }
  countAnalysts();
}

function formData() {
  return {
    ticker: $("ticker").value.trim(),
    trade_date: $("trade-date").value,
    analysts: Array.from(
      form.querySelectorAll('input[name="analyst"]:checked'),
      (item) => item.value,
    ),
    quick_provider: $("quick-provider").value,
    quick_model: $("quick-model").value.trim(),
    deep_provider: $("deep-provider").value,
    deep_model: $("deep-model").value.trim(),
    output_language: $("language").value.trim(),
    max_debate_rounds: Number($("debate-rounds").value),
    max_risk_discuss_rounds: Number($("risk-rounds").value),
  };
}

function controls() {
  const active = runningStates.has(snapshot?.status);
  $("setup-fields").disabled = !config || active || busy;
  $("run-button").disabled = !config || active || busy;
  $("run-button").querySelector("span").textContent = busy
    ? "Working…"
    : active
      ? "Analysis in progress"
      : "Run analysis";
  $("stop-button").hidden = !active;
  $("stop-button").disabled = busy;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")} elapsed`;
}

function renderSection() {
  const section = (snapshot?.sections || []).find(
    (item) => item.id === selectedSection,
  );
  for (const tab of $("report-tabs").children) {
    const active = tab.dataset.section === selectedSection;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
  if (section) {
    const next = `${section.id}\n${section.html}`;
    if (next !== lastRender) {
      // HTML comes only from the local server's HTML-disabled Markdown renderer.
      $("report-content").innerHTML = section.html;
      lastRender = next;
    }
    $("report-content").setAttribute("aria-labelledby", `tab-${section.id}`);
  }
}

function reports() {
  const sections = snapshot.sections || [];
  $("reports-card").hidden = sections.length === 0;
  $("downloads").hidden = !(
    snapshot.status === "completed" && snapshot.downloads
  );
  if (!sections.length) {
    $("report-tabs").replaceChildren();
    $("report-content").replaceChildren();
    lastRender = "";
    return;
  }
  if (!sections.some((section) => section.id === selectedSection))
    selectedSection = sections[0].id;
  const oldIds = Array.from(
    $("report-tabs").children,
    (tab) => tab.dataset.section,
  ).join("|");
  if (oldIds !== sections.map((section) => section.id).join("|")) {
    $("report-tabs").replaceChildren(
      ...sections.map((section) => {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", "report-content");
        tab.id = `tab-${section.id}`;
        tab.dataset.section = section.id;
        tab.textContent = section.title;
        tab.addEventListener("click", () => {
          selectedSection = section.id;
          renderSection();
        });
        return tab;
      }),
    );
  }
  renderSection();
}

function render(next) {
  snapshot = next;
  const active = runningStates.has(next.status);
  const isIdle = next.status === "idle";
  if (next.id !== currentRunId) {
    currentRunId = next.id;
    selectedSection = null;
    lastRender = "";
    if (next.ticker) $("ticker").value = next.ticker;
    if (next.trade_date) $("trade-date").value = next.trade_date;
  }
  const statusLabel = {
    idle: "READY",
    starting: "STARTING",
    running: "RESEARCHING",
    completed: "COMPLETED",
    stopped: "STOPPED",
    failed: "FAILED",
  };
  $("run-status").textContent = statusLabel[next.status] || "UNKNOWN";
  $("run-status").className = `status-pill ${next.status}`;
  $("elapsed").textContent = isIdle ? "—" : duration(next.elapsed_seconds);
  $("workspace-title").textContent = isIdle
    ? "The research desk"
    : `${next.ticker} / Research`;
  $("workspace-subtitle").textContent = isIdle
    ? "Your next perspective starts here."
    : `Analysis as of ${next.trade_date} · ${next.selected_analysts?.length || 0} analysts selected`;
  $("empty-state").hidden = !isIdle;
  const stageIndex = stages.indexOf(next.stage);
  for (const [index, stage] of Array.from(
    document.querySelectorAll("[data-stage]"),
  ).entries()) {
    stage.classList.toggle("active", active && index === stageIndex);
    stage.classList.toggle(
      "done",
      !isIdle && (next.status === "completed" || index < stageIndex),
    );
  }
  $("pipeline-caption").textContent = active
    ? "Live updates from the research engine"
    : "Evidence first. Conviction second.";
  $("analyst-progress").replaceChildren(
    ...(next.selected_analysts || []).map((key) => {
      const item = document.createElement("span");
      const state = next.analyst_status?.[key] || "pending";
      item.className = state;
      const dot = document.createElement("i");
      dot.setAttribute("aria-hidden", "true");
      item.append(dot, `${analystNames[key] || key}: ${state}`);
      return item;
    }),
  );
  let notice = "";
  if (active)
    notice =
      next.status === "starting"
        ? "Preparing the research engine and resolving the instrument. This can take a moment."
        : "Analysis is running. Reports appear as agents complete their work. You can keep reading while the team works.";
  if (next.status === "failed")
    notice =
      next.error ||
      "Analysis failed. Check your local provider configuration and try again. Any available reports below are incomplete.";
  if (next.status === "stopped")
    notice =
      "Analysis stopped. Available sections below are partial—not a final decision. Requests already accepted by a provider may still incur charges.";
  message("run-notice", notice);
  $("run-notice").classList.toggle("error-notice", next.status === "failed");
  const completed = next.status === "completed";
  $("decision-card").hidden = !completed;
  if (completed) {
    $("rating").textContent =
      next.rating === "REVIEW" || !next.rating
        ? "Review required"
        : next.rating;
    $("decision-card").dataset.rating = next.rating || "REVIEW";
  }
  message("memory-note", next.memory_note);
  reports();
  controls();
}

async function refresh() {
  if (polling || busy) return;
  polling = true;
  const requestedRevision = revision;
  try {
    const next = await request("/api/run");
    if (requestedRevision === revision && !busy) render(next);
    message("connection-error", "");
  } catch (_) {
    message(
      "connection-error",
      "Cannot reach the local server. Check that tradingagents-web is still running. This page will reconnect automatically.",
    );
  } finally {
    polling = false;
  }
}

form.addEventListener(
  "invalid",
  (event) => {
    const details = event.target.closest("details");
    if (details) details.open = true;
  },
  true,
);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || !config || runningStates.has(snapshot?.status)) return;
  message("form-error", "");
  const data = formData();
  if (!data.analysts.length) {
    message("form-error", "Select at least one analyst.");
    return;
  }
  busy = true;
  revision += 1;
  controls();
  try {
    render(
      await request("/api/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": config.csrf_token,
        },
        body: JSON.stringify(data),
      }),
    );
    $("workspace").focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 760px)").matches)
      $("workspace").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    message("form-error", error.message);
  } finally {
    busy = false;
    controls();
  }
});

$("stop-button").addEventListener("click", async () => {
  if (busy || !config) return;
  busy = true;
  revision += 1;
  controls();
  try {
    render(
      await request("/api/run/stop", {
        method: "POST",
        headers: { "X-CSRF-Token": config.csrf_token },
      }),
    );
  } catch (error) {
    message("form-error", error.message);
  } finally {
    busy = false;
    controls();
  }
});

form
  .querySelectorAll('input[name="analyst"]')
  .forEach((item) => item.addEventListener("change", countAnalysts));
$("report-tabs").addEventListener("keydown", (event) => {
  const tabs = Array.from($("report-tabs").children);
  const index = tabs.indexOf(document.activeElement);
  if (
    index < 0 ||
    !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
  )
    return;
  event.preventDefault();
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  selectedSection = tabs[next].dataset.section;
  renderSection();
  tabs[next].focus();
});

async function initialize() {
  try {
    configure(await request("/api/config"));
    await refresh();
    controls();
    setInterval(refresh, 1000);
  } catch (_) {
    $("run-status").textContent = "OFFLINE";
    message(
      "connection-error",
      "Dashboard setup could not load. Check the local server, then reload this page.",
    );
  }
}
initialize();
