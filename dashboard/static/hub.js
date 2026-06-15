// Jarvis Hub — integrations, connections, plugins, health (data-driven from API).

const hub$ = (id) => document.getElementById(id);
const hub$$ = (sel) => Array.from(document.querySelectorAll(sel));

async function hubGet(url) {
  const r = await fetch(url);
  return r.json();
}
async function hubPost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  return { ok: r.ok, status: r.status, data };
}
function hubEsc(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}
function hubToast(msg, kind = "info") {
  if (typeof window.jarvisToast === "function") return window.jarvisToast(msg, kind);
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  hub$("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

let _integrations = [];
let _pendingManifest = null;
let _healthTimer = null;

function showHubTab(name) {
  hub$$(".hub-tab").forEach((t) => t.classList.toggle("active", t.dataset.hubTab === name));
  hub$$(".hub-panel").forEach((p) => p.classList.toggle("active", p.dataset.hubPanel === name));
  if (name === "health") startHealthPoll();
  else stopHealthPoll();
}

function openConnectionsFor(id) {
  if (typeof window.jarvisShowView === "function") window.jarvisShowView("hub");
  showHubTab("connections");
  const el = hub$(`conn-${id}`);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.add("highlight");
    setTimeout(() => el.classList.remove("highlight"), 1800);
  }
}

async function loadIntegrations() {
  _integrations = await hubGet("/api/hub/integrations");
  renderSetupGrid();
  renderConnections();
}

function renderSetupGrid() {
  const grid = hub$("hub-setup-grid");
  grid.innerHTML = "";
  _integrations.forEach((item) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "hub-int-card color-" + (item.color || "gray");
    card.innerHTML =
      `<div class="hub-int-top"><i class="${hubEsc(item.icon || "ti-plug")}"></i>` +
      `<span class="status-dot ${item.connected ? "on" : "off"}"></span></div>` +
      `<div class="hub-int-name">${hubEsc(item.name)}</div>` +
      `<div class="hub-int-desc">${hubEsc(item.description)}</div>` +
      `<div class="hub-int-label">${hubEsc(item.label || (item.connected ? "Connected" : "Not connected"))}</div>`;
    card.onclick = () => {
      if (item.connected) return;
      openConnectionsFor(item.id);
    };
    grid.appendChild(card);
  });
}

function renderConnections() {
  const list = hub$("hub-connections-list");
  list.innerHTML = "";
  _integrations.forEach((item) => {
    const section = document.createElement("section");
    section.className = "hub-conn card";
    section.id = `conn-${item.id}`;

    let body = "";
    if (item.auth_type === "oauth") {
      body =
        `<p class="sub">${hubEsc(item.description)}</p>` +
        `<p class="conn-status">${item.connected ? "✅ Connected" : "⚪ Not connected"}</p>` +
        `<button type="button" class="primary oauth-btn" data-id="${hubEsc(item.id)}">Connect with Google</button>` +
        `<p class="oauth-msg hidden" id="oauth-msg-${hubEsc(item.id)}"></p>`;
    } else {
      const fields = (item.fields || []).map((f) => {
        const type = f.secret ? "password" : "text";
        const req = f.required ? '<span class="req">*</span>' : "";
        return (
          `<label class="field"><span>${hubEsc(f.label)}${req}</span>` +
          `<input type="${type}" data-key="${hubEsc(f.key)}" placeholder="${hubEsc(f.placeholder || "")}" autocomplete="off" />` +
          `</label>`
        );
      }).join("");
      body =
        `<p class="sub">${hubEsc(item.description)}</p>` +
        `<form class="conn-form" data-id="${hubEsc(item.id)}">${fields}</form>` +
        `<div class="conn-actions">` +
        (item.docs_url ? `<a class="docs-link" href="${hubEsc(item.docs_url)}" target="_blank" rel="noopener">Get credentials ↗</a>` : "") +
        `<button type="button" class="primary save-keys" data-id="${hubEsc(item.id)}">Save</button>` +
        `</div>`;
    }

    section.innerHTML =
      `<div class="hub-conn-head">` +
      `<i class="${hubEsc(item.icon || "ti-plug")}"></i>` +
      `<div><h3>${hubEsc(item.name)}</h3><span class="conn-badge ${item.connected ? "on" : "off"}">${hubEsc(item.label)}</span></div>` +
      `</div>${body}`;
    list.appendChild(section);
  });

  hub$$(".save-keys").forEach((btn) => (btn.onclick = () => saveIntegrationKeys(btn.dataset.id)));
  hub$$(".oauth-btn").forEach((btn) => (btn.onclick = () => startGoogleAuth(btn.dataset.id)));
}

async function saveIntegrationKeys(integrationId) {
  const form = hub$(`conn-${integrationId}`)?.querySelector(".conn-form");
  if (!form) return;
  const fields = {};
  hub$$("input[data-key]", form).forEach((inp) => {
    if (inp.value.trim()) fields[inp.dataset.key] = inp.value.trim();
  });
  const { ok, data } = await hubPost("/api/hub/keys", { integration_id: integrationId, fields });
  if (ok && data.ok) {
    hubToast("Credentials saved", "ok");
    await loadIntegrations();
  } else {
    hubToast(data.error || "Save failed", "err");
  }
}

async function startGoogleAuth(integrationId) {
  const msg = hub$(`oauth-msg-${integrationId}`);
  if (msg) { msg.classList.remove("hidden"); msg.textContent = "Opening browser…"; }
  const { ok, data } = await hubPost("/api/hub/google/auth", {});
  if (msg) msg.textContent = data.message || data.error || (ok ? "Started" : "Failed");
  hubToast(data.message || "Google sign-in started", ok ? "ok" : "err");
}

