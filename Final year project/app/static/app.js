"use strict";
const $ = (id) => document.getElementById(id);
let catalog = null;
let disease = "diabetes";
let registering = false;
let signedInUser = "";
let historyOffset = 0;
let statusTimer;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function notify(text, error = false) {
  clearTimeout(statusTimer);
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
  $("status").hidden = false;
  statusTimer = setTimeout(() => { $("status").hidden = true; }, error ? 14000 : 8000);
}

async function api(path, options = {}) {
  const headers = { "X-Requested-With": "HealthLens", ...options.headers };
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), path === "/api/chat" ? 100000 : 20000);
  try {
    const response = await fetch(path, { ...options, headers, credentials: "same-origin", signal: controller.signal });
    if (!response.ok) {
      let message = response.status === 502 || response.status === 504
        ? "The private tunnel gateway could not reach the app. Check port 8000 in VS Code's Ports view and keep the backend running."
        : response.status === 404
          ? "This app endpoint was not found. Check the forwarded address and backend version."
          : `Request failed (${response.status})`;
      try {
        const body = await response.json();
        message = typeof body.detail === "string" ? body.detail : "Please check your input values.";
      } catch { /* A tunnel gateway may return HTML rather than an API error. */ }
      if (response.status === 401 && !path.includes("/auth/")) showSignedOut();
      throw new Error(message);
    }
    return response.status === 204 ? null : await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Check the private port forward in VS Code. If registering, check account status before retrying.");
    if (error instanceof TypeError) throw new Error("Could not connect to the app. Check the private tunnel and backend, then reload.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function busy(button, action) {
  button.disabled = true;
  try { await action(); } catch (error) { notify(error.message || "Unexpected error", true); }
  finally { button.disabled = false; }
}

function showSignedOut() {
  signedInUser = "";
  catalog = null;
  $("workspace").hidden = true;
  $("identity").hidden = true;
  $("auth").hidden = false;
  $("auth-password").value = "";
  $("delete-password").value = "";
  $("question").value = "";
  $("report-file").value = "";
  $("confirmed").checked = false;
  $("external-consent").checked = false;
  $("account-status").hidden = true;
  $("account-status").textContent = "";
  ["result", "features", "history-list", "chat-messages", "model-details", "disease-cards"].forEach((id) => $(id).replaceChildren());
}

async function showWorkspace(username) {
  const loaded = await api("/api/catalog");
  signedInUser = username;
  catalog = loaded;
  $("username").textContent = username;
  $("auth-password").value = "";
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("identity").hidden = false;
  const metadata = Object.values(catalog.models);
  $("model-badge").textContent = metadata.some((m) => m.source === "synthetic") ? "SYNTHETIC DEMO / NOT CLINICAL" : "RESEARCH MODELS / NOT VALIDATED";
  const providerName = catalog.external_chat_provider === "nvidia" ? "NVIDIA" : "Azure OpenAI";
  $("external-provider-name").textContent = catalog.external_chat_available ? providerName : "the configured AI provider";
  $("provider-notice").textContent = catalog.external_chat_available ? `${providerName} is configured. Offline by default; external processing requires the checkbox above.` : "No external AI provider is configured. The assistant works offline with reviewed excerpts.";
  $("external-consent").disabled = !catalog.external_chat_available;
  $("disease-cards").replaceChildren();
  catalog.diseases.forEach((item, index) => {
    const button = node("button", undefined, "disease-card");
    button.type = "button";
    button.dataset.disease = item.id;
    button.append(node("small", `MODULE 0${index + 1}`), node("strong", item.name), node("small", `${item.features.length} input measurements`));
    button.addEventListener("click", () => selectDisease(item.id));
    $("disease-cards").append(button);
  });
  selectDisease(disease);
  renderModels();
  selectTab("assessment");
}

function selectDisease(id) {
  disease = id;
  const item = catalog.diseases.find((d) => d.id === id);
  document.querySelectorAll(".disease-card").forEach((card) => {
    const selected = card.dataset.disease === id;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  $("feature-heading").textContent = item.name + " measurements";
  $("features").replaceChildren();
  item.features.forEach((feature) => {
    const wrapper = node("div");
    const label = node("label", feature.label);
    label.htmlFor = "field-" + feature.key;
    const input = node("input");
    Object.assign(input, { id: label.htmlFor, name: feature.key, type: "number", min: feature.min, max: feature.max, step: feature.key === "exercise_angina" ? "1" : "any", required: true });
    wrapper.append(label, input, node("small", `${feature.unit} / range ${feature.min}-${feature.max}`));
    $("features").append(wrapper);
  });
  $("confirmed").checked = false;
  $("report-file").value = "";
  $("result").hidden = true;
  $("result").replaceChildren();
  $("result-empty").hidden = false;
  $("assess-submit").disabled = !catalog.models[id];
  if (!catalog.models[id]) notify("This model is missing. Run the training command and restart the app.", true);
}

function renderSources(parent, sources) {
  sources.forEach((source, i) => {
    const block = node("div", undefined, "source");
    const link = node("a", `[${i + 1}] ${source.title}`);
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    block.append(node("p", source.text), link);
    parent.append(block);
  });
}

function renderResult(item) {
  $("result-empty").hidden = true;
  $("result").hidden = false;
  const result = item.result;
  const title = catalog.diseases.find((d) => d.id === result.disease).name;
  const root = $("result");
  root.replaceChildren(node("h2", title + " / research output"));
  const score = node("div", result.model_score.toFixed(4), "score");
  score.append(node("small", "model score"));
  root.append(score, node("p", `Experimental class ${result.predicted_class} at threshold ${result.threshold}.`), node("div", `${result.model_source === "synthetic" ? "SYNTHETIC DEMO. " : "UNVALIDATED RESEARCH MODEL. "}This score is not a clinical probability. Do not interpret it as your chance of disease.`, "notice"), node("p", "Suggested discussion topics: review the input measurements, any symptoms, and whether clinical testing is appropriate."));
  renderSources(root, item.guidance);
  root.append(node("p", item.disclaimer, "muted"));
  const link = node("a", "Download PDF report", "download");
  link.href = `/api/assessments/${item.id}/report`;
  root.append(link);
}

async function loadHistory(append = false) {
  if (!append) { historyOffset = 0; $("history-list").replaceChildren(); }
  const records = await api(`/api/assessments?offset=${historyOffset}`);
  if (!records.length && !append) $("history-list").append(node("p", "No assessments yet.", "muted"));
  for (const item of records) {
    const row = node("div", undefined, "history-item");
    const name = catalog.diseases.find((d) => d.id === item.result.disease).name;
    row.append(node("strong", name), node("p", `${new Date(item.created).toLocaleString()} / ${item.result.model_source} / score ${item.result.model_score}`, "muted"));
    const view = node("button", "View", "secondary");
    view.addEventListener("click", () => { selectTab("assessment"); renderResult(item); });
    const download = node("a", "PDF report", "download");
    download.href = `/api/assessments/${item.id}/report`;
    const remove = node("button", "Delete", "quiet");
    remove.addEventListener("click", () => busy(remove, async () => {
      if (!confirm("Delete this saved assessment? Downloaded copies are not removed.")) return;
      await api(`/api/assessments/${item.id}`, { method: "DELETE" });
      await loadHistory();
      $("result").replaceChildren();
      $("result").hidden = true;
      $("result-empty").hidden = false;
    }));
    row.append(view, download, remove);
    $("history-list").append(row);
  }
  historyOffset += records.length;
  $("history-more").hidden = records.length < 20;
}

function renderModels() {
  $("model-details").replaceChildren();
  catalog.diseases.forEach((d) => {
    const model = catalog.models[d.id];
    const block = node("div");
    block.append(node("h3", d.name));
    if (!model) { block.append(node("p", "Not trained")); $("model-details").append(block); return; }
    block.append(node("p", `${model.source} / ${model.algorithm} / version ${model.version} / ${model.rows} rows`, "muted"));
    const table = node("table");
    const head = node("tr");
    const values = ["Accuracy", "Precision", "Recall", "F1"];
    values.forEach((v) => head.append(node("th", v)));
    const data = node("tr");
    ["accuracy", "precision", "recall", "f1"].forEach((k) => data.append(node("td", model.metrics[k].toFixed(3))));
    table.append(head, data);
    block.append(table, node("p", `Confusion matrix [true 0, true 1] x [predicted 0, predicted 1]: ${JSON.stringify(model.metrics.confusion_matrix)}`, "muted"));
    block.append(node("p", "Training-only cross-validation F1: " + Object.entries(model.cross_validation_f1).map(([k, v]) => `${k}: ${v.toFixed(3)}`).join("; "), "muted"));
    $("model-details").append(block);
  });
}

function selectTab(name) {
  document.querySelectorAll(".tab-content").forEach((section) => { section.hidden = section.id !== "tab-" + name; });
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
    button.setAttribute("aria-current", button.dataset.tab === name ? "page" : "false");
  });
}

$("auth-toggle").addEventListener("click", () => {
  registering = !registering;
  $("auth-title").textContent = registering ? "Create your research account" : "Sign in to your workspace";
  $("auth-submit").textContent = registering ? "Create account" : "Sign in";
  $("auth-toggle").textContent = registering ? "Already registered? Sign in" : "New here? Create an account";
  $("auth-password").autocomplete = registering ? "new-password" : "current-password";
});
$("auth-user").addEventListener("input", () => {
  $("account-status").hidden = true;
  $("account-status").textContent = "";
});
$("account-check").addEventListener("click", () => busy($("account-check"), async () => {
  if (!$("auth-user").reportValidity()) return;
  const username = $("auth-user").value;
  $("account-status").hidden = false;
  $("account-status").textContent = "Checking account...";
  try {
    const result = await api("/api/auth/account-status", { method: "POST", body: JSON.stringify({ username }) });
    if ($("auth-user").value !== username) return;
    $("account-status").textContent = result.exists
      ? "Account exists. Use Sign in with your password."
      : "No account found for this exact username. Choose Create an account.";
  } catch (error) {
    if ($("auth-user").value === username) $("account-status").textContent = "Account status could not be confirmed. " + error.message;
    throw error;
  }
}));
$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  busy($("auth-submit"), async () => {
    const user = await api(`/api/auth/${registering ? "register" : "login"}`, { method: "POST", body: JSON.stringify({ username: $("auth-user").value, password: $("auth-password").value }) });
    await showWorkspace(user.username);
  });
});
$("logout").addEventListener("click", () => busy($("logout"), async () => {
  await api("/api/auth/logout", { method: "POST" });
  showSignedOut();
}));
document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => {
  selectTab(button.dataset.tab);
  if (button.dataset.tab === "history") busy(button, () => loadHistory());
}));
$("history-more").addEventListener("click", () => busy($("history-more"), () => loadHistory(true)));
$("upload").addEventListener("click", () => busy($("upload"), async () => {
  const file = $("report-file").files[0];
  if (!file) throw new Error("Choose a supported report first.");
  if (file.size > 2 * 1024 * 1024) throw new Error("Maximum upload size is 2 MB.");
  const uploadDisease = disease;
  const form = new FormData();
  form.append("file", file);
  const result = await api(`/api/uploads/extract?disease=${encodeURIComponent(uploadDisease)}`, { method: "POST", body: form });
  if (disease !== uploadDisease) return;
  // Clear missing fields so an older patient's measurements cannot be silently reused.
  document.querySelectorAll("#features input").forEach((input) => { input.value = ""; });
  Object.entries(result.features).forEach(([key, value]) => { $("field-" + key).value = value; });
  $("confirmed").checked = false;
  notify(result.warning + (result.missing.length ? ` Missing: ${result.missing.join(", ")}.` : ""));
}));
$("assessment-form").addEventListener("submit", (event) => {
  event.preventDefault();
  busy($("assess-submit"), async () => {
    const submittedDisease = disease;
    const features = {};
    document.querySelectorAll("#features input").forEach((input) => { features[input.name] = Number(input.value); });
    const result = await api("/api/assessments", { method: "POST", body: JSON.stringify({ disease: submittedDisease, features, confirmed: $("confirmed").checked }) });
    if (disease === submittedDisease) renderResult(result);
  });
});
$("features").addEventListener("input", () => { $("confirmed").checked = false; });
$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  busy(button, async () => {
    const question = $("question").value;
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ question, disease: $("chat-disease").value || null, external_consent: $("external-consent").checked }) });
    const questionBlock = node("div", question, "message question");
    const responseBlock = node("div", result.answer, "message");
    $("chat-messages").append(questionBlock, responseBlock);
    renderSources($("chat-messages"), result.sources);
    $("chat-messages").append(node("p", `${result.provider}${result.model ? " / " + result.model : ""} / ${result.mode}${result.notice ? " / " + result.notice : ""}`, "muted"), node("p", result.disclaimer, "muted"));
    $("question").value = "";
    $("external-consent").checked = false;
  });
});
$("delete-account-form").addEventListener("submit", (event) => {
  event.preventDefault();
  busy(event.currentTarget.querySelector("button"), async () => {
    if (!confirm("Permanently delete your account and every saved assessment?")) return;
    await api("/api/account", { method: "DELETE", body: JSON.stringify({ username: signedInUser, password: $("delete-password").value }) });
    showSignedOut();
    notify("Account and active records deleted. External copies and backups are not removed.");
  });
});
(async () => {
  try {
    const user = await api("/api/auth/me");
    await showWorkspace(user.username);
  } catch (error) {
    showSignedOut();
    if (error.message !== "Please sign in") notify(error.message, true);
  }
})();
