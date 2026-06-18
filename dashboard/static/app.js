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

const VIEW_ORDER = ["overview", "activity", "tools", "memory", "contacts", "plugins", "hub", "settings"];

const AVATAR_COLORS = [
  { bg: "var(--accent-subtle)", color: "var(--accent)" },
  { bg: "rgba(52, 211, 153, 0.12)", color: "var(--good)" },
  { bg: "rgba(251, 191, 36, 0.12)", color: "var(--warn)" },
  { bg: "rgba(248, 113, 113, 0.12)", color: "var(--danger)" },
  { bg: "rgba(96, 165, 250, 0.12)", color: "#60A5FA" },
  { bg: "rgba(236, 72, 153, 0.1)", color: "#EC4899" },
  { bg: "rgba(139, 92, 246, 0.1)", color: "#8B5CF6" },
  { bg: "rgba(34, 197, 94, 0.1)", color: "#22C55E" },
  { bg: "var(--accent-subtle)", color: "var(--accent)" },
];

function avatarColor(name) {
  const ch = (name || "?").charCodeAt(0);
  const i = Math.floor((Math.max(65, ch) - 65) / 3) % AVATAR_COLORS.length;
  return AVATAR_COLORS[Math.max(0, i)];
}

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
  if (name === "contacts") loadContactsView();
  if (name === "email") loadEmailView();
  if (name === "calendar") loadCalendarView();
  if (name === "overview") {
    loadOverviewPlugins();
    loadDevicePanel();
    loadMusicPanel();
  }
  document.dispatchEvent(new CustomEvent("jarvis:view", { detail: name }));
}

window.jarvisShowView = switchView;

$$(".nav-item").forEach((b) => (b.onclick = () => switchView(b.dataset.view)));

const contactsSearch = $("contacts-search");
if (contactsSearch) {
  contactsSearch.addEventListener("input", (e) => filterContacts(e.target.value));
}

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
    try {
      const contactsData = await getJSON("/api/contacts");
      const count = (contactsData.contacts || []).length;
      const metricEl = $("metric-contacts");
      if (metricEl) {
        metricEl.textContent = contactsData.error ? "—" : String(count);
      }
    } catch {
      /* transient */
    }
  } catch {
    /* transient */
  }
}

function contactsSkeleton() {
  const list = $("contacts-list");
  if (!list) return;
  list.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const row = document.createElement("div");
    row.className = "contact-skeleton";
    row.innerHTML = '<div class="contact-skeleton-avatar"></div><div class="contact-skeleton-lines"><span></span><span></span></div>';
    list.appendChild(row);
  }
}

function filterContacts(query) {
  const q = (query || "").toLowerCase();
  document.querySelectorAll(".contact-card").forEach((card) => {
    const name = (card.dataset.name || "").toLowerCase();
    const email = (card.dataset.email || "").toLowerCase();
    const org = (card.dataset.org || "").toLowerCase();
    card.style.display = name.includes(q) || email.includes(q) || org.includes(q) ? "" : "none";
  });
}

window.filterContacts = filterContacts;

function composeEmailTo(email) {
  if (!email) return;
  const input = $("dock-input");
  input.value = `send email to ${email} subject `;
  input.focus();
}

function copyContactText(text, label) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(
    () => showToast(`${label} copied`, "ok"),
    () => showToast("Could not copy", "err")
  );
}

