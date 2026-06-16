# Jarvis — Feature Overview

Jarvis is a privacy-first voice AI assistant and personal automation hub. You talk to it naturally; it listens locally, reasons with Claude, runs tools on your behalf, and speaks back in real time. A localhost dashboard gives you full control over memory, tools, spend, and integrations.

This document is a product-level map of what Jarvis can do today. For setup and configuration, see [README.md](README.md). For internals, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## At a glance

| Area | What you get |
|------|----------------|
| **Voice** | Wake word ("hey Jarvis"), local STT, follow-up listening, streaming TTS |
| **Brain** | Claude Haiku by default; escalates to Sonnet when needed |
| **Tools** | 30+ built-in actions across Google, Slack, GitHub, weather, web, and system |
| **Memory** | Local facts, notes, diary, and semantic search — nothing leaves your machine |
| **Dashboard** | Mission-control UI at `http://127.0.0.1:7777` with live SSE updates |
| **Automation** | Cron plugins, webhooks, and a plugin generator in the Hub |
| **Safety** | Token budgets, high-risk confirm gates, localhost-only API |

---

## How you interact with Jarvis

### Voice (primary)

1. Say **"hey Jarvis"** to wake it (openWakeWord model; the bare word "Jarvis" alone does not trigger).
2. Speak your request. Jarvis records until silence is detected (VAD), transcribes locally, and sends the text to the orchestrator.
3. Jarvis thinks, may call tools, then speaks the reply via Cartesia streaming TTS (or pyttsx3 fallback).
4. After replying, it keeps listening briefly for a follow-up without requiring the wake word again.

**Orb controls:** click to mute/unmute, drag to reposition, **Stop** or **Escape** to cancel the current turn and clear the queue.

### Dashboard (secondary)

Open **http://127.0.0.1:7777** (started automatically with Jarvis). Type in the command dock from any view — dashboard messages share the same orchestrator queue as voice, so nothing races or overlaps.

### Scheduled automation

Plugins can fire on a **cron** schedule or via **webhook** (`POST /hooks/<id>`). Each trigger submits an ordinary command through the orchestrator with the same budget, logging, and confirm rules as voice.

---

## Voice and audio pipeline

| Feature | Detail |
|---------|--------|
| **Wake word** | openWakeWord `"hey_jarvis"` model; runs on a daemon thread |
| **Speech-to-text** | mlx-whisper on Apple Silicon (Metal); configurable model size (`tiny` default, `small` for accuracy) |
| **STT backends** | `mlx` (macOS default) or `faster` (Windows/Linux via faster-whisper) |
| **Contact hotwords** | Google Contact names cached and fed to STT for better name recognition |
| **VAD** | webrtcvad when available; energy-based fallback when not |
| **Audio capture** | sounddevice preferred; PyAudio fallback |
| **Text-to-speech** | Cartesia streaming (`speak_stream`) — first audio in ~150 ms; sentence-by-sentence during Claude streaming |
| **Follow-up window** | Extended listening after a reply so you can continue the conversation naturally |

---

## AI and reasoning

### Model routing

Every turn **starts on the fast model** (Haiku by default). Jarvis can call the **`escalate` tool** to hand off to the smart model (Sonnet) mid-turn when the request needs careful reasoning, planning, coding, or nuanced writing.

Simple lookups, chit-chat, and single tool actions stay on the fast model without escalation.

### Prompt caching

The system prompt is sent with Anthropic ephemeral cache control to reduce input-token cost on repeated turns.

### Conversation context

- In-memory conversation history (configurable turn count and character cap)
- Injected memory: variables, recent notes, semantic recall hits, and profile facts
- Exact token usage logged per response — never estimated

### Spend controls

| Threshold | Behaviour |
|-----------|-----------|
| **80% of daily budget** | One-time spoken heads-up; orb turns amber |
| **100% of daily budget** | Hard stop on API calls; orb turns red |
| **Monthly budget** | Tracked for reference in the dashboard |

Pricing reference: Haiku $1/$5 per Mtok (in/out), Sonnet $3/$15.

---

## Memory system

All memory is **local**. Assign any folder via `memory_root_path` in config or the dashboard Settings panel.

| Store | Purpose |
|-------|---------|
| **`variables.db`** | Structured key-value facts (name, city, preferences) injected into every prompt |
| **`notes/`** | Markdown topic notes Jarvis can read and write |
| **`profile.md`** | Durable facts learned via the `remember` tool |
| **`diary/`** | Daily conversation logs when auto-learn is enabled |
| **`semantic_index.db`** | FTS5 index for meaning-based recall via `search_memory` |

