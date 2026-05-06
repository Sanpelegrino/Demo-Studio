const $ = (sel) => document.querySelector(sel);

let currentPlan = null;
let lastUserMessage = "";

const AUTORUN_KEY = "demo-studio.autorun";
const SHOW_CODE_KEY = "demo-studio.show-code";
const MODEL_KEY = "demo-studio.model";
const autorunEnabled = () => !!$("#autorun")?.checked;
const selectedModel = () => $("#model-select")?.value || null;

async function api(path, opts = {}) {
  const headers = opts.body ? { "Content-Type": "application/json" } : {};
  const res = await fetch(path, {
    headers,
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function setStatus(msg, kind = "") {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status " + kind;
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderHistory(items) {
  const ul = $("#history");
  if (!ul) return;
  ul.innerHTML = "";
  if (!items.length) {
    ul.innerHTML = '<li class="empty">No changes yet.</li>';
    hideHistoryDetail();
    return;
  }
  for (const h of [...items].reverse()) {
    const li = document.createElement("li");
    li.className = "history-item";
    li.dataset.id = h.id;
    li.innerHTML = `
      <span class="when">${fmtTime(h.created_at)}</span>
      <span class="lang">${h.language}</span>
      <span class="what">${escapeHtml(h.summary || "(no summary)")}</span>
    `;
    li.addEventListener("click", () => showHistoryDetail(h));
    ul.appendChild(li);
  }
}

function showHistoryDetail(h) {
  const wrap = $("#history-detail");
  if (!wrap) return;
  $("#history-detail-lang").textContent = h.language || "";
  $("#history-detail-summary").textContent = h.summary || "(no summary)";
  $("#history-detail-code").textContent = h.code || "(no code recorded)";
  wrap.classList.remove("hidden");
  document.querySelectorAll("#history .history-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.id === h.id);
  });
}

function hideHistoryDetail() {
  const wrap = $("#history-detail");
  if (!wrap) return;
  wrap.classList.add("hidden");
  document.querySelectorAll("#history .history-item.selected")
    .forEach((el) => el.classList.remove("selected"));
}

document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "history-detail-close") hideHistoryDetail();
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const setText = (sel, value) => {
  const el = $(sel);
  if (el) el.textContent = value;
};

async function refresh() {
  const s = await api("/api/status");
  const c = s.connection;
  setText("#conn-host", c.host);
  setText("#conn-port", c.port);
  setText("#conn-db", c.database);
  setText("#conn-user", c.user);
  setText("#conn-pass", c.password);
  setText("#conn-schema", c.schema);
  const viewName = c.view ? `${c.schema}.${c.view}` : "(none)";
  setText("#conn-view", viewName);
  setText("#conn-view-inline", viewName);
  setText("#conn-view-rows",
    s.tableau_view_row_count ? `(${s.tableau_view_row_count.toLocaleString()} rows)` : "");
  setText("#conn-tables", s.tables.join(", ") || "(none)");
  setText("#conn-dataset", s.active_dataset || "");
  setText("#schema", s.schema);
  setText("#sample", s.sample);
  const embedCtx = $("#embed-context");
  if (embedCtx) {
    const rows = s.tableau_view_row_count ? ` (${s.tableau_view_row_count.toLocaleString()} rows)` : "";
    embedCtx.textContent = viewName + rows;
  }
  renderHistory(s.history || []);
}

function showPlan(plan) {
  currentPlan = plan;
  $("#plan-summary").textContent = plan.summary || "(no summary)";
  $("#plan-lang").textContent = plan.language;
  $("#plan-notes").textContent = plan.notes ? `· ${plan.notes}` : "";
  const codeEl = $("#plan-code");
  if (codeEl) codeEl.textContent = plan.code;
  $("#plan").classList.remove("hidden");
  $("#apply-top").classList.remove("hidden");
  $("#discard-top").classList.remove("hidden");
  // Re-apply show-code state so the inline style is set on the now-visible element.
  const sc = $("#show-code");
  if (sc) applyShowCode(sc.checked);
}

function hidePlan() {
  currentPlan = null;
  $("#plan").classList.add("hidden");
  $("#apply-top").classList.add("hidden");
  $("#discard-top").classList.add("hidden");
}

$("#send").addEventListener("click", async () => {
  const message = $("#message").value.trim();
  if (!message) return;
  lastUserMessage = message;
  const auto = autorunEnabled();
  setStatus(auto ? "Planning (autorun)…" : "Planning…");
  $("#send").disabled = true;
  hidePlan();
  try {
    const plan = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, model: selectedModel() }),
    });
    showPlan(plan);
    if (auto) {
      setStatus("Plan ready — applying automatically…", "ok");
      await applyCurrentPlan();
    } else {
      setStatus("Plan ready. Review and Apply.", "ok");
    }
  } catch (e) {
    setStatus(e.message, "err");
  } finally {
    $("#send").disabled = false;
  }
});

async function applyCurrentPlan() {
  if (!currentPlan) return;
  setStatus("Applying…");
  $("#apply-top").disabled = true;
  try {
    const res = await api("/api/apply", {
      method: "POST",
      body: JSON.stringify({
        language: currentPlan.language,
        code: currentPlan.code,
        summary: currentPlan.summary,
        original_message: lastUserMessage || null,
      }),
    });
    const retryCount = (res.attempts || []).length;
    if (res.ok) {
      const retryNote = retryCount
        ? ` (recovered after ${retryCount} failed attempt${retryCount === 1 ? "" : "s"})`
        : "";
      setStatus(
        `Applied${retryNote}. Tableau will auto-refresh if the Live Refresh extension is loaded.`,
        "ok",
      );
      $("#message").value = "";
      hidePlan();
      await refreshAll();
    } else {
      const tried = retryCount || 1;
      setStatus(
        `Execution failed after ${tried} attempt${tried === 1 ? "" : "s"}, rolled back: ${res.error}`,
        "err",
      );
    }
  } catch (e) {
    setStatus(e.message, "err");
  } finally {
    $("#apply-top").disabled = false;
  }
}

