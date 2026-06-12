// Jarvis dashboard — vanilla JS, polls /api/state every 2s. No build step.

const $ = (id) => document.getElementById(id);

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

function fmtUptime(s) {
  s = Number(s) || 0;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `up ${h}h ${m}m`;
  if (m) return `up ${m}m ${sec}s`;
  return `up ${sec}s`;
}

function renderState(s) {
  const dot = $("state-dot");
  dot.className = "dot " + s.pipeline_state.toLowerCase();
  $("state-label").textContent = s.pipeline_state;
  $("mute-label").textContent = s.muted ? "muted" : "unmuted";
  $("uptime").textContent = fmtUptime(s.uptime_seconds);
  $("models").textContent = `${s.models.fast} / ${s.models.smart}`;

  // Spend
  const sp = s.spend;
  $("spend-today").textContent = money(sp.today);
  $("spend-week").textContent = money(sp.week);
  $("spend-month").textContent = money(sp.month);
  const pct = Math.min(100, sp.daily_pct);
  const bar = $("budget-bar");
  bar.style.width = pct + "%";
  bar.className = "bar" + (sp.daily_pct >= 100 ? " capped" : sp.daily_pct >= 80 ? " warn" : "");
  $("budget-caption").textContent =
    `${sp.daily_pct}% of daily budget (${money(sp.today)} / ${money(sp.daily_budget)})`;
  if (sp.daily_pct >= 100) dot.classList.add("capped");

  // Log
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
}

function esc(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}

// ---- Budgets + settings -----------------------------------------------
let settingsLoaded = false;
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
  settingsLoaded = true;
}

$("save-budget").onclick = async () => {
  await sendJSON("/api/config", "POST", {
    daily_budget_usd: $("daily-budget").value,
    monthly_budget_usd: $("monthly-budget").value,
  });
  flash($("save-budget"));
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
  flash($("save-settings"));
};

function flash(btn) {
  const t = btn.textContent;
  btn.textContent = "Saved ✓";
  setTimeout(() => (btn.textContent = t), 1200);
}

// ---- Talk -------------------------------------------------------------
async function sendMessage() {
  const input = $("talk-input");
  const text = input.value.trim();
  if (!text) return;
  $("talk-reply").textContent = "…thinking…";
  input.value = "";
  const r = await sendJSON("/api/message", "POST", { text });
  $("talk-reply").textContent = r.reply || r.error || "(no reply)";
  refresh();
}
$("talk-send").onclick = sendMessage;
$("talk-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
$("talk-stop").onclick = async () => {
  await sendJSON("/api/interrupt", "POST");
  $("talk-reply").textContent = "Stopped.";
};

// ---- Variables --------------------------------------------------------
async function loadVars() {
  const vars = await getJSON("/api/variables");
  const body = $("vars-body");
  body.innerHTML = "";
  Object.entries(vars).forEach(([k, v]) => {
    const tr = document.createElement("tr");
    const tdK = document.createElement("td");
    tdK.textContent = k;
    const tdV = document.createElement("td");
    const inp = document.createElement("input");
    inp.value = v;
    inp.onchange = () => sendJSON("/api/variables", "POST", { key: k, value: inp.value });
    tdV.appendChild(inp);
    const tdX = document.createElement("td");
    const del = document.createElement("button");
    del.textContent = "✕";
    del.className = "ghost";
    del.onclick = async () => { await fetch("/api/variables/" + encodeURIComponent(k), { method: "DELETE" }); loadVars(); };
    tdX.appendChild(del);
    tr.append(tdK, tdV, tdX);
    body.appendChild(tr);
  });
}
$("var-add").onclick = async () => {
  const key = $("var-key").value.trim();
  if (!key) return;
  await sendJSON("/api/variables", "POST", { key, value: $("var-value").value });
  $("var-key").value = ""; $("var-value").value = "";
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
    del.className = "ghost";
    del.onclick = async () => { await fetch("/api/notes/" + encodeURIComponent(title), { method: "DELETE" }); loadNotes(); };
    li.append(span, del);
    list.appendChild(li);
  });
}
$("note-save").onclick = async () => {
  const title = $("note-title").value.trim();
  if (!title) return;
  await sendJSON("/api/notes", "POST", { title, content: $("note-content").value });
  loadNotes();
};

// ---- Poll loop --------------------------------------------------------
async function refresh() {
  try {
    const s = await getJSON("/api/state");
    renderState(s);
  } catch (e) { /* ignore transient errors */ }
}

(async function init() {
  await loadConfig();
  await Promise.all([loadVars(), loadNotes(), refresh()]);
  setInterval(refresh, 2000);
})();
