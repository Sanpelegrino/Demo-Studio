const $ = (sel) => document.querySelector(sel);

let currentPlan = null;
let lastUserMessage = "";

const AUTORUN_KEY = "demo-studio.autorun";
const SHOW_CODE_KEY = "demo-studio.show-code";
const autorunEnabled = () => !!$("#autorun")?.checked;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
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
  setText("#schema", s.schema);
  setText("#sample", s.sample);
  renderHistory(s.history || []);
}

function showPlan(plan) {
  currentPlan = plan;
  $("#plan-summary").textContent = plan.summary || "(no summary)";
  $("#plan-lang").textContent = plan.language;
  $("#plan-notes").textContent = plan.notes ? `· ${plan.notes}` : "";
  // embed.html omits this element so dashboard viewers don't see raw SQL.
  const codeEl = $("#plan-code");
  if (codeEl) codeEl.textContent = plan.code;
  $("#plan").classList.remove("hidden");
  $("#apply-top").classList.remove("hidden");
  $("#discard-top").classList.remove("hidden");
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
      body: JSON.stringify({ message }),
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

$("#reseed").addEventListener("click", async () => {
  const dataset = $("#reseed-dataset").value || "salesforce";
  const label = dataset === "superstore" ? "Superstore" : "Salesforce";
  if (!confirm(`Wipe workspace and reseed with ${label}?`)) return;
  try {
    await api(`/api/reseed?dataset=${encodeURIComponent(dataset)}`, { method: "POST" });
    setStatus(`Reseeded with ${label}.`, "ok");
    await refresh();
  } catch (e) {
    setStatus(e.message, "err");
  }
});

$("#refresh").addEventListener("click", refresh);

async function refreshDatasets() {
  const sel = $("#manifest-select");
  if (!sel) return;
  try {
    const res = await api("/api/datasets");
    const prev = sel.value;
    sel.innerHTML = '<option value="">— select dataset —</option>';
    for (const d of res.datasets) {
      const opt = document.createElement("option");
      opt.value = d.folder;
      opt.textContent = d.name;
      sel.appendChild(opt);
    }
    if (prev) sel.value = prev;
  } catch { /* ignore — list is a convenience */ }
}

async function loadManifestFolder(folder) {
  if (!folder) {
    setStatus("Select a dataset first.", "err");
    return;
  }
  if (!confirm(`Wipe the workspace and load:\n${folder}?`)) return;
  setStatus("Loading manifest…");
  const btn = $("#manifest-load");
  if (btn) btn.disabled = true;
  try {
    const res = await api("/api/load-manifest", {
      method: "POST",
      body: JSON.stringify({ folder }),
    });
    const tableCount = Object.keys(res.tables || {}).length;
    const rowTotal = Object.values(res.tables || {}).reduce((a, b) => a + b, 0);
    setStatus(
      `Loaded ${res.dataset}: ${tableCount} tables, ${rowTotal.toLocaleString()} rows.`,
      "ok",
    );
    await refreshAll();
  } catch (e) {
    setStatus(e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

if ($("#manifest-load")) {
  $("#manifest-load").addEventListener("click", () => {
    const sel = $("#manifest-select");
    loadManifestFolder(sel ? sel.value : "");
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
      // Auto-select the just-uploaded dataset.
      const sel = $("#manifest-select");
      if (sel) sel.value = data.folder;
    } catch (err) {
      setStatus(err.message, "err");
    }
    e.target.value = "";
  });
}

$("#copy-pass").addEventListener("click", async () => {
  const text = $("#conn-pass").textContent;
  try {
    await navigator.clipboard.writeText(text);
    setStatus("Password copied.", "ok");
  } catch {
    setStatus("Copy failed — select manually.", "err");
  }
});

function applyMaxMode(on) {
  document.body.classList.toggle("chat-max", on);
  const btn = $("#maximize");
  if (btn) btn.textContent = on ? "Restore" : "Maximize";
  if (on) location.hash = "chat";
  else if (location.hash === "#chat") history.replaceState(null, "", location.pathname);
}

$("#maximize").addEventListener("click", () => {
  applyMaxMode(!document.body.classList.contains("chat-max"));
});

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

// Show-code toggle (embed/extension only) — off by default, persisted.
// Sets inline style directly on #plan-code to bypass any CSS cache in the
// Tableau extension webview.
const showCodeEl = $("#show-code");
function applyShowCode(on) {
  document.documentElement.classList.toggle("show-code", on);
  const codeEl = $("#plan-code");
  if (codeEl) codeEl.style.display = on ? "block" : "none";
}
if (showCodeEl) {
  const on = localStorage.getItem(SHOW_CODE_KEY) === "1";
  showCodeEl.checked = on;
  applyShowCode(on);
  showCodeEl.addEventListener("change", () => {
    localStorage.setItem(SHOW_CODE_KEY, showCodeEl.checked ? "1" : "0");
    applyShowCode(showCodeEl.checked);
  });
}

// --- Pitfalls panel (only present on the main page, not on /embed) ---
async function loadPitfalls() {
  const textEl = $("#pitfalls-text");
  const countEl = $("#pitfalls-raw-count");
  if (!textEl || !countEl) return;
  try {
    const p = await api("/api/pitfalls");
    textEl.value = p.curated || "";
    countEl.textContent = p.raw_count
      ? `${p.raw_count} failure${p.raw_count === 1 ? "" : "s"} logged`
      : "no failures logged";
  } catch (e) {
    countEl.textContent = "error: " + e.message;
  }
}

if ($("#pitfalls-save")) {
  $("#pitfalls-save").addEventListener("click", async () => {
    const curated = $("#pitfalls-text").value;
    try {
      await api("/api/pitfalls", {
        method: "PUT",
        body: JSON.stringify({ curated }),
      });
      setStatus("Pitfalls saved. Future chats will use the new guidance.", "ok");
    } catch (e) {
      setStatus(e.message, "err");
    }
  });
}

if ($("#pitfalls-download")) {
  $("#pitfalls-download").addEventListener("click", () => {
    window.location.href = "/api/pitfalls/raw";
  });
}

if ($("#pitfalls-clear")) {
  $("#pitfalls-clear").addEventListener("click", async () => {
    if (!confirm("Clear the raw failure log? (Keeps your curated pitfalls.)")) return;
    try {
      await fetch("/api/pitfalls/raw", { method: "DELETE" });
      await loadPitfalls();
      setStatus("Raw failure log cleared.", "ok");
    } catch (e) {
      setStatus(e.message, "err");
    }
  });
}

async function refreshAll() {
  await refresh();
  await loadPitfalls();
  await refreshDatasets();
}

refreshAll().catch((e) => setStatus(e.message, "err"));
