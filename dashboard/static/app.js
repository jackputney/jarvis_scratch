// Jarvis dashboard — vanilla JS, no build step.
// Real-time via SSE (/api/events); slow poll is the fallback.

const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}
async function sendJSON(url, method, body) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}
const money = (n) => "$" + (Number(n) || 0).toFixed(2);
function esc(t) { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }

const POLL_IDLE_MS = 5000;
const POLL_CONFIRM_MS = 500;
let _pollMs = POLL_IDLE_MS;
let _pollTimer = null;
let _activeConfirmId = null;

const STATE_LABELS = {
  IDLE: "Idle", LISTENING: "Listening", THINKING: "Thinking",
  WAITING_CONFIRM: "Waiting for approval", SPEAKING: "Speaking",
};

// ---- Toasts -----------------------------------------------------------
function toast(message, kind = "info", ms = 3200) {
  const icons = { ok: "✅", err: "⚠️", info: "💡" };
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = `<span class="t-ico">${icons[kind] || "💡"}</span><span>${esc(message)}</span>`;
  $("toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 260); }, ms);
}

// ---- Activity feed ----------------------------------------------------
function addActivity(icon, text) {
  const feed = $("activity-feed");
  const empty = feed.querySelector(".empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  li.innerHTML = `<span class="a-ico">${icon}</span><span>${esc(text)}</span><span class="a-time">${t}</span>`;
  feed.prepend(li);
  while (feed.children.length > 30) feed.lastChild.remove();
}
function ensureActivityEmpty() {
  const feed = $("activity-feed");
  if (!feed.children.length) feed.innerHTML = `<li class="empty">Waiting for activity…</li>`;
}

// ---- View routing -----------------------------------------------------
function showView(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === name));
  if (name === "tools" && !_toolsLoaded) loadTools();
  document.dispatchEvent(new CustomEvent("jarvis:view", { detail: name }));
}
window.jarvisShowView = showView;
$$(".nav-item").forEach((b) => (b.onclick = () => showView(b.dataset.view)));

// ---- State render -----------------------------------------------------
function applyStateName(name) {
  if (!name) return;
  $("state-dot").className = "dot " + name.toLowerCase();
  $("state-label").textContent = STATE_LABELS[name] || name;
  const busy = name && name !== "IDLE";
  $("logo-orb").classList.toggle("is-busy", busy);
}

function renderConfirm(pending) {
  const overlay = $("confirm-overlay");
  if (!pending) {
    overlay.classList.add("hidden");
    _activeConfirmId = null;
    _pollMs = POLL_IDLE_MS;
    return;
  }
  _pollMs = POLL_CONFIRM_MS;
  _activeConfirmId = pending.id;
  overlay.classList.remove("hidden");
  $("confirm-tool").textContent = pending.tool;
  $("confirm-inputs").textContent = JSON.stringify(pending.inputs, null, 2);
  const remaining = Math.max(0, Math.ceil(pending.timeout_sec - pending.age_sec));
  $("confirm-timer").textContent = `Auto-deny in ${remaining}s if you don't choose.`;
}
async function respondConfirm(allow) {
  if (!_activeConfirmId) return;
  await sendJSON("/api/confirm/respond", "POST", { id: _activeConfirmId, allow });
  $("confirm-overlay").classList.add("hidden");
  _activeConfirmId = null;
  refresh();
}
$("confirm-allow").onclick = () => respondConfirm(true);
$("confirm-deny").onclick = () => respondConfirm(false);

function fmtUptime(s) {
  s = Number(s) || 0;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `up ${h}h ${m}m`;
  if (m) return `up ${m}m ${sec}s`;
  return `up ${sec}s`;
}