**Semantic recall** (on by default) pulls the most relevant memories into each prompt, not just the most recent. **Auto-learn** (on by default) saves completed turns to today's diary.

Diary growth is capped by `memory_diary_max_mb`. SQLite retention prunes old usage, conversation, and tool-run records at startup.

---

## Built-in tools

Tools are grouped by risk tier. Read-only tools never prompt. Low-risk mutating tools run immediately in voice mode. High-risk tools require dashboard confirmation when `confirm_before_execute` is on.

### System and web

| Tool | Risk | What it does |
|------|------|--------------|
| `open_app` | Auto-allow | Open an application (macOS, Windows, or Linux) |
| `web_search` | Read-only | Brave Search with DuckDuckGo fallback |
| `get_weather` | Read-only | Current weather and 3-day forecast via Open-Meteo (no API key) |
| `escalate` | Auto-allow | Hand the turn to the smart model |

### Memory

| Tool | Risk | What it does |
|------|------|--------------|
| `set_variable` | Auto-allow | Store a key-value fact |
| `get_variable` | Read-only | Retrieve a stored fact |
| `write_note` | Auto-allow | Save or overwrite a Markdown note |
| `read_note` | Read-only | Read a note by title |
| `remember` | Auto-allow | Persist a durable fact to profile |
| `search_memory` | Read-only | Semantic search across notes, diary, and profile |

### Google Workspace

Requires one-time OAuth (browser sign-in); token stored in `memory/google_token.json`.

| Tool | Risk | What it does |
|------|------|--------------|
| `get_calendar_events` | Read-only | Upcoming calendar events |
| `get_todays_schedule` | Read-only | Today's schedule, formatted for speech |
| `get_unread_emails` | Read-only | Unread inbox summaries |
| `list_recent_emails` | Read-only | Most recent inbox messages |
| `search_emails` | Read-only | Gmail search query |
| `send_email` | **Confirm** | Send plain-text email |
| `read_sheet` | Read-only | Read a Sheets range |
| `append_row` | **Confirm** | Append a row to a sheet |
| `update_cell` | **Confirm** | Update a single cell |
| `search_contacts` | Read-only | Search Google Contacts by name |
| `list_contacts` | Read-only | List recent contacts |
| `search_drive` | Read-only | Search Drive files by name |
| `read_drive_file` | Read-only | Read text content of a Drive file (truncated) |

### Slack

Requires `SLACK_BOT_TOKEN` in `.env`.

| Tool | Risk | What it does |
|------|------|--------------|
| `read_slack_channel` | Read-only | Recent messages from a channel |
| `send_slack_message` | **Confirm** | Post a message to a channel |

### GitHub

Requires `GITHUB_TOKEN` in `.env`.

| Tool | Risk | What it does |
|------|------|--------------|
| `search_github_issues` | Read-only | Search issues in a repo |
| `get_github_repo_summary` | Read-only | Repo stats and description |
| `create_github_comment` | **Confirm** | Comment on an issue |

---

## Integrations (Hub)

The Hub (`dashboard` → **Hub** view) is driven by `hub/integrations.json`. Connection status is resolved from env keys, OAuth token files, or `auth_type: none`.

| Integration | Status | Auth |
|-------------|--------|------|
| **Anthropic** | Required | API key |
| **Cartesia** | Optional (TTS) | API key |
| **Google Workspace** | Optional | OAuth (Gmail, Calendar, Sheets, Drive, Contacts) |
| **Weather** | Built-in | None (Open-Meteo) |
| **Brave Search** | Optional | API key (falls back to DuckDuckGo) |
| **Slack** | Optional | Bot token |
| **GitHub** | Optional | Personal access token |
| **Home Assistant** | Coming soon | URL + token |
| **Notion** | Coming soon | Integration token |

The Hub also includes a **plugin generator**: describe what you want in plain language, preview the manifest, and save it to `plugins/`.

---

## Plugins and automation

Plugins live in `plugins/*/manifest.json`. At startup Jarvis discovers manifests and schedules cron triggers.

**Built-in example:** `morning_briefing` — fires at 08:00 daily, summarises calendar, unread email, and weather.

| Trigger type | How it works |
|--------------|--------------|
| `cron` | Standard cron expression; reschedules after each fire |
| `webhook` | `POST /hooks/<plugin_id>` on the dashboard server |
| `voice` | Reserved for future voice-triggered plugins |
| `event` | Reserved for event-bus triggers |