$("#apply-top").addEventListener("click", applyCurrentPlan);
$("#discard-top").addEventListener("click", () => {
  hidePlan();
  setStatus("Discarded.");
});

if ($("#rollback")) {
  $("#rollback").addEventListener("click", async () => {
    if (!confirm("Roll back the most recent change?")) return;
    try {
      const r = await api("/api/rollback", { method: "POST" });
      setStatus(`Rolled back: ${r.summary}`, "ok");
      await refresh();
    } catch (e) {
      setStatus(e.message, "err");
    }
  });
}

if ($("#refresh")) $("#refresh").addEventListener("click", refresh);

async function refreshDatasets() {
  const sel = $("#dataset-select");
  if (!sel) return;
  try {
    const res = await api("/api/datasets");
    // Remove previously-added manifest options (keep built-ins).
    sel.querySelectorAll("option[data-manifest]").forEach((o) => o.remove());
    for (const d of res.datasets) {
      const opt = document.createElement("option");
      opt.value = `manifest:${d.folder}`;
      opt.textContent = d.name;
      opt.dataset.manifest = "1";
      sel.appendChild(opt);
    }
  } catch { /* ignore — list is a convenience */ }
}

if ($("#dataset-load")) {
  $("#dataset-load").addEventListener("click", async () => {
    const sel = $("#dataset-select");
    const val = sel ? sel.value : "salesforce";
    const label = sel ? sel.options[sel.selectedIndex].textContent : val;
    if (!confirm(`Wipe workspace and load: ${label}?`)) return;
    const btn = $("#dataset-load");
    if (btn) btn.disabled = true;
    setStatus("Loading…");
    try {
      if (val.startsWith("manifest:")) {
        const folder = val.slice("manifest:".length);
        const res = await api("/api/load-manifest", {
          method: "POST",
          body: JSON.stringify({ folder }),
        });
        const tableCount = Object.keys(res.tables || {}).length;
        const rowTotal = Object.values(res.tables || {}).reduce((a, b) => a + b, 0);
        setStatus(`Loaded ${res.dataset}: ${tableCount} tables, ${rowTotal.toLocaleString()} rows.`, "ok");
      } else {
        await api(`/api/reseed?dataset=${encodeURIComponent(val)}`, { method: "POST" });
        setStatus(`Loaded ${label}.`, "ok");
      }
      await refreshAll();
    } catch (e) {
      setStatus(e.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

if ($("#manifest-upload")) {
  $("#manifest-upload").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setStatus("Uploading…");
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/datasets/upload", { method: "POST", body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      const data = await res.json();
      setStatus(`Uploaded ${data.name}. Select it and click Load.`, "ok");
      await refreshDatasets();
      const sel = $("#dataset-select");
      if (sel) sel.value = `manifest:${data.folder}`;
    } catch (err) {
      setStatus(err.message, "err");
    }
    e.target.value = "";
  });
}

if ($("#copy-pass")) {
  $("#copy-pass").addEventListener("click", async () => {
    const text = $("#conn-pass").textContent;
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Password copied.", "ok");
    } catch {
      setStatus("Copy failed — select manually.", "err");
    }
  });
}

function applyMaxMode(on) {
  document.body.classList.toggle("chat-max", on);
  const btn = $("#maximize");
  if (btn) btn.textContent = on ? "Restore" : "Maximize";
  if (on) location.hash = "chat";
  else if (location.hash === "#chat") history.replaceState(null, "", location.pathname);
}

if ($("#maximize")) {
  $("#maximize").addEventListener("click", () => {
    applyMaxMode(!document.body.classList.contains("chat-max"));
  });
}

// Enter maximized mode if URL hash is #chat (for iframe embeds).
if (location.hash === "#chat") applyMaxMode(true);

// Autorun toggle — persist across reloads.
const autorunEl = $("#autorun");
if (autorunEl) {
  autorunEl.checked = localStorage.getItem(AUTORUN_KEY) === "1";
  autorunEl.addEventListener("change", () => {
    localStorage.setItem(AUTORUN_KEY, autorunEl.checked ? "1" : "0");
  });
}

// Model selector — persist across reloads.
const modelEl = $("#model-select");
if (modelEl) {
  const saved = localStorage.getItem(MODEL_KEY);
  if (saved) modelEl.value = saved;
  modelEl.addEventListener("change", () => {
    localStorage.setItem(MODEL_KEY, modelEl.value);
  });
}

// Show-code toggle (embed/extension only) — off by default, persisted.
// Toggles .show-code on <html> AND sets inline style as a belt-and-suspenders
// fix for Tableau extension webviews where CSS specificity can be unreliable.
const showCodeEl = $("#show-code");
function applyShowCode(on) {
  document.documentElement.classList.toggle("show-code", on);
  const codeEl = $("#plan-code");
  if (codeEl) codeEl.style.setProperty("display", on ? "block" : "none", "important");
}
if (showCodeEl) {
  let stored = false;
  try { stored = localStorage.getItem(SHOW_CODE_KEY) === "1"; } catch {}
  showCodeEl.checked = stored;
  applyShowCode(stored);
  showCodeEl.addEventListener("change", () => {
    const on = showCodeEl.checked;
    try { localStorage.setItem(SHOW_CODE_KEY, on ? "1" : "0"); } catch {}
    applyShowCode(on);
  });
}

async function refreshAll() {
  await refresh();
  await refreshDatasets();
}

refreshAll().catch((e) => setStatus(e.message, "err"));