function renderContactCard(c) {
  const orgLine = [c.organization, c.title].filter(Boolean).join(" · ");
  const colors = avatarColor(c.name);
  const card = document.createElement("div");
  card.className = "contact-card";
  card.dataset.name = c.name || "";
  card.dataset.email = c.email || "";
  card.dataset.org = c.organization || "";
  let detailLine = "";
  if (c.email || c.phone) {
    const parts = [];
    if (c.email) parts.push(`<a href="#" class="contact-email-link">${esc(c.email)}</a>`);
    if (c.phone) parts.push(esc(c.phone));
    detailLine = `<div class="contact-detail">${parts.join(" · ")}</div>`;
  }
  card.innerHTML =
    `<div class="contact-avatar" style="background:${colors.bg};color:${colors.color}">${esc(c.initials || "?")}</div>` +
    `<div class="contact-body">` +
    `<div class="contact-name">${esc(c.name)}</div>` +
    (orgLine ? `<div class="contact-detail">${esc(orgLine)}</div>` : "") +
    detailLine +
    `</div>` +
    `<div class="contact-actions">` +
    (c.email
      ? `<button type="button" class="contact-action-btn" title="Email" data-action="email" data-email="${esc(c.email)}"><i class="ti ti-mail"></i></button>`
      : "") +
    (c.email
      ? `<button type="button" class="contact-action-btn" title="Copy email" data-action="copy-email" data-copy="${esc(c.email)}"><i class="ti ti-copy"></i></button>`
      : "") +
    (c.phone
      ? `<button type="button" class="contact-action-btn" title="Copy phone" data-action="copy-phone" data-copy="${esc(c.phone)}"><i class="ti ti-phone"></i></button>`
      : "") +
    `</div>`;
  card.querySelectorAll("[data-action='email']").forEach((btn) => {
    btn.onclick = (e) => {
      e.preventDefault();
      composeEmailTo(btn.dataset.email);
    };
  });
  card.querySelectorAll("[data-action='copy-email'], [data-action='copy-phone']").forEach((btn) => {
    btn.onclick = () => copyContactText(btn.dataset.copy, btn.title || "Value");
  });
  const emailLink = card.querySelector(".contact-email-link");
  if (emailLink) {
    emailLink.onclick = (e) => {
      e.preventDefault();
      composeEmailTo(c.email);
    };
  }
  return card;
}

async function loadContactsView() {
  const list = $("contacts-list");
  if (!list) return;
  contactsSkeleton();
  try {
    const data = await getJSON("/api/contacts");
    list.innerHTML = "";
    const contacts = data.contacts || [];
    if (data.error && !contacts.length) {
      list.innerHTML =
        `<p class="contacts-empty">Could not load contacts.</p>` +
        `<p class="contacts-empty sub">${esc(data.error)}</p>` +
        `<p class="contacts-empty"><a href="#" onclick="switchView('hub');return false;">Connect Google in Hub → Connections</a></p>`;
      return;
    }
    if (!contacts.length) {
      list.innerHTML =
        `<p class="contacts-empty">No contacts found.</p>` +
        `<p class="contacts-empty sub"><a href="#" onclick="switchView('hub');return false;">Connect Google in Hub → Connections</a></p>`;
      return;
    }
    contacts.forEach((c) => list.appendChild(renderContactCard(c)));
    const search = $("contacts-search");
    if (search && search.value) filterContacts(search.value);
  } catch (err) {
    list.innerHTML = `<p class="contacts-empty">Could not load contacts. Try a hard refresh (⌘⇧R).</p>`;
  }
}

function emailSkeleton() {
  const list = $("email-list");
  if (!list) return;
  list.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const row = document.createElement("div");
    row.className = "email-skeleton";
    row.innerHTML =
      `<div class="email-skeleton-lines"><span style="width:35%"></span><span style="width:55%"></span><span></span></div>`;
    list.appendChild(row);
  }
}

function formatEmailDate(raw) {
  if (!raw) return "";
  const parsed = Date.parse(raw);
  if (Number.isNaN(parsed)) return raw;
  return new Date(parsed).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function renderEmailRow(email) {
  const row = document.createElement("article");
  row.className = "email-row";
  row.dataset.messageId = email.id || "";
  row.innerHTML =
    `<div class="email-row-main">` +
    `<div class="email-row-head">` +
    `<span class="email-from">${esc(email.from || "Unknown sender")}</span>` +
    `<time class="email-date">${esc(formatEmailDate(email.date))}</time>` +
    `</div>` +
    `<div class="email-subject">${esc(email.subject || "(no subject)")}</div>` +
    `<p class="email-snippet">${esc(email.snippet || "")}</p>` +
    `</div>` +
    `<div class="email-row-actions">` +
    `<button type="button" class="ghost tiny email-draft-btn">Draft reply</button>` +
    `</div>`;
  row.querySelector(".email-draft-btn").addEventListener("click", () => openEmailDraft(email));
  return row;
}

let _emailComposeConfirmId = null;

function closeEmailCompose() {
  $("email-compose-drawer")?.classList.add("hidden");
  _emailComposeConfirmId = null;
  const sendBtn = $("email-compose-send");
  if (sendBtn) {
    sendBtn.textContent = "Send";
    sendBtn.className = "primary";
    sendBtn.disabled = false;
    sendBtn.onclick = sendComposedEmail;
  }
}

function openEmailCompose(prefill) {
  $("email-compose-to").value = prefill.to || "";
  $("email-compose-subject-input").value = prefill.subject || "";
  $("email-compose-body").value = prefill.body || "";
  $("email-compose-subject").textContent = prefill.subject || "Reply";
  $("email-compose-drawer")?.classList.remove("hidden");
  $("email-compose-body")?.focus();
}

async function openEmailDraft(email) {
  const btn = document.querySelector(`.email-row[data-message-id="${CSS.escape(email.id)}"] .email-draft-btn`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Drafting…";
  }
  try {
    const data = await sendJSON("/api/email/draft-reply", "POST", { message_id: email.id });
    if (!data.ok) {
      showToast(data.error || "Could not draft reply", "err", 5000);
      return;
    }
    openEmailCompose({
      to: data.to || email.from_email || "",
      subject: data.subject || "",
      body: data.body || "",
    });
  } catch {
    showToast("Draft failed (network)", "err");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Draft reply";
    }
  }
}

