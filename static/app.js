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

if ($("#save-dataset")) {
  $("#save-dataset").addEventListener("click", async () => {
    const name = prompt("Save current workspace as dataset.\nEnter a name:");
    if (!name || !name.trim()) return;
    setStatus("Saving…");
    const btn = $("#save-dataset");
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/datasets/save", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      setStatus(`Saved "${res.name}" (${res.tables} tables).`, "ok");
      await refreshDatasets();
    } catch (e) {
      setStatus(e.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

if ($("#delete-dataset")) {
  $("#delete-dataset").addEventListener("click", async () => {
    const dataset = $("#conn-dataset")?.textContent?.trim() || "this dataset";
    if (!confirm(`Delete "${dataset}" and wipe the workspace?`)) return;
    const btn = $("#delete-dataset");
    if (btn) btn.disabled = true;
    setStatus("Deleting…");
    try {
      const res = await fetch("/api/datasets/delete", { method: "DELETE" });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      setStatus(`Deleted "${dataset}".`, "ok");
      await refreshAll();
    } catch (e) {
      setStatus(e.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });
}

if ($("#rename-dataset")) {
  $("#rename-dataset").addEventListener("click", async () => {
    const current = $("#conn-dataset")?.textContent || "";
    const newName = prompt("Rename dataset:", current);
    if (!newName || !newName.trim() || newName.trim() === current) return;
    try {
      const res = await api("/api/datasets/rename", {
        method: "PATCH",
        body: JSON.stringify({ new_name: newName.trim() }),
      });
      setStatus(`Renamed to "${res.name}".`, "ok");
      await refreshAll();
    } catch (e) {
      setStatus(e.message, "err");
    }
  });
}


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

if ($("#file-upload")) {
  $("#file-upload").addEventListener("change", async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setStatus("Uploading…");
    try {
      const form = new FormData();
      for (const f of files) {
        form.append("files", f);
      }
      const res = await fetch("/api/datasets/upload", { method: "POST", body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      const data = await res.json();
      if (data.loaded) {
        setStatus(`Loaded ${data.dataset || data.name}.`, "ok");
        await refreshAll();
      } else if (data.needs_config) {
        _configState = { folder: data.folder, name: data.name, tables: data.tables, configType: data.config_type };
        openConfigModal(data);
      } else {
        setStatus(`Uploaded ${data.name}. Select it and click Load.`, "ok");
        await refreshDatasets();
        const sel = $("#dataset-select");
        if (sel) sel.value = `manifest:${data.folder}`;
      }
    } catch (err) {
      setStatus(err.message, "err");
    }
    e.target.value = "";
  });
}

if ($("#folder-upload-link")) {
  $("#folder-upload-link").addEventListener("click", (e) => {
    e.preventDefault();
    const input = $("#folder-upload");
    if (input) input.click();
  });
}

// --- Folder upload + config modal logic ---

let _configState = null; // { folder, name, tables, configType }

if ($("#folder-upload")) {
  $("#folder-upload").addEventListener("change", async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setStatus("Uploading folder…");
    try {
      const form = new FormData();
      for (const f of files) {
        form.append("files", f);
      }
      const res = await fetch("/api/datasets/upload", { method: "POST", body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
      }
      const data = await res.json();
      if (data.loaded) {
        setStatus(`Loaded ${data.dataset || data.name}.`, "ok");
        await refreshAll();
      } else if (data.needs_config) {
        _configState = { folder: data.folder, name: data.name, tables: data.tables, configType: data.config_type };
        openConfigModal(data);
      }
    } catch (err) {
      setStatus(err.message, "err");
    }
    e.target.value = "";
  });
}

function openConfigModal(data) {
  const modal = $("#config-modal");
  if (!modal) return;
  modal.classList.remove("hidden");

  const title = $("#config-modal-title");
  if (title) title.textContent = `Configure: ${data.name}`;

  // Reset all sections and their contents
  const sheetPicker = $("#config-sheet-picker");
  const tablesSection = $("#config-tables");
  const joinsSection = $("#config-joins");
  if (sheetPicker) sheetPicker.classList.add("hidden");
  if (tablesSection) tablesSection.classList.add("hidden");
  if (joinsSection) joinsSection.classList.add("hidden");

  const joinsList = $("#config-joins-list");
  if (joinsList) joinsList.innerHTML = "";

  const tablesList = $("#config-tables-list");
  if (tablesList) tablesList.innerHTML = "";

  const sheetsList = $("#config-sheets-list");
  if (sheetsList) sheetsList.innerHTML = "";

  // Reset radio buttons to default
  const singleRadio = document.querySelector('input[name="config-mode"][value="single"]');
  if (singleRadio) singleRadio.checked = true;

  if (data.config_type === "sheets") {
    if (sheetPicker) sheetPicker.classList.remove("hidden");
    renderSheetPicker(data.tables);
  } else if (data.config_type === "joins") {
    if (tablesSection) tablesSection.classList.remove("hidden");
    if (joinsSection) joinsSection.classList.remove("hidden");
    renderTablesList(data.tables);
    renderJoinRows();
  }
}

function closeConfigModal() {
  const modal = $("#config-modal");
  if (modal) modal.classList.add("hidden");
  const joinsList = $("#config-joins-list");
  if (joinsList) joinsList.innerHTML = "";
  _configState = null;
}

function renderSheetPicker(tables) {
  const list = $("#config-sheets-list");
  if (!list) return;
  list.innerHTML = "";
  tables.forEach((t) => {
    const label = document.createElement("label");
    label.className = "table-info-card";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = t.name;
    cb.checked = true;
    cb.addEventListener("change", updateSingleModeAvailability);
    label.appendChild(cb);
    const info = document.createElement("span");
    info.innerHTML = ` <strong class="table-name">${escapeHtml(t.name)}</strong> <span class="table-rows">(${t.row_count.toLocaleString()} rows)</span><br><span class="table-columns">${t.columns.slice(0, 5).map(escapeHtml).join(", ")}${t.columns.length > 5 ? "…" : ""}</span>`;
    label.appendChild(info);
    list.appendChild(label);
  });
  updateSingleModeAvailability();
}

function updateSingleModeAvailability() {
  const checked = document.querySelectorAll("#config-sheets-list input[type=checkbox]:checked");
  const singleRadio = document.querySelector('input[name="config-mode"][value="single"]');
  const multiRadio = document.querySelector('input[name="config-mode"][value="multi"]');
  if (!singleRadio) return;
  if (checked.length > 1) {
    singleRadio.disabled = true;
    if (singleRadio.checked) {
      multiRadio.checked = true;
      multiRadio.dispatchEvent(new Event("change", { bubbles: true }));
    }
  } else {
    singleRadio.disabled = false;
  }
}

function renderTablesList(tables) {
  const list = $("#config-tables-list");
  if (!list) return;
  list.innerHTML = "";
  tables.forEach((t) => {
    const div = document.createElement("div");
    div.className = "table-info-card";
    div.innerHTML = `<strong class="table-name">${escapeHtml(t.name)}</strong> <span class="table-rows">(${t.row_count.toLocaleString()} rows)</span><br><span class="table-columns">${t.columns.slice(0, 6).map(escapeHtml).join(", ")}${t.columns.length > 6 ? "…" : ""}</span>`;
    list.appendChild(div);
  });
}

function renderJoinRows() {
  const list = $("#config-joins-list");
  if (!list) return;
  // Start with one empty row if none exist
  if (list.children.length === 0) addJoinRow();
}

function addJoinRow() {
  const list = $("#config-joins-list");
  if (!list || !_configState) return;
  const tables = _configState.tables;

  const row = document.createElement("div");
  row.className = "join-row";

  // From table select
  const fromTable = document.createElement("select");
  fromTable.className = "join-from-table";
  tables.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = t.name;
    fromTable.appendChild(opt);
  });

  // From field select
  const fromField = document.createElement("select");
  fromField.className = "join-from-field";

  // Arrow
  const arrow = document.createElement("span");
  arrow.className = "join-arrow";
  arrow.textContent = "→";

  // To table select
  const toTable = document.createElement("select");
  toTable.className = "join-to-table";
  tables.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = t.name;
    toTable.appendChild(opt);
  });
  // Default to second table if available
  if (tables.length > 1) toTable.value = tables[1].name;

  // To field select
  const toField = document.createElement("select");
  toField.className = "join-to-field";

  // Remove button
  const removeBtn = document.createElement("button");
  removeBtn.className = "join-remove mini";
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", () => row.remove());

  // Populate field selects when table changes
  function populateFields(tableSelect, fieldSelect) {
    const tableName = tableSelect.value;
    const table = tables.find((t) => t.name === tableName);
    fieldSelect.innerHTML = "";
    if (table) {
      table.columns.forEach((col) => {
        const opt = document.createElement("option");
        opt.value = col;
        opt.textContent = col;
        fieldSelect.appendChild(opt);
      });
    }
  }

  fromTable.addEventListener("change", () => populateFields(fromTable, fromField));
  toTable.addEventListener("change", () => populateFields(toTable, toField));

  row.appendChild(fromTable);
  row.appendChild(fromField);
  row.appendChild(arrow);
  row.appendChild(toTable);
  row.appendChild(toField);
  row.appendChild(removeBtn);
  list.appendChild(row);

  // Initial population
  populateFields(fromTable, fromField);
  populateFields(toTable, toField);
}

if ($("#config-add-join")) {
  $("#config-add-join").addEventListener("click", addJoinRow);
}

if ($("#config-cancel")) {
  $("#config-cancel").addEventListener("click", closeConfigModal);
}

if ($("#config-load")) {
  $("#config-load").addEventListener("click", async () => {
    if (!_configState) return;
    const { folder, configType, tables } = _configState;

    let body = { folder };

    if (configType === "sheets") {
      // Check which mode is selected
      const mode = document.querySelector('input[name="config-mode"]:checked');
      const modeValue = mode ? mode.value : "single";

      // Get checked sheets
      const checked = [...document.querySelectorAll("#config-sheets-list input[type=checkbox]:checked")]
        .map((cb) => cb.value);

      if (checked.length === 0) {
        setStatus("Select at least one sheet.", "err");
        return;
      }

      if (modeValue === "single") {
        // Load first checked sheet as single table
        body.sheet = checked[0];
      } else {
        // Multiple sheets — need joins
        body.sheets = checked;
        // Collect join definitions from the join builder
        const joins = collectJoinDefs();
        if (joins.length === 0) {
          // Show join builder if not visible
          const joinsSection = $("#config-joins");
          const tablesSection = $("#config-tables");
          if (joinsSection) joinsSection.classList.remove("hidden");
          if (tablesSection) {
            tablesSection.classList.remove("hidden");
            // Re-render tables with only checked sheets
            const selectedTables = tables.filter((t) => checked.includes(t.name));
            _configState.tables = selectedTables;
            renderTablesList(selectedTables);
          }
          renderJoinRows();
          setStatus("Define at least one relationship between tables.", "err");
          return;
        }
        body.joins = joins;
      }
    } else {
      // Multi-CSV: collect joins
      const joins = collectJoinDefs();
      if (joins.length === 0) {
        setStatus("Define at least one relationship between tables.", "err");
        return;
      }
      body.joins = joins;
    }

    // Send configure request
    setStatus("Loading dataset…");
    const loadBtn = $("#config-load");
    if (loadBtn) loadBtn.disabled = true;

    try {
      const res = await api("/api/datasets/configure", {
        method: "POST",
        body: JSON.stringify(body),
      });
      closeConfigModal();
      const tableCount = Object.keys(res.tables || {}).length;
      const rowTotal = Object.values(res.tables || {}).reduce((a, b) => a + b, 0);
      setStatus(`Loaded ${res.dataset}: ${tableCount} tables, ${rowTotal.toLocaleString()} rows.`, "ok");
      await refreshAll();
    } catch (err) {
      setStatus(err.message, "err");
    } finally {
      if (loadBtn) loadBtn.disabled = false;
    }
  });
}

function collectJoinDefs() {
  const rows = document.querySelectorAll("#config-joins-list .join-row");
  const joins = [];
  rows.forEach((row) => {
    const fromTable = row.querySelector(".join-from-table")?.value;
    const fromField = row.querySelector(".join-from-field")?.value;
    const toTable = row.querySelector(".join-to-table")?.value;
    const toField = row.querySelector(".join-to-field")?.value;
    if (fromTable && fromField && toTable && toField) {
      joins.push({ from_table: fromTable, from_field: fromField, to_table: toTable, to_field: toField });
    }
  });
  return joins;
}

document.querySelectorAll('input[name="config-mode"]').forEach((radio) => {
  radio.addEventListener("change", (e) => {
    const joinsSection = $("#config-joins");
    const tablesSection = $("#config-tables");
    if (e.target.value === "multi") {
      if (joinsSection) joinsSection.classList.remove("hidden");
      if (tablesSection) tablesSection.classList.remove("hidden");
      // Render tables and first join row if not already
      if (_configState) {
        const checked = [...document.querySelectorAll("#config-sheets-list input[type=checkbox]:checked")]
          .map((cb) => cb.value);
        const selectedTables = _configState.tables.filter((t) => checked.includes(t.name));
        renderTablesList(selectedTables);
        renderJoinRows();
      }
    } else {
      if (joinsSection) joinsSection.classList.add("hidden");
      if (tablesSection) tablesSection.classList.add("hidden");
    }
  });
});

// --- End folder upload + config modal logic ---

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
