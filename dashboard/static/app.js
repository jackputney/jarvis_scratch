// Jarvis dashboard — vanilla JS, no build step.
// Real-time via SSE (/api/events); poll is fallback on SSE error only.

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

function esc(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}

const POLL_IDLE_MS = 5000;
const POLL_CONFIRM_MS = 500;
let _pollTimer = null;
let _confirmTimer = null;
let _activeConfirmId = null;
let _sseOk = true;

const STATE_LABELS = {
  IDLE: "Idle",
  LISTENING: "Listening",
  THINKING: "Thinking",
  WAITING_CONFIRM: "Waiting for approval",
  SPEAKING: "Speaking",
};

const VIEW_ORDER = ["overview", "activity", "tools", "memory", "plugins", "hub", "settings"];

// ---- Toasts -----------------------------------------------------------
function showToast(message, kind = "info", ms = 3200) {
  const icons = { ok: "✅", err: "⚠️", info: "💡" };
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = `<span class="t-ico">${icons[kind] || "💡"}</span><span>${esc(message)}</span>`;
  $("toast-container").appendChild(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 260);
  }, ms);
}

window.jarvisToast = showToast;

// ---- Activity feed ----------------------------------------------------
function addActivity(icon, text) {
  const feed = $("activity-feed");
  const empty = feed.querySelector(".empty");
  if (empty) empty.remove();
  const entry = document.createElement("div");
  entry.className = "feed-entry";
  const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  entry.innerHTML =
    `<span class="feed-ico">${icon}</span>` +
    `<span class="feed-text">${esc(text)}</span>` +
    `<span class="feed-time">${t}</span>`;
  feed.prepend(entry);
  while (feed.children.length > 30) feed.lastChild.remove();
}

function ensureActivityEmpty() {
  const feed = $("activity-feed");
  if (!feed.children.length) {
    feed.innerHTML = `<div class="feed-entry empty">Waiting for activity…</div>`;
  }
}

// ---- View routing -----------------------------------------------------
function switchView(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.dataset.view === name));
  if (name === "tools" && !_toolsLoaded) loadTools();
  if (name === "plugins") loadPluginsView();
  if (name === "overview") loadOverviewPlugins();
  document.dispatchEvent(new CustomEvent("jarvis:view", { detail: name }));
}

window.jarvisShowView = switchView;

$$(".nav-item").forEach((b) => (b.onclick = () => switchView(b.dataset.view)));

// ---- Memory tabs ------------------------------------------------------
$$(".memory-tab").forEach((tab) => {
  tab.onclick = () => {
    $$(".memory-tab").forEach((t) => t.classList.toggle("active", t === tab));
    $$(".memory-panel").forEach((p) =>
      p.classList.toggle("active", p.dataset.memPanel === tab.dataset.memTab)
    );
  };
});

// ---- Metrics + overview plugins ---------------------------------------
async function loadMetrics() {
  try {
    const m = await getJSON("/api/metrics");
    $("metric-queries").textContent = String(m.queries_today ?? 0);
    $("metric-tools").textContent = String(m.tools_today ?? 0);
    $("metric-uptime").textContent = m.uptime_display || fmtUptime(m.uptime_seconds).replace("up ", "");
  } catch {
    /* transient */
  }
}

async function loadOverviewPlugins() {
  const list = $("overview-plugins-list");
  if (!list) return;
  try {
    const { plugins } = await getJSON("/api/plugins");
    $("metric-plugins").textContent = String(plugins.filter((p) => p.enabled !== false).length);
    list.innerHTML = "";
    if (!plugins.length) {
      list.innerHTML = "<li class='plugin-card empty'>No plugins installed yet.</li>";
      return;
    }
    plugins.slice(0, 5).forEach((p) => {
      const li = document.createElement("li");
      li.className = "plugin-card";
      const m = p.manifest || p;
      li.innerHTML =
        `<strong>${esc(m.name || p.slug)}</strong>` +
        `<span class="sub">${esc(m.description || "")}</span>`;
      list.appendChild(li);
    });
  } catch {
    /* transient */
  }
}