async function sendComposedEmail() {
  const to = $("email-compose-to")?.value.trim();
  const subject = $("email-compose-subject-input")?.value.trim();
  const body = $("email-compose-body")?.value.trim();
  if (!to || !subject || !body) {
    showToast("To, subject, and message are required", "err");
    return;
  }

  const inputs = { to, subject, body };
  const sendBtn = $("email-compose-send");
  sendBtn.disabled = true;
  sendBtn.textContent = "Sending…";

  try {
    let res = await sendJSON("/api/tools/run", "POST", {
      name: "send_email",
      inputs,
      confirm_id: _emailComposeConfirmId || undefined,
      confirmed: Boolean(_emailComposeConfirmId),
    });

    if (res.confirm_required) {
      _emailComposeConfirmId = res.confirm_id;
      sendBtn.textContent = "Confirm send";
      sendBtn.className = "danger";
      sendBtn.disabled = false;
      showToast("Confirm to send this email", "info", 5000);
      return;
    }

    if (res.ok) {
      showToast(res.result || "Email sent.", "ok", 4000);
      closeEmailCompose();
      await loadEmailView();
    } else {
      showToast(res.error || res.result || "Send failed", "err", 5000);
    }
  } catch {
    showToast("Send failed (network)", "err");
  } finally {
    if (!_emailComposeConfirmId) {
      sendBtn.textContent = "Send";
      sendBtn.className = "primary";
      sendBtn.disabled = false;
    }
  }
}

async function loadEmailView() {
  const list = $("email-list");
  const countEl = $("email-count");
  if (!list) return;
  emailSkeleton();
  try {
    const data = await getJSON("/api/email/unread");
    list.innerHTML = "";
    if (!data.ok && data.error) {
      list.innerHTML =
        `<p class="email-empty">Could not load unread email.</p>` +
        `<p class="email-empty sub">${esc(data.error)}</p>` +
        `<p class="email-empty"><a href="#" onclick="switchView('hub');return false;">Connect Google in Hub → Connections</a></p>`;
      if (countEl) countEl.textContent = "—";
      return;
    }
    const emails = data.emails || [];
    if (countEl) countEl.textContent = emails.length ? `${emails.length} unread` : "Inbox clear";
    if (!emails.length) {
      list.innerHTML = `<p class="email-empty">No unread emails. Nice work.</p>`;
      return;
    }
    emails.forEach((email) => list.appendChild(renderEmailRow(email)));
  } catch {
    list.innerHTML = `<p class="email-empty">Could not load email. Try a hard refresh (⌘⇧R).</p>`;
    if (countEl) countEl.textContent = "—";
  }
}

$("email-refresh")?.addEventListener("click", () => loadEmailView());
$("email-compose-close")?.addEventListener("click", closeEmailCompose);
$("email-compose-cancel")?.addEventListener("click", closeEmailCompose);
$("email-compose-scrim")?.addEventListener("click", closeEmailCompose);
$("email-compose-send")?.addEventListener("click", sendComposedEmail);

const CALENDAR_HOUR_PX = 48;
const CALENDAR_PX_PER_MIN = CALENDAR_HOUR_PX / 60;
const CALENDAR_MIN_EVENT_PX = 40;
let _calendarDay = null;

function todayIsoDate() {
  const now = new Date();
  const tzOffset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - tzOffset).toISOString().slice(0, 10);
}

function shiftIsoDate(isoDate, deltaDays) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + deltaDays));
  return dt.toISOString().slice(0, 10);
}