function renderState(s) {
  applyStateName(s.pipeline_state);
  $("mute-label").textContent = s.muted ? "muted" : "unmuted";
  $("uptime").textContent = fmtUptime(s.uptime_seconds);
  $("side-uptime").textContent = fmtUptime(s.uptime_seconds).replace("up ", "");
  $("models").textContent = `${s.models.fast} / ${s.models.smart}`;

  const sp = s.spend;
  $("spend-today").textContent = money(sp.today);
  $("spend-week").textContent = money(sp.week);
  $("spend-month").textContent = money(sp.month);
  $("side-spend-today").textContent = money(sp.today);
  const pct = Math.min(100, sp.daily_pct);
  const bar = $("budget-bar");
  bar.style.width = pct + "%";
  bar.className = "bar" + (sp.daily_pct >= 100 ? " capped" : sp.daily_pct >= 80 ? " warn" : "");
  $("budget-caption").textContent = `${sp.daily_pct}% of daily budget (${money(sp.today)} / ${money(sp.daily_budget)})`;
  const tag = $("budget-state-tag");
  tag.textContent = sp.daily_pct >= 100 ? "capped" : sp.daily_pct >= 80 ? "80% used" : "healthy";
  if (sp.daily_pct >= 100) $("state-dot").classList.add("capped");

  renderConfirm(s.pending_confirm || null);

  const body = $("log-body");
  body.innerHTML = "";
  s.conversations.slice().reverse().forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(c.heard)}</td><td>${esc(c.response)}</td>` +
      `<td>${esc(c.model)}</td><td class="num">${c.latency_ms}</td>` +
      `<td class="num">${money(c.cost_usd)}</td>`;
    body.appendChild(tr);
  });
  $("log-count").textContent = `${s.conversations.length} exchanges`;
}

// ---- Tools ------------------------------------------------------------
const TOOL_META = {
  open_app: ["🖥️", "System"], web_search: ["🌐", "Web"],
  set_variable: ["💾", "Memory"], get_variable: ["🔎", "Memory"],
  write_note: ["📝", "Memory"], read_note: ["📖", "Memory"],
  get_calendar_events: ["📅", "Calendar"], get_todays_schedule: ["🗓️", "Calendar"],
  get_unread_emails: ["📬", "Email"], search_emails: ["✉️", "Email"], send_email: ["📤", "Email"],
  read_sheet: ["📊", "Sheets"], append_row: ["➕", "Sheets"], update_cell: ["✏️", "Sheets"],
};
const TIER_LABEL = { read: "read-only", write: "write", high: "high-risk" };
let _tools = [];
let _toolsLoaded = false;
let _toolFilter = "all";
let _activeTool = null;
let _armed = false;

async function loadTools() {
  try {
    const { tools } = await getJSON("/api/tools");
    _tools = tools;
    _toolsLoaded = true;
    renderTools();
  } catch (e) { toast("Couldn't load tools", "err"); }
}

function renderTools() {
  const gallery = $("tools-gallery");
  gallery.innerHTML = "";
  const list = _tools.filter((t) => _toolFilter === "all" || t.tier === _toolFilter);
  list.forEach((tool) => {
    const [icon, cat] = TOOL_META[tool.name] || ["🔧", "Tool"];
    const card = document.createElement("button");
    card.className = "tool-card";
    card.innerHTML =
      `<div class="tc-top"><span class="tc-ico">${icon}</span><span class="tool-badge ${tool.tier}">${TIER_LABEL[tool.tier]}</span></div>` +
      `<div class="tc-name">${esc(tool.name)}</div>` +
      `<div class="tc-desc">${esc(tool.description)}</div>` +
      `<div class="card-sub">${cat}</div>`;
    card.onclick = () => openDrawer(tool);
    gallery.appendChild(card);
  });
  if (!list.length) gallery.innerHTML = `<p class="sub">No tools in this category.</p>`;
}
$$(".tools-filter .pill").forEach((p) => (p.onclick = () => {
  _toolFilter = p.dataset.filter;
  $$(".tools-filter .pill").forEach((x) => x.classList.toggle("active", x === p));
  renderTools();
}));

function fieldType(prop) {
  if (prop.type === "integer" || prop.type === "number") return "number";
  if (prop.type === "array") return "array";
  return "string";
}

function openDrawer(tool) {
  _activeTool = tool;
  _armed = false;
  $("drawer-title").textContent = tool.name;
  $("drawer-desc").textContent = tool.description;
  const badge = $("drawer-badge");
  badge.className = "tool-badge " + tool.tier;
  badge.textContent = TIER_LABEL[tool.tier];

  const form = $("tool-form");
  form.innerHTML = "";
  const props = (tool.input_schema && tool.input_schema.properties) || {};
  const required = (tool.input_schema && tool.input_schema.required) || [];
  if (!Object.keys(props).length) {
    form.innerHTML = `<p class="sub">This tool takes no inputs.</p>`;
  }
  Object.entries(props).forEach(([key, prop]) => {
    const ft = fieldType(prop);
    const isReq = required.includes(key);
    const wrap = document.createElement("div");
    wrap.className = "field";
    const longText = key === "body" || key === "content";
    const placeholder = ft === "array" ? "comma, separated, values" : "";
    const control = longText
      ? `<textarea data-key="${key}" data-ft="${ft}" placeholder="${placeholder}"></textarea>`
      : `<input data-key="${key}" data-ft="${ft}" type="${ft === "number" ? "number" : "text"}" placeholder="${placeholder}" />`;
    wrap.innerHTML =
      `<label>${esc(key)}${isReq ? '<span class="req">*</span>' : ""}</label>` +
      (prop.description ? `<span class="desc">${esc(prop.description)}</span>` : "") +
      control;
    form.appendChild(wrap);
  });

  $("drawer-result").classList.add("hidden");
  $("result-body").textContent = "";
  const runBtn = $("drawer-run");
  runBtn.textContent = "Run tool";
  runBtn.className = "primary";
  $("tool-drawer").classList.remove("hidden");
  const first = form.querySelector("input, textarea");
  if (first) first.focus();
}
function closeDrawer() { $("tool-drawer").classList.add("hidden"); _activeTool = null; }
$("drawer-close").onclick = closeDrawer;
$("drawer-cancel").onclick = closeDrawer;
$("drawer-scrim").onclick = closeDrawer;

function collectInputs(tool) {
  const inputs = {};
  const required = (tool.input_schema && tool.input_schema.required) || [];
  const missing = [];
  $$("#tool-form [data-key]").forEach((el) => {
    const key = el.dataset.key, ft = el.dataset.ft;
    let raw = el.value.trim();
    if (raw === "") {
      if (required.includes(key)) missing.push(key);
      return;
    }
    if (ft === "number") inputs[key] = Number(raw);
    else if (ft === "array") inputs[key] = raw.split(",").map((v) => v.trim()).filter(Boolean);
    else inputs[key] = raw;
  });
  return { inputs, missing };
}

async function runTool() {
  if (!_activeTool) return;
  const tool = _activeTool;
  const { inputs, missing } = collectInputs(tool);
  if (missing.length) { toast(`Missing required: ${missing.join(", ")}`, "err"); return; }

  const runBtn = $("drawer-run");
  // High-risk tools require a second, deliberate click.
  if (tool.tier === "high" && !_armed) {
    _armed = true;
    runBtn.textContent = "⚠️ Click again to run for real";
    runBtn.className = "danger";
    setTimeout(() => { if (_armed) { _armed = false; runBtn.textContent = "Run tool"; runBtn.className = "primary"; } }, 4000);
    return;
  }
  _armed = false;
  runBtn.textContent = "Running…";
  runBtn.disabled = true;
  try {
    const res = await sendJSON("/api/tools/run", "POST", { name: tool.name, inputs });
    const ok = res.ok;
    const result = res.result || res.error || "(no output)";
    $("drawer-result").classList.remove("hidden");
    const status = $("result-status");
    status.textContent = ok ? "✓ Success" : "✗ Failed";
    status.className = ok ? "ok" : "err";
    $("result-body").textContent = result;
    toast(`${tool.name} ${ok ? "ran" : "failed"}`, ok ? "ok" : "err");
    addActivity(ok ? "🛠️" : "⚠️", `${tool.name} ${ok ? "ran" : "failed"}`);
  } catch (e) {
    toast("Run failed (network)", "err");
  } finally {
    runBtn.textContent = tool.tier === "high" ? "Run tool" : "Run tool";
    runBtn.className = "primary";
    runBtn.disabled = false;
  }
}
$("drawer-run").onclick = runTool;
$("result-copy").onclick = () => {
  navigator.clipboard.writeText($("result-body").textContent || "").then(() => toast("Copied result", "ok"));
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("tool-drawer").classList.contains("hidden")) closeDrawer(); });

// ---- Budgets + settings -----------------------------------------------
async function loadConfig() {
  const c = await getJSON("/api/config");
  $("daily-budget").value = c.daily_budget_usd;
  $("monthly-budget").value = c.monthly_budget_usd;
  $("set-wake-enabled").checked = c.wake_word_enabled;
  $("set-confirm").checked = c.confirm_before_execute;
  $("set-whisper").value = c.whisper_model;
  $("set-fast").value = c.claude_model_fast;
  $("set-smart").value = c.claude_model_smart;
  $("set-threshold").value = c.routing_word_threshold;
  $("set-wakeword").value = c.wake_word;
  $("set-voice").value = c.cartesia_voice_id;
}
$("save-budget").onclick = async () => {
  await sendJSON("/api/config", "POST", {
    daily_budget_usd: $("daily-budget").value,
    monthly_budget_usd: $("monthly-budget").value,
  });
  toast("Budgets saved", "ok");
  refresh();
};
$("save-settings").onclick = async () => {
  await sendJSON("/api/config", "POST", {
    wake_word_enabled: $("set-wake-enabled").checked,
    confirm_before_execute: $("set-confirm").checked,
    whisper_model: $("set-whisper").value,
    claude_model_fast: $("set-fast").value,
    claude_model_smart: $("set-smart").value,
    routing_word_threshold: $("set-threshold").value,
    wake_word: $("set-wakeword").value,
    cartesia_voice_id: $("set-voice").value,
  });
  toast("Settings saved — applied live", "ok");
};

// ---- Talk dock --------------------------------------------------------
async function sendMessage() {
  const input = $("talk-input");
  const text = input.value.trim();
  if (!text) return;
  const reply = $("talk-reply");
  reply.classList.add("show");
  reply.textContent = "…thinking…";
  input.value = "";
  try {
    const r = await sendJSON("/api/message", "POST", { text });
    reply.textContent = r.reply || r.error || "(no reply)";
    addActivity("💬", `${text} → ${(r.reply || "").slice(0, 60)}`);
  } catch (e) { reply.textContent = "(network error)"; }
  refresh();
}
$("talk-send").onclick = sendMessage;
$("talk-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
$("talk-stop").onclick = async () => {
  await sendJSON("/api/interrupt", "POST");
  $("talk-reply").classList.add("show");
  $("talk-reply").textContent = "Stopped.";
  toast("Interrupted", "info");
};

// ---- Variables --------------------------------------------------------
async function loadVars() {
  const vars = await getJSON("/api/variables");
  const body = $("vars-body");
  body.innerHTML = "";
  const entries = Object.entries(vars);
  entries.forEach(([k, v]) => {
    const tr = document.createElement("tr");
    const tdK = document.createElement("td"); tdK.textContent = k;
    const tdV = document.createElement("td");
    const inp = document.createElement("input"); inp.value = v;
    inp.onchange = () => { sendJSON("/api/variables", "POST", { key: k, value: inp.value }); toast(`Saved ${k}`, "ok"); };
    tdV.appendChild(inp);
    const tdX = document.createElement("td");
    const del = document.createElement("button"); del.textContent = "✕"; del.className = "ghost tiny";
    del.onclick = async () => { await fetch("/api/variables/" + encodeURIComponent(k), { method: "DELETE" }); loadVars(); };
    tdX.appendChild(del);
    tr.append(tdK, tdV, tdX);
    body.appendChild(tr);
  });
  $("vars-count").textContent = `${entries.length} stored`;
}
$("var-add").onclick = async () => {
  const key = $("var-key").value.trim();
  if (!key) return;
  await sendJSON("/api/variables", "POST", { key, value: $("var-value").value });
  $("var-key").value = ""; $("var-value").value = "";
  toast("Variable added", "ok");
  loadVars();
};

// ---- Notes ------------------------------------------------------------
async function loadNotes() {
  const { notes } = await getJSON("/api/notes");
  const list = $("notes-list");
  list.innerHTML = "";
  notes.forEach((title) => {
    const li = document.createElement("li");
    const span = document.createElement("span"); span.className = "title"; span.textContent = title;
    span.onclick = async () => {
      const n = await getJSON("/api/notes/" + encodeURIComponent(title));
      $("note-title").value = title; $("note-content").value = n.content || "";
    };
    const del = document.createElement("button"); del.textContent = "✕"; del.className = "ghost tiny";
    del.onclick = async () => { await fetch("/api/notes/" + encodeURIComponent(title), { method: "DELETE" }); loadNotes(); };
    li.append(span, del);
    list.appendChild(li);
  });
  $("notes-count").textContent = `${notes.length} notes`;
}
$("note-save").onclick = async () => {
  const title = $("note-title").value.trim();
  if (!title) return;
  await sendJSON("/api/notes", "POST", { title, content: $("note-content").value });
  toast("Note saved", "ok");
  loadNotes();
};

// ---- Poll + SSE -------------------------------------------------------
function schedulePoll() {
  if (_pollTimer) clearTimeout(_pollTimer);
  _pollTimer = setTimeout(async () => { await refresh(); schedulePoll(); }, _pollMs);
}
async function refresh() {
  try { renderState(await getJSON("/api/state")); } catch (e) { /* transient */ }
}

let _events = null;
function connectEvents() {
  if (_events) _events.close();
  _events = new EventSource("/api/events");
  _events.onmessage = (e) => {
    let data; try { data = JSON.parse(e.data); } catch { return; }
    switch (data.event) {
      case "pipeline.state":
        applyStateName(data.state);
        if (data.state === "WAITING_CONFIRM") refresh();
        break;
      case "job.transcript":
        if (data.heard) addActivity("💬", `${data.heard} → ${(data.reply || "").slice(0, 60)}`);
        refresh();
        break;
      case "tool.run":
        addActivity(data.ok ? "🛠️" : "⚠️", `${data.name} (voice) ${data.ok ? "ran" : "failed"}`);
        break;
      case "job.state":
        refresh();
        break;
    }
  };
  _events.onerror = () => { /* auto-reconnects; poll covers gaps */ };
}

(async function init() {
  ensureActivityEmpty();
  await loadConfig();
  await Promise.all([loadVars(), loadNotes(), refresh()]);
  connectEvents();
  schedulePoll();
})();