async function loadPluginsView() {
  const list = $("plugins-list");
  if (!list) return;
  const { plugins } = await getJSON("/api/plugins");
  list.innerHTML = "";
  if (!plugins.length) {
    list.innerHTML = "<li class='plugin-card empty'>No plugins installed yet.</li>";
    return;
  }
  plugins.forEach((p) => {
    const li = document.createElement("li");
    li.className = "plugin-card";
    const m = p.manifest || p;
    const trigger = m.trigger || {};
    const hook = trigger.type === "webhook" ? `http://127.0.0.1:7777/hooks/${p.slug || m.name}` : "";
    li.innerHTML =
      `<strong>${esc(m.name || p.slug)}</strong>` +
      `<span class="sub">${esc(m.description || "")}</span>` +
      `<span class="sub">${esc(trigger.type || "manual")}${trigger.schedule ? " · " + esc(trigger.schedule) : ""}</span>` +
      (hook ? `<code class="hook-url">${esc(hook)}</code>` : "");
    list.appendChild(li);
  });
}

// ---- State render -----------------------------------------------------
function applyStateName(name) {
  if (!name) return;
  const dot = $("state-dot");
  dot.className = "status-dot " + name.toLowerCase();
  $("state-label").textContent = STATE_LABELS[name] || name;
  $("sidebar-orb").classList.toggle("is-busy", name !== "IDLE");
  $("dock-stop").classList.toggle("hidden", name !== "THINKING" && name !== "SPEAKING");
}

function renderConfirm(pending) {
  const overlay = $("confirm-overlay");
  if (!pending) {
    overlay.classList.remove("visible");
    _activeConfirmId = null;
    stopConfirmCountdown();
    return;
  }
  _activeConfirmId = pending.id;
  overlay.classList.add("visible");
  $("confirm-tool").textContent = pending.tool;
  $("confirm-inputs").textContent = JSON.stringify(pending.inputs, null, 2);
  const remaining = Math.max(0, Math.ceil(pending.timeout_sec - pending.age_sec));
  $("confirm-timer").textContent = `Auto-deny in ${remaining}s if you do not choose.`;
  startConfirmCountdown();
}

function startConfirmCountdown() {
  stopConfirmCountdown();
  _confirmTimer = setInterval(async () => {
    try {
      const s = await getJSON("/api/state");
      renderConfirm(s.pending_confirm || null);
      if (!s.pending_confirm) stopConfirmCountdown();
    } catch {
      /* transient */
    }
  }, POLL_CONFIRM_MS);
}

function stopConfirmCountdown() {
  if (_confirmTimer) {
    clearInterval(_confirmTimer);
    _confirmTimer = null;
  }
}

async function respondConfirm(allow) {
  if (!_activeConfirmId) return;
  await sendJSON("/api/confirm/respond", "POST", { id: _activeConfirmId, allow });
  $("confirm-overlay").classList.remove("visible");
  _activeConfirmId = null;
  stopConfirmCountdown();
  refresh();
}

$("btn-allow").onclick = () => respondConfirm(true);
$("btn-deny").onclick = () => respondConfirm(false);

function fmtUptime(s) {
  s = Number(s) || 0;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `up ${h}h ${m}m`;
  if (m) return `up ${m}m ${sec}s`;
  return `up ${sec}s`;
}

function updateMuteDisplay(muted) {
  $("mute-label").textContent = muted ? "muted" : "unmuted";
  const ico = $("dock-mute-ico");
  if (ico) {
    ico.className = muted ? "ti ti-volume-off" : "ti ti-volume";
  }
}

function renderState(s) {
  applyStateName(s.pipeline_state);
  updateMuteDisplay(s.muted);
  $("models").textContent = `${s.models.fast} / ${s.models.smart}`;

  const sp = s.spend;
  $("spend-amount").textContent = money(sp.today);
  const pct = Math.min(100, sp.daily_pct);
  const bar = $("spend-bar");
  bar.style.width = pct + "%";
  bar.className = "spend-bar" + (sp.daily_pct >= 100 ? " capped" : sp.daily_pct >= 80 ? " warn" : "");
  $("spend-meta").textContent = `${sp.daily_pct}% of daily budget (${money(sp.today)} / ${money(sp.daily_budget)})`;

  if (sp.daily_pct >= 100) $("state-dot").classList.add("capped");

  renderConfirm(s.pending_confirm || null);

  const rows = s.conversations
    .slice()
    .reverse()
    .map(
      (c) =>
        `<tr><td>${esc(c.heard)}</td><td>${esc(c.response)}</td>` +
        `<td>${esc(c.model)}</td><td class="num">${c.latency_ms}</td>` +
        `<td class="num">${money(c.cost_usd)}</td></tr>`
    )
    .join("");
  const activityBody = $("activity-log-body");
  if (activityBody) activityBody.innerHTML = rows;
  $("log-count").textContent = `${s.conversations.length} exchanges`;
}