function calendarSkeleton() {
  const timeline = $("calendar-timeline");
  if (!timeline) return;
  timeline.innerHTML = "";
  timeline.style.height = `${3 * CALENDAR_HOUR_PX}px`;
  timeline.style.minHeight = "0";
  for (let i = 0; i < 3; i++) {
    const row = document.createElement("div");
    row.className = "calendar-skeleton";
    row.innerHTML = `<span></span><span></span><span style="width:70%"></span>`;
    timeline.appendChild(row);
  }
}

function setTimelineHeight(timeline, minStart, maxEnd) {
  const spanMinutes = maxEnd - minStart;
  const px = Math.round(spanMinutes * CALENDAR_PX_PER_MIN);
  timeline.style.height = `${px}px`;
  timeline.style.minHeight = "0";
}

function renderCalendarHourMarkers(timeline, minStart, maxEnd) {
  const firstHour = Math.floor(minStart / 60);
  const lastHour = Math.floor(maxEnd / 60);
  for (let hour = firstHour; hour <= lastHour; hour++) {
    const marker = document.createElement("div");
    marker.className = "calendar-hour-marker";
    marker.style.top = `${Math.round((hour * 60 - minStart) * CALENDAR_PX_PER_MIN)}px`;
    const label = new Date(2000, 0, 1, hour, 0).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    marker.innerHTML = `<span>${esc(label)}</span>`;
    timeline.appendChild(marker);
  }
}

function renderCalendarEmptyRange(timeline, message) {
  const minStart = 9 * 60;
  const maxEnd = 17 * 60;
  setTimelineHeight(timeline, minStart, maxEnd);
  renderCalendarHourMarkers(timeline, minStart, maxEnd);
  if (message) {
    const note = document.createElement("p");
    note.className = "calendar-empty calendar-empty-inline";
    note.textContent = message;
    timeline.appendChild(note);
  }
}

function renderCalendarEventCard(event) {
  const card = document.createElement("article");
  card.className = "calendar-event-card";
  card.setAttribute("role", "listitem");
  const timeRange = event.end_time_label
    ? `${event.time_label} – ${event.end_time_label}`
    : event.time_label;
  const locationHtml = event.location
    ? `<div class="calendar-event-location"><i class="ti ti-map-pin" aria-hidden="true"></i>${esc(event.location)}</div>`
    : "";
  const zoomHtml = event.zoom_link
    ? `<a class="calendar-zoom-link" href="${esc(event.zoom_link)}">Join Zoom</a>`
    : "";
  card.innerHTML =
    `<div class="calendar-event-time">${esc(timeRange)}</div>` +
    `<div class="calendar-event-title">${esc(event.title)}</div>` +
    (locationHtml || zoomHtml
      ? `<div class="calendar-event-meta">${locationHtml}${zoomHtml}</div>`
      : "");
  return card;
}

function renderCalendarTimeline(events) {
  const alldayEl = $("calendar-allday");
  const timeline = $("calendar-timeline");
  if (!timeline || !alldayEl) return;

  const allDay = events.filter((e) => e.all_day);
  const timed = events.filter((e) => !e.all_day);

  if (allDay.length) {
    alldayEl.classList.remove("hidden");
    alldayEl.innerHTML =
      `<div class="calendar-allday-label">All day</div>` +
      `<div class="calendar-allday-items">` +
      allDay
        .map(
          (ev) =>
            `<div class="calendar-allday-item">` +
            `<span class="calendar-event-title">${esc(ev.title)}</span>` +
            (ev.location ? `<span class="calendar-event-location">${esc(ev.location)}</span>` : "") +
            (ev.zoom_link
              ? `<a class="calendar-zoom-link" href="${esc(ev.zoom_link)}">Join Zoom</a>`
              : "") +
            `</div>`
        )
        .join("") +
      `</div>`;
  } else {
    alldayEl.classList.add("hidden");
    alldayEl.innerHTML = "";
  }

  timeline.innerHTML = "";
  if (!timed.length) {
    renderCalendarEmptyRange(
      timeline,
      allDay.length ? "No timed events." : "Nothing scheduled for this day."
    );
    return;
  }

  const starts = timed.map((e) => e.timeline_start ?? 0);
  const ends = timed.map((e) => (e.timeline_start ?? 0) + (e.duration_minutes ?? 30));
  const minStart = Math.max(0, Math.min(...starts) - 60);
  const maxEnd = Math.min(24 * 60, Math.max(...ends) + 60);
  setTimelineHeight(timeline, minStart, maxEnd);

  renderCalendarHourMarkers(timeline, minStart, maxEnd);

  timed.forEach((event) => {
    const block = document.createElement("div");
    block.className = "calendar-event-block";
    const startMin = event.timeline_start ?? minStart;
    const duration = event.duration_minutes ?? 30;
    block.style.top = `${Math.round((startMin - minStart) * CALENDAR_PX_PER_MIN)}px`;
    block.style.height = `${Math.max(
      CALENDAR_MIN_EVENT_PX,
      Math.round(duration * CALENDAR_PX_PER_MIN)
    )}px`;
    block.appendChild(renderCalendarEventCard(event));
    timeline.appendChild(block);
  });
}

