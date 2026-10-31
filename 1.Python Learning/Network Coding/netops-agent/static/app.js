"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// Minimal, safe markdown: escape first, then code fences, bold, bullets.
function md(text) {
  const parts = String(text || "").split("```");
  return parts.map((p, i) => i % 2
    ? `<pre>${esc(p.replace(/^\w*\n/, ""))}</pre>`
    : esc(p).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/^- (.*)$/gm, "&bull; $1").replace(/\n/g, "<br>")).join("");
}

// ---- tabs
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${t.dataset.tab}`));
  if (t.dataset.tab === "audit") loadAudit();
}));

// ---- init
(async () => {
  try {
    const info = await api("/api/info");
    $("#mode").textContent = info.mock ? "DEMO MODE (mock data)" : "LIVE (read-only)";
    $("#mode").classList.toggle("mock", info.mock);
    $("#user").textContent = info.user;
    $("#device").innerHTML = info.devices.map((d) => `<option value="${esc(d.name)}">${esc(d.name)} (${esc(d.platform)})</option>`).join("");
  } catch (e) { $("#mode").textContent = "Error: " + e.message; }
})();

// ---- ask
document.querySelectorAll("#tab-ask .chip").forEach((c) => c.addEventListener("click", () => { $("#question").value = c.textContent; }));
$("#askBtn").addEventListener("click", async () => {
  const btn = $("#askBtn"); btn.disabled = true; btn.textContent = "Investigating…";
  $("#answer").classList.add("hidden"); $("#steps").innerHTML = "";
  try {
    const r = await api("/api/ask", { question: $("#question").value });
    $("#answer").innerHTML = `<h3>Answer</h3>${md(r.answer)}`;
    $("#answer").classList.remove("hidden");
    $("#steps").innerHTML = `<h3>How I got there (${r.steps.length} steps)</h3>` + r.steps.map(renderStep).join("");
  } catch (e) {
    $("#answer").innerHTML = `<span class="badge error">Error</span> ${esc(e.message)}`; $("#answer").classList.remove("hidden");
  } finally { btn.disabled = false; btn.textContent = "Ask"; }
});

function renderStep(s, i) {
  const r = s.result || {};
  const src = s.tool === "kusto_query" ? "kusto" : "device";
  const title = src === "kusto" ? `Kusto: ${esc(s.args.template)}` : `Device ${esc(s.args.device)}: <code>${esc(s.args.command)}</code>`;
  const status = r.error ? `<span class="badge error">${esc(r.error)}</span>`
    : src === "kusto" ? `${r.row_count} rows` : `${r.elapsed_s}s`;
  const body = r.error ? "" : src === "kusto"
    ? `<pre>${esc(JSON.stringify(r.rows, null, 2))}</pre>` : `<pre>${esc(r.output)}</pre>`;
  return `<details class="step"><summary>${i + 1}. <span class="badge ${src}">${src.toUpperCase()}</span> ${title} — ${status}</summary>${body}</details>`;
}

// ---- run
document.querySelectorAll("#tab-run .chip").forEach((c) => c.addEventListener("click", () => { $("#command").value = c.textContent; }));
const cmdBody = (ack = false) => ({ device: $("#device").value, command: $("#command").value, purpose: $("#purpose").value, acknowledge_warning: ack });

function renderValidation(v) {
  const rules = v.rules.allowed ? `<span class="badge allow">PASS</span>`
    : `<span class="badge deny">BLOCKED</span><ul class="reasons">${v.rules.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`;
  const a = v.ai || {};
  const aiHtml = `<span class="badge ${esc(a.verdict)}">${esc((a.verdict || "").toUpperCase())}</span> ${esc(a.reason || "")}`
    + (a.explanation ? `<br><span class="muted">What it shows:</span> ${esc(a.explanation)}` : "")
    + (a.suggested_command ? `<br><span class="muted">Suggested:</span> <code>${esc(a.suggested_command)}</code>` : "");
  $("#validation").innerHTML = `<h3>Validation for <code>${esc(v.command)}</code> on ${esc(v.device)}</h3>
    <p><b>1. Safety rules:</b> ${rules}</p><p><b>2. AI review:</b> ${aiHtml}</p>
    <p><b>Decision:</b> <span class="badge ${esc(v.decision)}">${esc(v.decision.toUpperCase())}</span></p>`;
  $("#validation").classList.remove("hidden");
}

$("#validateBtn").addEventListener("click", async () => {
  $("#output").classList.add("hidden");
  try { renderValidation(await api("/api/validate", cmdBody())); } catch (e) { alert(e.message); }
});

async function doRun(ack) {
  const btn = $("#runBtn"); btn.disabled = true;
  $("#output").classList.add("hidden");
  try {
    const r = await api("/api/run", cmdBody(ack));
    renderValidation(r.validation);
    if (r.needs_acknowledgement && confirm(`AI flagged this command: ${r.validation.ai.reason}\n\nRun it anyway?`)) return doRun(true);
    if (r.executed) { $("#output").textContent = r.result.output || "(no output)"; $("#output").classList.remove("hidden"); }
    else if (r.error) { $("#output").textContent = "Error: " + r.error; $("#output").classList.remove("hidden"); }
  } catch (e) { alert(e.message); } finally { btn.disabled = false; }
}
$("#runBtn").addEventListener("click", () => doRun(false));
$("#command").addEventListener("keydown", (e) => { if (e.key === "Enter") doRun(false); });

// ---- audit
async function loadAudit() {
  try {
    const rows = await api("/api/audit?limit=200");
    $("#auditTable tbody").innerHTML = rows.map((r) => {
      const { ts, user, action, ...rest } = r;
      return `<tr><td>${esc(ts.replace("T", " ").slice(0, 19))}</td><td>${esc(user)}</td><td>${esc(action)}</td><td><code>${esc(JSON.stringify(rest))}</code></td></tr>`;
    }).join("");
  } catch (e) { alert(e.message); }
}
$("#refreshAudit").addEventListener("click", loadAudit);
