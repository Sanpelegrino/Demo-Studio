const $ = (sel) => document.querySelector(sel);

// Extension is hosted by the same app that mutates the workspace, so
// relative URLs work. If that ever changes, make this configurable.
const EVENTS_URL = "/api/events";

const state = {
  dashboard: null,
  eventSource: null,
  connected: false,
  lastKind: null,
  busy: false,
};

function log(msg) {
  const el = $("#log");
  const ts = new Date().toLocaleTimeString();
  el.textContent = `[${ts}] ${msg}\n` + el.textContent;
  el.textContent = el.textContent.split("\n").slice(0, 50).join("\n");
}

function setStateBadge() {
  const badge = $("#state");
  if (state.connected) {
    badge.textContent = "connected";
    badge.style.background = "var(--ok)";
    badge.style.color = "#08160f";
  } else {
    badge.textContent = "disconnected";
    badge.style.background = "var(--border)";
    badge.style.color = "var(--muted)";
  }
}

function getDataSources() {
  const dashboard = state.dashboard;
  if (!dashboard) return Promise.resolve([]);
  const seen = new Map();
  const work = [];
  for (const ws of dashboard.worksheets) {
    work.push(ws.getDataSourcesAsync().then((list) => {
      for (const ds of list) {
        if (!seen.has(ds.id)) seen.set(ds.id, ds);
      }
    }));
  }
  return Promise.all(work).then(() => Array.from(seen.values()));
}

async function renderDataSources() {
  try {
    const ds = await getDataSources();
    $("#ds-list").textContent = ds.length
      ? ds.map((d) => d.name).join(", ")
      : "(none found on this dashboard)";
  } catch (e) {
    $("#ds-list").textContent = "(error: " + e.message + ")";
  }
}

async function refreshAll(reason = "manual") {
  if (!state.dashboard) {
    log("Tableau not ready yet — skipping refresh.");
    return;
  }
  if (state.busy) {
    log("Refresh already in progress — skipping.");
    return;
  }
  state.busy = true;
  try {
    const ds = await getDataSources();
    if (!ds.length) {
      log("No data sources to refresh.");
      return;
    }
    await Promise.all(ds.map((d) => d.refreshAsync()));
    $("#last").textContent = new Date().toLocaleTimeString();
    log(`Refreshed ${ds.length} data source${ds.length === 1 ? "" : "s"} (${reason}).`);
  } catch (e) {
    log("Refresh failed: " + e.message);
  } finally {
    state.busy = false;
  }
}

function connectEventStream() {
  if (state.eventSource) state.eventSource.close();
  const es = new EventSource(EVENTS_URL);
  state.eventSource = es;

  es.addEventListener("ready", () => {
    state.connected = true;
    setStateBadge();
    log("Connected to workspace event stream.");
  });

  es.addEventListener("workspace_changed", (ev) => {
    let data = {};
    try { data = JSON.parse(ev.data); } catch {}
    const kind = data.kind || "change";
    state.lastKind = kind;
    $("#last-event").textContent = `${kind}${data.summary ? " — " + data.summary : ""}`;
    log(`Event: ${kind}${data.summary ? " — " + data.summary : ""}`);
    refreshAll(kind);
  });

  es.onerror = () => {
    if (state.connected) {
      log("Event stream disconnected. Reconnecting…");
    }
    state.connected = false;
    setStateBadge();
    // EventSource auto-reconnects; we just update the badge.
  };
}

$("#refresh-now").addEventListener("click", () => refreshAll("manual"));

async function init() {
  if (typeof tableau === "undefined" || !tableau.extensions) {
    const msg = "Tableau Extensions API did not load (check /static/tableau.extensions.1.latest.min.js).";
    $("#ds-list").textContent = msg;
    log(msg);
    return;
  }
  try {
    await tableau.extensions.initializeAsync();
    state.dashboard = tableau.extensions.dashboardContent.dashboard;
    await renderDataSources();
    connectEventStream();
  } catch (e) {
    $("#ds-list").textContent = "Tableau init failed: " + e.message;
    log("Init error: " + e.message);
  }
}

init();