async function loadCalendarView(isoDate) {
  if (isoDate) _calendarDay = isoDate;
  if (!_calendarDay) _calendarDay = todayIsoDate();

  const titleEl = $("calendar-day-title");
  const subtitleEl = $("calendar-day-subtitle");
  calendarSkeleton();

  try {
    const data = await getJSON(`/api/calendar/day?date=${encodeURIComponent(_calendarDay)}`);
    if (!data.ok && data.error) {
      $("calendar-timeline").innerHTML =
        `<p class="calendar-empty">Could not load calendar.</p>` +
        `<p class="calendar-empty sub">${esc(data.error)}</p>` +
        `<p class="calendar-empty"><a href="#" onclick="switchView('hub');return false;">Connect Google in Hub → Connections</a></p>`;
      $("calendar-allday")?.classList.add("hidden");
      if (titleEl) titleEl.textContent = _calendarDay;
      if (subtitleEl) subtitleEl.textContent = "";
      return;
    }

    if (titleEl) titleEl.textContent = data.label || _calendarDay;
    if (subtitleEl) {
      subtitleEl.textContent =
        data.count === 1 ? "1 event" : data.count ? `${data.count} events` : "No events";
    }
    renderCalendarTimeline(data.events || []);
  } catch {
    $("calendar-timeline").innerHTML =
      `<p class="calendar-empty">Could not load calendar. Try a hard refresh (⌘⇧R).</p>`;
    $("calendar-allday")?.classList.add("hidden");
  }
}

$("calendar-prev")?.addEventListener("click", () => loadCalendarView(shiftIsoDate(_calendarDay || todayIsoDate(), -1)));
$("calendar-next")?.addEventListener("click", () => loadCalendarView(shiftIsoDate(_calendarDay || todayIsoDate(), 1)));
$("calendar-today")?.addEventListener("click", () => loadCalendarView(todayIsoDate()));

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

const DEVICE_CONTROLS = [
  { label: "Dark mode", icon: "ti-moon", tool: "set_appearance_mode", inputs: { mode: "dark" } },
  { label: "Light mode", icon: "ti-sun", tool: "set_appearance_mode", inputs: { mode: "light" } },
  { label: "Lock screen", icon: "ti-lock", tool: "lock_screen", inputs: {} },
  { label: "Do Not Disturb", icon: "ti-bell-off", tool: "set_do_not_disturb", inputs: { enabled: true } },
  { label: "Battery", icon: "ti-battery-2", tool: "get_battery_status", inputs: {} },
  { label: "WiFi off", icon: "ti-wifi-off", tool: "set_wifi", inputs: { action: "off" } },
];

async function runDeviceControl(toolName, inputs) {
  try {
    const data = await sendJSON("/api/tools/run", "POST", { name: toolName, inputs });
    const msg = data.result || data.error || (data.ok ? "Done." : "Failed.");
    showToast(msg, data.ok ? "ok" : "err", data.ok ? 3200 : 5000);
    return data;
  } catch {
    showToast("Device control failed (network)", "err");
    return null;
  }
}

function loadDevicePanel() {
  const grid = $("device-control-grid");
  if (!grid) return;
  grid.innerHTML = "";
  DEVICE_CONTROLS.forEach((ctrl) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "device-btn";
    btn.innerHTML = `<i class="ti ${ctrl.icon}" aria-hidden="true"></i><span>${esc(ctrl.label)}</span>`;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await runDeviceControl(ctrl.tool, ctrl.inputs);
      btn.disabled = false;
    });
    grid.appendChild(btn);
  });
}