Plugins declare a `risk_tier` (`read_only`, `auto_allow`, `confirm_required`) and optional `requires` integrations. Disable a plugin by creating `plugins/<slug>/.disabled`.

---

## Control dashboard

Seven views, dark mission-control design, live updates over Server-Sent Events (`/api/events`).

| View | Purpose |
|------|---------|
| **Overview** | Metrics (queries, tools, uptime), spend bar, active plugins |
| **Activity** | Real-time feed of voice turns, dashboard messages, and tool runs |
| **Tools** | Gallery grouped by risk tier; schema-driven run drawer; two-step confirm for high-risk |
| **Memory** | Edit variables and notes (add / edit / delete) |
| **Plugins** | List, enable/disable, and inspect plugin manifests |
| **Hub** | Integrations, connections, OAuth flows, plugin generator |
| **Settings** | Models, wake word, Whisper/STT, TTS voice, budgets, memory paths — saved live to `config.json` |

**Persistent command dock** — type to Jarvis from any view.

**Tool confirm modal** — when a high-risk tool is requested via voice, the orb turns amber (`WAITING_CONFIRM`), Jarvis speaks a heads-up, and Allow/Deny appears in the dashboard. Auto-denies after 30 s. Stop on the orb cancels a pending confirm.

All `/api/*` endpoints bind to **127.0.0.1 only** (no remote access, no auth — single-user machine).

---

## Orb UI

A floating PyQt6 HUD in the top-right corner (disable with `"ui_enabled": false`).

| State | Visual |
|-------|--------|
| **IDLE** | Static glass sphere on frosted panel |
| **LISTENING** | Slow breathing pulse (green) |
| **THINKING** | Fast rotating arc (purple) |
| **WAITING_CONFIRM** | Amber pulse |
| **SPEAKING** | Ripple rings expanding from centre |

Landscape frosted panel (200×120), 8-layer luminous sphere rendering, "Jarvis" label chip. macOS vibrancy with painted fallback on other platforms.

---

## Orchestrator

Voice, dashboard, cron plugins, and webhooks all call `orchestrator.submit(Command)` — never the pipeline directly.

| Policy | Value |
|--------|-------|
| Queue depth | 3 waiting commands |
| Stale drop | Commands older than 60 s discarded |
| Cancel | Stop/Escape clears queue and interrupts in-flight Claude stream |
| Serialisation | One worker thread — no overlapping turns |

State flows through an in-process EventBus to the dashboard SSE stream and the orb.

---

## Security and privacy

- **Local-first memory** — facts, notes, diary, and semantic index stay on disk; only Claude API calls leave the machine (plus optional third-party integrations you configure).
- **Secrets in `.env` only** — API keys never in `config.json` or logs.
- **Confirm gates** — high-risk mutations require explicit approval.
- **Localhost dashboard** — no authentication because the trust boundary is your machine.
- **Budget hard stop** — no silent overspend on Anthropic API.
- **Google OAuth token** — stored in gitignored `memory/google_token.json`.

---

## Platform support

| Platform | Voice loop | Orb UI | Notes |
|----------|------------|--------|-------|
| **macOS (Apple Silicon)** | Full (mlx-whisper, Metal) | PyQt6 orb | Primary target; use `./run.sh` |
| **Windows** | Full (faster-whisper) | PyQt6 orb | Use `run.ps1`; set `"stt_backend": "faster"` |
| **Linux** | Full (faster-whisper) | PyQt6 orb | PyAudio/sounddevice for capture |
| **Headless** | Dashboard + plugins only | Disabled | `"ui_enabled": false` |

---

## Test coverage

167+ automated tests cover the orchestrator, pipeline speed features, tools, memory, dashboard API, Hub, plugins, budget enforcement, confirm gates, and orb rendering maths. Run:

```bash
python3.11 -m pytest --tb=short -q
```

---

## Roadmap (not yet shipped)

- Home Assistant smart-home control
- Notion integration
- Voice-triggered and event-bus plugin triggers
- Dashboard screenshots in README

---

## Related docs

| Document | Audience |
|----------|----------|
| [README.md](README.md) | End users — install, config, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Developers — threads, event bus, file map |
| [orchestrator/QUEUE_POLICY.md](orchestrator/QUEUE_POLICY.md) | Queue semantics and cancel behaviour |
| [plugins/README.md](plugins/README.md) | Plugin manifest schema |
