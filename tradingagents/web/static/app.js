"use strict";

const $ = (id) => document.getElementById(id);
const form = $("analysis-form");
const runningStates = new Set(["starting", "running"]);
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

const agentTeams = [
  ["Analysts", [["market", "Market Analyst"], ["social", "Sentiment Analyst"], ["news", "News Analyst"], ["fundamentals", "Fundamentals Analyst"]]],
  ["Research Debate", [["bull", "Bull Researcher"], ["bear", "Bear Researcher"], ["research_manager", "Research Manager"]]],
  ["Trading", [["trader", "Trader"]]],
  ["Risk Review", [["aggressive", "Aggressive Analyst"], ["conservative", "Conservative Analyst"], ["neutral", "Neutral Analyst"]]],
  ["Portfolio Decision", [["portfolio_manager", "Portfolio Manager"]]],
];
const agentNames = Object.fromEntries(agentTeams.flatMap(([, agents]) => agents));
const activityKinds = new Set(["started", "completed", "failed", "tool_started", "tool_completed", "tool_failed"]);
const agentStates = new Set(["queued", "running", "completed", "failed", "stopped", "output_available"]);
const agentStreams = new Map();

function resetActivity() {
  for (const reader of agentStreams.values()) {
    reader.nodes.clear();
    reader.stream.replaceChildren(reader.empty);
    reader.stream.scrollTop = 0;
    reader.follow = true;
    reader.button.setAttribute("aria-pressed", "true");
    reader.latest.textContent = "";
    reader.latestSequence = -1;
  }
}

function initializeAgents() {
  for (const [index, [team, agents]] of agentTeams.entries()) {
    const group = document.createElement("section");
    group.className = "agent-team";
    const heading = document.createElement("h4");
    heading.id = `agent-team-${index}`;
    heading.textContent = team;
    group.setAttribute("aria-labelledby", heading.id);
    const cards = document.createElement("div");
    cards.className = "agent-cards";
    for (const [id, name] of agents) {
      const card = document.createElement("section");
      card.className = "agent-card";
      card.dataset.agent = id;
      card.setAttribute("aria-labelledby", `agent-name-${id}`);
      const label = document.createElement("h5");
      label.id = `agent-name-${id}`;
      label.className = "agent-name";
      label.textContent = name;
      const state = document.createElement("span");
      state.className = "agent-state";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "follow-latest";
      button.textContent = "Follow latest";
      button.setAttribute("aria-label", `Follow latest for ${name}`);
      button.setAttribute("aria-pressed", "true");
      button.setAttribute("aria-controls", `agent-stream-${id}`);
      const stream = document.createElement("div");
      stream.id = `agent-stream-${id}`;
      stream.className = "activity-stream";
      stream.tabIndex = 0;
      stream.setAttribute("role", "region");
      stream.setAttribute("aria-label", `${name} stream`);
      const empty = document.createElement("p");
      empty.className = "activity-empty";
      stream.append(empty);
      const latest = document.createElement("p");
      latest.className = "activity-latest";
      latest.setAttribute("role", "status");
      latest.setAttribute("aria-live", "polite");
      latest.setAttribute("aria-atomic", "true");
      const reader = { card, state, button, stream, empty, latest, nodes: new Map(), follow: true, latestSequence: -1 };
      agentStreams.set(id, reader);
      button.addEventListener("click", () => {
        reader.follow = !reader.follow;
        button.setAttribute("aria-pressed", String(reader.follow));
        if (reader.follow) stream.scrollTop = stream.scrollHeight;
      });
      card.append(label, state, button, stream, latest);
      cards.append(card);
    }
    group.append(heading, cards);
    $("agent-groups").append(group);
  }
}