async function loadPlugins() {
  const { plugins } = await hubGet("/api/plugins");
  const list = hub$("hub-plugins-list");
  list.innerHTML = "";
  if (!plugins.length) {
    list.innerHTML = `<p class="sub">No plugins yet — describe an automation below to generate one.</p>`;
    return;
  }
  plugins.forEach((p) => {
    const row = document.createElement("div");
    row.className = "plugin-row card";
    const m = p.manifest || {};
    row.innerHTML =
      `<div class="plugin-info"><strong>${hubEsc(m.name || p.slug)}</strong>` +
      `<span class="sub">${hubEsc(m.description || "")}</span></div>` +
      `<label class="toggle"><input type="checkbox" class="plugin-toggle" data-slug="${hubEsc(p.slug)}" ${p.enabled ? "checked" : ""} /> Enabled</label>`;
    list.appendChild(row);
  });
  hub$$(".plugin-toggle").forEach((cb) => (cb.onchange = () => togglePlugin(cb.dataset.slug, cb.checked)));
}

async function togglePlugin(slug, enabled) {
  const { ok, data } = await hubPost("/api/hub/plugins/toggle", { slug, enabled });
  if (!ok || !data.ok) hubToast(data.error || "Toggle failed", "err");
  else hubToast(`${slug} ${enabled ? "enabled" : "disabled"}`, "ok");
}

async function generatePlugin() {
  const desc = hub$("hub-plugin-desc").value.trim();
  if (!desc) return;
  const btn = hub$("hub-plugin-generate");
  btn.textContent = "Generating…";
  btn.disabled = true;
  const preview = hub$("hub-plugin-preview");
  preview.classList.add("hidden");
  try {
    const r = await fetch("/api/hub/plugins/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: desc }),
    });
    const data = await r.json();
    if (!r.ok) {
      hubToast(data.error || "Generation failed", "err");
      if (data.raw) {
        preview.classList.remove("hidden");
        preview.innerHTML = `<pre>${hubEsc(data.raw)}</pre>`;
      }
      return;
    }
    _pendingManifest = data;
    preview.classList.remove("hidden");
    preview.innerHTML =
      `<h4>Preview — ${hubEsc(data.path)}</h4>` +
      `<pre>${hubEsc(JSON.stringify(data.manifest, null, 2))}</pre>` +
      `<div class="preview-actions">` +
      `<button type="button" class="ghost" id="hub-plugin-discard">Discard</button>` +
      `<button type="button" class="primary" id="hub-plugin-keep">Save</button>` +
      `</div>`;
    hub$("hub-plugin-keep").onclick = () => { hubToast("Plugin saved", "ok"); _pendingManifest = null; loadPlugins(); preview.classList.add("hidden"); };
    hub$("hub-plugin-discard").onclick = async () => {
      if (_pendingManifest?.slug) await hubPost("/api/hub/plugins/discard", { slug: _pendingManifest.slug });
      _pendingManifest = null;
      preview.classList.add("hidden");
      hubToast("Discarded", "info");
      loadPlugins();
    };
    hubToast("Manifest generated", "ok");
  } finally {
    btn.textContent = "Generate";
    btn.disabled = false;
  }
}

async function refreshHealth() {
  const data = await hubGet("/api/hub/status");
  const svc = hub$("hub-service-dots");
  svc.innerHTML = "";
  (data.services || []).forEach((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="status-dot ${s.connected ? "on" : "off"}"></span><span>${hubEsc(s.id)}</span><span class="health-label">${hubEsc(s.label)}</span>`;
    svc.appendChild(li);
  });
  const orch = data.orchestrator || {};
  hub$("hub-orchestrator-stats").innerHTML =
    `<p>Queue depth: <strong>${orch.queue_depth ?? 0}</strong></p>` +
    `<p>Current job: <strong>${hubEsc(orch.current_job || "none")}</strong></p>`;
  const plugs = data.plugins || {};
  hub$("hub-plugin-stats").innerHTML =
    `<p>Total: <strong>${plugs.total ?? 0}</strong></p><p>Active: <strong>${plugs.active ?? 0}</strong></p>`;
  const sp = data.spend || {};
  hub$("hub-spend-stats").innerHTML =
    `<p>Today: <strong>$${Number(sp.today || 0).toFixed(2)}</strong></p>` +
    `<p>Month: <strong>$${Number(sp.month || 0).toFixed(2)}</strong></p>` +
    `<p>Remaining: <strong>$${Number(sp.remaining || 0).toFixed(2)}</strong></p>`;
}

function startHealthPoll() {
  stopHealthPoll();
  refreshHealth();
  _healthTimer = setInterval(refreshHealth, 10000);
}
function stopHealthPoll() {
  if (_healthTimer) { clearInterval(_healthTimer); _healthTimer = null; }
}

async function runPreflight() {
  const box = hub$("hub-preflight-result");
  box.classList.remove("hidden");
  box.textContent = "Running preflight…";
  const { ok, data } = await hubPost("/api/message", { text: "run preflight check and tell me what needs fixing" });
  box.textContent = data.reply || data.error || (ok ? "(no reply)" : "Preflight failed");
}

function initHub() {
  hub$$(".hub-tab").forEach((tab) => {
    tab.onclick = () => showHubTab(tab.dataset.hubTab);
  });
  hub$("hub-plugin-generate").onclick = generatePlugin;
  hub$("hub-preflight").onclick = runPreflight;

  document.addEventListener("jarvis:view", (e) => {
    if (e.detail === "hub") {
      loadIntegrations();
      loadPlugins();
      const active = hub$(".hub-tab.active")?.dataset.hubTab;
      if (active === "health") startHealthPoll();
    } else {
      stopHealthPoll();
    }
  });
}

document.addEventListener("DOMContentLoaded", initHub);
