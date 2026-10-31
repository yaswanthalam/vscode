"use strict";
let token = "";
let state = null;
let report = null;
let busy = false;
const el = (id) => document.getElementById(id);
function status(text, error = false) {
  el("status").textContent = text;
  el("status").className = error ? "error" : "";
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
el("connect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = el("token").value.trim();
  try {
    state = await api("/api/status");
    el("token").value = "";
    el("connect-panel").hidden = true;
    el("workspace").hidden = false;
    el("mode").textContent = state.mode === "demo" ? "DEMO / SYNTHETIC" : "LIVE / READ-ONLY";
    const providers = state.ai_providers.map((item) =>
      `${item.name}: ${item.configured ? "key configured" : "key missing"}, sharing ${item.sharing ? "enabled" : "disabled"}, ${item.model}`).join(" | ");
    el("notice").textContent = state.mode === "demo"
      ? "DEMO: No device connections or AI provider calls. Every output is synthetic. Start with --mode live after local setup."
      : `LIVE: AI fallback order: ${state.ai_providers.map((item) => item.name).join(" -> ")}. ${providers}. Questions and bounded, redacted device/log evidence may be sent to enabled providers (including OpenRouter downstream models). Configuration is not a health check. Manual show commands stay local.`;
    for (const [name, device] of Object.entries(state.devices)) {
      const card = node("label", undefined, "device");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox"; checkbox.value = name; checkbox.checked = true;
      const info = node("div");
      info.append(node("strong", name), node("span", `${device.host}:${device.port}`),
        node("small", device.description));
      card.append(checkbox, info); el("devices").append(card);
      const option = node("option", name); option.value = name; el("log-device").append(option);
    }
    for (const [id, command] of Object.entries(state.commands)) {
      const option = node("option", command.command);
      option.value = id; el("command").append(option);
    }
    status("Connected to the local backend.");
  } catch (error) { token = ""; status(error.message, true); }
});
document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => { el("question").value = button.textContent; el("question").focus(); });
});
function selectedDevices() {
  return Array.from(document.querySelectorAll("#devices input:checked"), (item) => item.value);
}
function render(data) {
  report = data;
  el("result-panel").hidden = false;
  el("export").disabled = false;
  el("run-meta").textContent = `${data.mode.toUpperCase()} | ${data.completed_at} | Run ${data.run_id}`;
  el("ai-route").textContent = data.ai_trace.length
    ? `AI routing: ${data.ai_trace.map((item) => `${item.stage}: ${item.provider} / ${item.model} (${item.status})`).join(" -> ")}`
    : "No external AI provider was used.";
  el("answer").textContent = data.answer;
  el("warnings").replaceChildren(...data.warnings.map((text) => node("li", text)));
  el("plan").replaceChildren(...data.plan.map((step) =>
    node("span", `${step.device}: ${state.commands[step.command_id].command}`, "chip")));
  el("evidence").replaceChildren();
  for (const item of data.evidence) {
    const details = node("details", undefined, "evidence");
    const summary = node("summary", `${item.device} | ${item.command || item.source} | ${item.status}${item.truncated ? " / TRUNCATED" : ""}`);
    details.append(summary, node("p", `[${item.id}] ${item.observed_at} | ${item.mode} | ${item.source}`, "muted"));
    if (item.note) details.append(node("p", item.note, "muted"));
    details.append(node("pre", item.output));
    if (item.run_id === data.run_id) details.open = true;
    el("evidence").append(details);
  }
}
async function investigate(commandId) {
  if (busy) return;
  const devices = selectedDevices();
  if (!devices.length) { status("Select at least one device.", true); return; }
  busy = true;
  document.querySelectorAll("button[type=submit]").forEach((button) => { button.disabled = true; });
  status("Collecting read-only evidence. SSH and AI calls can take several minutes; do not resubmit.");
  try {
    const request = { devices, question: commandId ? `Run ${state.commands[commandId].command}` : el("question").value.trim() };
    if (commandId) request.command_id = commandId;
    const data = await api("/api/investigate", request);
    render(data);
    const failures = data.evidence.filter((item) => item.run_id === data.run_id && item.status !== "ok").length;
    status(`Investigation returned. ${failures} command(s) reported errors, unsupported features or denied access.`, failures > 0);
  } catch (error) { status(error.message, true); }
  finally {
    busy = false;
    document.querySelectorAll("button[type=submit]").forEach((button) => { button.disabled = false; });
  }
}
el("ask-form").addEventListener("submit", (event) => { event.preventDefault(); investigate(); });
el("command-form").addEventListener("submit", (event) => { event.preventDefault(); investigate(el("command").value); });
el("import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const record = await api("/api/import", { device: el("log-device").value, text: el("log-text").value });
    el("log-text").value = "";
    status(`Stored unverified local log evidence [${record.id}]. It will be available to the next investigation.`);
  } catch (error) { status(error.message, true); }
});
el("export").addEventListener("click", () => {
  if (!report) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = `network-report-${report.run_id}.json`; link.click();
  URL.revokeObjectURL(url);
});