// ---- Tools ------------------------------------------------------------
const TOOL_META = {
  open_app: ["🖥️", "System"],
  web_search: ["🌐", "Web"],
  set_variable: ["💾", "Memory"],
  get_variable: ["🔎", "Memory"],
  write_note: ["📝", "Memory"],
  read_note: ["📖", "Memory"],
  get_calendar_events: ["📅", "Calendar"],
  get_todays_schedule: ["🗓️", "Calendar"],
  get_unread_emails: ["📬", "Email"],
  search_emails: ["✉️", "Email"],
  send_email: ["📤", "Email"],
  read_sheet: ["📊", "Sheets"],
  append_row: ["➕", "Sheets"],
  update_cell: ["✏️", "Sheets"],
};

const TIER_LABEL = { read: "read-only", write: "write", high: "high-risk" };
let _tools = [];
let _toolsLoaded = false;
let _toolFilter = "all";
let _activeTool = null;

async function loadTools() {
  try {
    const { tools } = await getJSON("/api/tools");
    _tools = tools;
    _toolsLoaded = true;
    renderTools();
  } catch {
    showToast("Could not load tools", "err");
  }
}

function renderTools() {
  const gallery = $("tools-gallery");
  gallery.innerHTML = "";
  const list = _tools.filter((t) => _toolFilter === "all" || t.tier === _toolFilter);
  list.forEach((tool) => {
    const [icon, cat] = TOOL_META[tool.name] || ["🔧", "Tool"];
    const card = document.createElement("button");
    card.type = "button";
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

$$(".tools-filter .pill").forEach((p) => {
  p.onclick = () => {
    _toolFilter = p.dataset.filter;
    $$(".tools-filter .pill").forEach((x) => x.classList.toggle("active", x === p));
    renderTools();
  };
});

function fieldType(prop) {
  if (prop.type === "integer" || prop.type === "number") return "number";
  if (prop.type === "array") return "array";
  return "string";
}

function openDrawer(tool) {
  _activeTool = tool;
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
  runBtn.onclick = runTool;
  $("tool-drawer").classList.remove("hidden");
  const first = form.querySelector("input, textarea");
  if (first) first.focus();
}

function closeDrawer() {
  $("tool-drawer").classList.add("hidden");
  _activeTool = null;
}

$("drawer-close").onclick = closeDrawer;
$("drawer-cancel").onclick = closeDrawer;
$("drawer-scrim").onclick = closeDrawer;

function collectInputs(tool) {
  const inputs = {};
  const required = (tool.input_schema && tool.input_schema.required) || [];
  const missing = [];
  $$("#tool-form [data-key]").forEach((el) => {
    const key = el.dataset.key;
    const ft = el.dataset.ft;
    const raw = el.value.trim();
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
  if (missing.length) {
    showToast(`Missing required: ${missing.join(", ")}`, "err");
    return;
  }

  const runBtn = $("drawer-run");
  runBtn.textContent = "Running…";
  runBtn.disabled = true;
  try {
    let res = await sendJSON("/api/tools/run", "POST", { name: tool.name, inputs });
    if (res.confirm_required) {
      runBtn.textContent = "⚠️ Confirm run";
      runBtn.className = "danger";
      runBtn.disabled = false;
      showToast("High-risk tool — click again to confirm", "info", 5000);
      runBtn.onclick = async () => {
        runBtn.disabled = true;
        runBtn.textContent = "Running…";
        try {
          res = await sendJSON("/api/tools/run", "POST", {
            name: tool.name,
            inputs,
            confirm_id: res.confirm_id,
            confirmed: true,
          });
          showToolResult(tool, res);
        } catch {
          showToast("Run failed (network)", "err");
        } finally {
          runBtn.textContent = "Run tool";
          runBtn.className = "primary";
          runBtn.disabled = false;
          runBtn.onclick = runTool;
        }
      };
      return;
    }
    showToolResult(tool, res);
  } catch {
    showToast("Run failed (network)", "err");
  } finally {
    if (runBtn.onclick === runTool || !runBtn.onclick) {
      runBtn.textContent = "Run tool";
      runBtn.className = "primary";
      runBtn.disabled = false;
    }
  }
}

function showToolResult(tool, res) {
  const ok = res.ok;
  const result = res.result || res.error || "(no output)";
  $("drawer-result").classList.remove("hidden");
  const status = $("result-status");
  status.textContent = ok ? "✓ Success" : "✗ Failed";
  status.className = ok ? "ok" : "err";
  $("result-body").textContent = result;
  showToast(`${tool.name} ${ok ? "ran" : "failed"}`, ok ? "ok" : "err");
  addActivity(ok ? "🛠️" : "⚠️", `${tool.name} ${ok ? "ran" : "failed"}`);
}

$("drawer-run").onclick = runTool;
$("result-copy").onclick = () => {
  navigator.clipboard.writeText($("result-body").textContent || "").then(() => showToast("Copied result", "ok"));
};

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
  $("set-memory-root").value = c.memory_root_path || "";
  $("set-memory-learn").checked = c.memory_auto_learn !== false;
  $("set-memory-recall").checked = c.memory_semantic_recall !== false;
}

$("save-budget").onclick = async () => {
  await sendJSON("/api/config", "POST", {
    daily_budget_usd: $("daily-budget").value,
    monthly_budget_usd: $("monthly-budget").value,
  });
  showToast("Budgets saved", "ok");
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
    memory_root_path: $("set-memory-root").value.trim(),
    memory_auto_learn: $("set-memory-learn").checked,
    memory_semantic_recall: $("set-memory-recall").checked,
  });
  showToast("Settings saved — applied live", "ok");
};

// ---- Command dock -----------------------------------------------------
async function sendMessage() {
  const input = $("dock-input");
  const text = input.value.trim();
  if (!text) return;
  const reply = $("dock-reply");
  reply.classList.add("show");
  reply.textContent = "…thinking…";
  input.value = "";
  try {
    const r = await sendJSON("/api/message", "POST", { text });
    reply.textContent = r.reply || r.error || "(no reply)";
    addActivity("💬", `${text} → ${(r.reply || "").slice(0, 60)}`);
  } catch {
    reply.textContent = "(network error)";
  }
  refresh();
}

$("dock-send").onclick = sendMessage;
$("dock-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

$("dock-stop").onclick = async () => {
  await sendJSON("/api/interrupt", "POST");
  $("dock-reply").classList.add("show");
  $("dock-reply").textContent = "Stopped.";
  showToast("Interrupted", "info");
};

// ---- Variables --------------------------------------------------------
async function loadVars() {
  const vars = await getJSON("/api/variables");
  const body = $("vars-body");
  body.innerHTML = "";
  const entries = Object.entries(vars);
  entries.forEach(([k, v]) => {
    const tr = document.createElement("tr");
    const tdK = document.createElement("td");
    tdK.textContent = k;
    const tdV = document.createElement("td");
    const inp = document.createElement("input");
    inp.value = v;
    inp.onchange = () => {
      sendJSON("/api/variables", "POST", { key: k, value: inp.value });
      showToast(`Saved ${k}`, "ok");
    };
    tdV.appendChild(inp);
    const tdX = document.createElement("td");
    const del = document.createElement("button");
    del.textContent = "✕";
    del.className = "ghost tiny";
    del.onclick = async () => {
      await fetch("/api/variables/" + encodeURIComponent(k), { method: "DELETE" });
      loadVars();
    };
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
  $("var-key").value = "";
  $("var-value").value = "";
  showToast("Variable added", "ok");
  loadVars();
};

// ---- Notes ------------------------------------------------------------
async function loadNotes() {
  const { notes } = await getJSON("/api/notes");
  const list = $("notes-list");
  list.innerHTML = "";
  notes.forEach((title) => {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.className = "title";
    span.textContent = title;
    span.onclick = async () => {
      const n = await getJSON("/api/notes/" + encodeURIComponent(title));
      $("note-title").value = title;
      $("note-content").value = n.content || "";
    };
    const del = document.createElement("button");
    del.textContent = "✕";
    del.className = "ghost tiny";
    del.onclick = async () => {
      await fetch("/api/notes/" + encodeURIComponent(title), { method: "DELETE" });
      loadNotes();
    };
    li.append(span, del);
    list.appendChild(li);
  });
  $("notes-count").textContent = `${notes.length} notes`;
}

$("note-save").onclick = async () => {
  const title = $("note-title").value.trim();
  if (!title) return;
  await sendJSON("/api/notes", "POST", { title, content: $("note-content").value });
  showToast("Note saved", "ok");
  loadNotes();
};

// ---- Semantic memory --------------------------------------------------
async function loadMemoryInfo() {
  const info = await getJSON("/api/memory/info");
  $("memory-root-path").textContent = info.root;
}

async function searchMemory() {
  const q = $("memory-search-q").value.trim();
  if (!q) return;
  const { hits } = await getJSON("/api/memory/search?q=" + encodeURIComponent(q));
  const list = $("memory-hits");
  list.innerHTML = "";
  if (!hits.length) {
    list.innerHTML = "<li>No matching memories.</li>";
    return;
  }
  hits.forEach((h) => {
    const li = document.createElement("li");
    li.innerHTML = `<div class="hit-src">${esc(h.source)}</div>${esc(h.chunk)}`;
    list.appendChild(li);
  });
}

$("memory-search-btn").onclick = searchMemory;
$("memory-search-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchMemory();
});

$("memory-reindex").onclick = async () => {
  const r = await sendJSON("/api/memory/reindex", "POST");
  showToast(`Reindexed ${r.chunks} chunks`, "ok");
};

// ---- Poll fallback (SSE error only) -----------------------------------
function startPollFallback() {
  if (_pollTimer) return;
  _pollTimer = setInterval(refresh, POLL_IDLE_MS);
}

function stopPollFallback() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

async function refresh() {
  try {
    renderState(await getJSON("/api/state"));
  } catch {
    /* transient */
  }
}

// ---- SSE --------------------------------------------------------------
let _events = null;

function sseEventName(data) {
  return data.event || data.type || "";
}

function handleSSE(data) {
  const evt = sseEventName(data);
  switch (evt) {
    case "pipeline.state":
    case "state":
      applyStateName(data.state || data.pipeline_state);
      if ((data.state || data.pipeline_state) === "WAITING_CONFIRM") refresh();
      if (data.muted != null) updateMuteDisplay(data.muted);
      break;
    case "job.transcript":
      if (data.heard) addActivity("💬", `${data.heard} → ${(data.reply || "").slice(0, 60)}`);
      refresh();
      break;
    case "tool.run":
      addActivity(data.ok ? "🛠️" : "⚠️", `${data.name} (voice) ${data.ok ? "ran" : "failed"}`);
      loadMetrics();
      break;
    case "confirm.pending":
    case "confirm":
      renderConfirm(data);
      break;
    case "job.state":
      refresh();
      break;
    default:
      break;
  }
}

function connectEvents() {
  if (_events) _events.close();
  _events = new EventSource("/api/events");
  _events.onopen = () => {
    _sseOk = true;
    stopPollFallback();
  };
  _events.onmessage = (e) => {
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      return;
    }
    handleSSE(data);
  };
  _events.onerror = () => {
    if (_sseOk) {
      _sseOk = false;
      startPollFallback();
    }
  };
}

// ---- Keyboard shortcuts -------------------------------------------------
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!$("tool-drawer").classList.contains("hidden")) closeDrawer();
    if ($("confirm-overlay").classList.contains("visible")) {
      /* keep confirm open — user must choose */
    }
    return;
  }

  if (e.metaKey || e.ctrlKey) {
    if (e.key.toLowerCase() === "k") {
      e.preventDefault();
      $("dock-input").focus();
      return;
    }
    const num = parseInt(e.key, 10);
    if (num >= 1 && num <= 7) {
      e.preventDefault();
      switchView(VIEW_ORDER[num - 1]);
    }
  }
});

// ---- Init -------------------------------------------------------------
(async function init() {
  ensureActivityEmpty();
  await loadConfig();
  await Promise.all([loadVars(), loadNotes(), loadMemoryInfo(), loadMetrics(), loadOverviewPlugins(), refresh()]);
  connectEvents();
})();