const MUSIC_CONTROLS = [
  { label: "Previous", icon: "ti-player-skip-back", tool: "music_previous", inputs: {} },
  { label: "Play", icon: "ti-player-play", tool: "music_play", inputs: {} },
  { label: "Pause", icon: "ti-player-pause", tool: "music_pause", inputs: {} },
  { label: "Next", icon: "ti-player-skip-forward", tool: "music_skip", inputs: {} },
];

async function refreshNowPlaying() {
  const el = $("music-now-playing");
  if (!el) return;
  try {
    const data = await getJSON("/api/music/now-playing");
    if (!data.supported) {
      $("music-panel")?.classList.add("hidden");
      return;
    }
    $("music-panel")?.classList.remove("hidden");
    el.textContent = data.now_playing || "Not playing.";
  } catch {
    el.textContent = "Could not read now playing.";
  }
}

async function runMusicControl(toolName, inputs) {
  try {
    const data = await sendJSON("/api/tools/run", "POST", { name: toolName, inputs });
    const msg = data.result || data.error || (data.ok ? "Done." : "Failed.");
    showToast(msg, data.ok ? "ok" : "err", data.ok ? 2800 : 5000);
    await refreshNowPlaying();
    return data;
  } catch {
    showToast("Music control failed (network)", "err");
    return null;
  }
}

function loadMusicPanel() {
  const grid = $("music-control-grid");
  if (!grid) return;
  grid.innerHTML = "";
  MUSIC_CONTROLS.forEach((ctrl) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "music-btn";
    btn.innerHTML = `<i class="ti ${ctrl.icon}" aria-hidden="true"></i><span>${esc(ctrl.label)}</span>`;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      await runMusicControl(ctrl.tool, ctrl.inputs);
      btn.disabled = false;
    });
    grid.appendChild(btn);
  });
  refreshNowPlaying();
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
    const enabled = p.enabled !== false;
    const scheduleHint =
      trigger.type === "cron" && trigger.schedule && trigger.schedule.startsWith("*/")
        ? ` · every ${trigger.schedule.split(" ")[0].replace("*/", "")} min`
        : "";
    li.innerHTML =
      `<div class="plugin-card-head">` +
      `<strong>${esc(m.name || p.slug)}</strong>` +
      `<span class="plugin-status ${enabled ? "active" : "inactive"}">` +
      `<span class="status-dot ${enabled ? "idle" : ""}"></span>${enabled ? "Active" : "Disabled"}</span>` +
      `</div>` +
      `<span class="sub">${esc(m.description || "")}</span>` +
      `<span class="sub">${esc(trigger.type || "manual")}${trigger.schedule ? " · " + esc(trigger.schedule) : ""}${scheduleHint}</span>` +
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
  await loadLoginItemToggle();
}

async function loadLoginItemToggle() {
  const row = $("login-item-row");
  const toggle = $("set-login-item");
  if (!row || !toggle) return;
  try {
    const data = await getJSON("/api/login-item");
    if (!data.supported) {
      row.classList.add("hidden");
      return;
    }
    row.classList.remove("hidden");
    toggle.checked = !!data.enabled;
    toggle.disabled = false;
  } catch {
    row.classList.add("hidden");
  }
}

async function setLoginItem(enabled) {
  const toggle = $("set-login-item");
  toggle.disabled = true;
  try {
    const data = await sendJSON("/api/login-item", "POST", { enabled });
    toggle.checked = !!data.enabled;
    showToast(data.result || (enabled ? "Launch at login enabled" : "Launch at login disabled"), "ok");
  } catch (err) {
    toggle.checked = !enabled;
    showToast(err.message || "Could not update launch at login", "err");
  } finally {
    toggle.disabled = false;
  }
}

if ($("set-login-item")) {
  $("set-login-item").onchange = (e) => setLoginItem(e.target.checked);
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
    if (num >= 1 && num <= VIEW_ORDER.length) {
      e.preventDefault();
      switchView(VIEW_ORDER[num - 1]);
    }
  }
});

// ---- Init -------------------------------------------------------------
(async function init() {
  ensureActivityEmpty();
  await loadConfig();
  await Promise.all([loadVars(), loadNotes(), loadMemoryInfo(), loadMetrics(), loadOverviewPlugins(), loadDevicePanel(), loadMusicPanel(), refresh()]);
  connectEvents();
})();