function renderActivity() {
  const next = snapshot || {};
  const analysts = next.status === "idle" || !snapshot
    ? Array.from(form.querySelectorAll('input[name="analyst"]:checked'), (item) => item.value)
    : next.selected_analysts || [];
  const seen = new Set();
  const events = (Array.isArray(next.activity) ? next.activity : []).filter((event) => {
    if (!event || !Number.isInteger(event.seq) || seen.has(event.seq) ||
        !Object.hasOwn(agentNames, event.agent) || !activityKinds.has(event.kind)) return false;
    seen.add(event.seq);
    return true;
  }).sort((a, b) => a.seq - b.seq).slice(-200);
  for (const [id, reader] of agentStreams) {
    const raw = next.agent_status?.[id];
    const state = id in analystNames && !analysts.includes(id) ? "not-selected"
      : agentStates.has(raw) ? raw : "unavailable";
    reader.card.dataset.status = state;
    reader.state.textContent = state === "not-selected" ? "Not selected"
      : state === "output_available" ? "Output available · activity not recorded"
      : state === "unavailable" ? (next.status === "idle" ? "Ready" : "Activity unavailable")
      : state.charAt(0).toUpperCase() + state.slice(1);
    const visible = events.filter((event) => event.agent === id);
    const { stream, nodes } = reader;
    const nearBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 48;
    const top = stream.scrollTop;
    const keys = new Set(visible.map((event) => event.seq));
    // Anchor a retained visible record before removing evicted records above it.
    const anchor = Array.from(stream.children).find((node) =>
      keys.has(Number(node.dataset.seq)) && node.getBoundingClientRect().bottom > stream.getBoundingClientRect().top);
    const anchorOffset = anchor?.getBoundingClientRect().top;
    let changed = false;
    for (const [seq, entry] of nodes) {
      if (!keys.has(seq)) {
        entry.node.remove();
        nodes.delete(seq);
        changed = true;
      }
    }
    for (const event of visible) {
      const signature = JSON.stringify(event);
      const old = nodes.get(event.seq);
      if (old?.signature === signature) continue;
      const node = document.createElement("article");
      node.className = "activity-event";
      node.dataset.seq = event.seq;
      node.dataset.kind = event.kind;
      const meta = document.createElement("p");
      meta.className = "activity-meta";
      meta.textContent = `${agentNames[event.agent]} · ${event.kind.replaceAll("_", " ")} · ${event.timestamp || ""}`;
      const summary = document.createElement("p");
      summary.className = "activity-summary";
      summary.textContent = event.summary || "";
      node.append(meta, summary);
      if (typeof event.output_html === "string" && event.output_html) {
        const output = document.createElement("div");
        output.className = "activity-output report-content markdown-body";
        // Same trust boundary as reports: only server-rendered, HTML-disabled Markdown.
        output.innerHTML = event.output_html;
        node.append(output);
      }
      if (old) old.node.replaceWith(node);
      else {
        const after = Array.from(stream.children).find((item) => Number(item.dataset.seq) > event.seq);
        stream.insertBefore(node, after || null);
      }
      nodes.set(event.seq, { node, signature });
      changed = true;
    }
    reader.empty.hidden = visible.length > 0;
    reader.empty.textContent = state === "not-selected"
      ? "This analyst was not selected."
      : next.status === "idle" || !snapshot
        ? "Start a run to follow real agent activity."
        : !Array.isArray(next.activity)
          ? "Activity unavailable for this snapshot. Any published reports remain below."
          : runningStates.has(next.status)
            ? "Waiting for this agent. Only observed events appear here."
            : `No activity recorded for this agent in the retained window (${next.status}). Any available reports remain below.`;
    const latest = visible.at(-1);
    if (latest && latest.seq > reader.latestSequence) {
      reader.latest.textContent = `${agentNames[id]}: ${latest.summary || latest.kind.replaceAll("_", " ")}`;
      reader.latestSequence = latest.seq;
    } else if (!latest) reader.latest.textContent = "";
    if (changed) {
      if (reader.follow && nearBottom) stream.scrollTop = stream.scrollHeight;
      else if (anchor?.isConnected) stream.scrollTop = top + anchor.getBoundingClientRect().top - anchorOffset;
      else stream.scrollTop = top;
    }
  }
}

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
  renderActivity();
}

function configure(data) {
  config = data;
  $("execution-mode").textContent = data.paper_execution_enabled ? "PAPER AUTO ON" : "RESEARCH ONLY";
  message("paper-automation-notice", data.paper_execution_enabled
    ? "Paper automation is ON. Current-day US-stock Buy/Sell decisions may submit simulated orders. No live trades."
    : "");
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
      window.dashboardMotion?.enter($("report-content"));
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
    resetActivity();
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
    ? "Every perspective. In focus."
    : `${next.ticker} / Research`;
  $("workspace-subtitle").textContent = isIdle
    ? "Your next perspective starts here."
    : `Analysis as of ${next.trade_date} · ${next.selected_analysts?.length || 0} analysts selected`;
  $("empty-state").hidden = !isIdle;
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
      "Analysis stopped. Available sections below are partial—not a final decision. Requests already accepted by a provider may still incur charges."
      + (config?.paper_execution_enabled ? " A paper order may already have been submitted; check Alpaca before another run." : "");
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
  $("manager-summary").hidden = !completed;
  for (const [key, id] of [["portfolio", "manager-portfolio"], ["recommendation", "manager-recommendation"]]) {
    const content = completed ? next.manager_summary?.[key] : null;
    if (content) $(id).innerHTML = content;
    else $(id).textContent = completed
      ? (key === "portfolio" ? "Portfolio input was not recorded for this run." : "No manager recommendation was recorded.")
      : "";
  }
  $("paper-execution").hidden = !(completed && next.paper_execution);
  if (completed && next.paper_execution) $("paper-execution-content").innerHTML = next.paper_execution;
  else $("paper-execution-content").replaceChildren();
  message("memory-note", next.memory_note);
  renderActivity();
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
    const next = await request("/api/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": config.csrf_token,
      },
      body: JSON.stringify(data),
    });
    resetActivity();
    render(next);
    $("workspace").focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 760px)").matches)
      $("workspace").scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
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
    window.dashboardMotion?.enter(".setup-panel, .workspace-heading, .agent-roster", true);
    setInterval(refresh, 1000);
  } catch (_) {
    $("run-status").textContent = "OFFLINE";
    message(
      "connection-error",
      "Dashboard setup could not load. Check the local server, then reload this page.",
    );
  }
}
initializeAgents();
initialize();
