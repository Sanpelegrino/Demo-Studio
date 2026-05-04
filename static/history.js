const $ = (sel) => document.querySelector(sel);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function render(items) {
  const ul = $("#history");
  ul.innerHTML = "";
  if (!items.length) {
    ul.innerHTML = '<li class="empty">No changes yet.</li>';
    return;
  }
  for (const h of [...items].reverse()) {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="when">${fmtTime(h.created_at)}</span>
      <span class="lang">${h.language}</span>
      <span class="what">${escapeHtml(h.summary || "(no summary)")}</span>
    `;
    ul.appendChild(li);
  }
}

async function load() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    render(data.history || []);
  } catch (e) {
    $("#history").innerHTML = `<li class="empty">Error: ${escapeHtml(e.message)}</li>`;
  }
}

$("#refresh").addEventListener("click", load);

// Auto-refresh every 5 seconds — embedded dashboards want the list to
// stay current without a user action.
load();
setInterval(load, 5000);
