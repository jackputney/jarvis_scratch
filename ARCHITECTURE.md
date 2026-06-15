# Jarvis Architecture

Jarvis is a privacy-first, local voice assistant and personal automation hub. Voice, the localhost dashboard, cron plugins, and webhooks all enqueue work on a single orchestrator; one worker runs Claude with tools, confirmation gates, and TTS. State flows through an in-process EventBus to the dashboard (SSE) and legacy `events.py` subscribers.

## Command flow

```
Voice wake ──► STT ──► orchestrator.submit(VOICE)
Dashboard dock ──► orchestrator.submit(DASHBOARD)
Cron plugin ──► orchestrator.submit(SCHEDULE)
Webhook POST ──► orchestrator.submit(WEBHOOK)
                         │
                         ▼
              Bounded FIFO queue (depth 3)
              Stale drop > 60s · cancel_current()
                         │
                         ▼
              Worker: process_query() ──► Claude (streaming)
                         │                    │
                         │                    ▼
                         │              Tool dispatch + confirm
                         ▼
              TTS (batch or sentence streaming)
                         │
                         ▼
              EventBus ──► SSE / orb / events.py
```

## Thread model

| Thread | Owns | Shared state |
|--------|------|--------------|
| Main | Qt face widget (optional), app lifecycle | Reads config |
| `jarvis-dashboard` | Flask on 127.0.0.1:7777 | EventBus fan-out, orchestrator submit |
| `jarvis-orchestrator` | Single command worker | Queue, `_jobs`, interrupt |
| `jarvis-pipeline` | Mic, wake word, VAD, STT | Submits to orchestrator only |
| Plugin cron timers | Fire prompts on schedule | Submit to orchestrator |
| Claude executor | Blocking Anthropic HTTP | Interrupt event |

## Orchestrator

- **Queue depth:** 3 waiting commands; rejects with busy when full.
- **Stale policy:** Commands older than 60s are dropped at dequeue.
- **Cancel:** `cancel_current()` sets interrupt, clears queue, marks jobs cancelled.
- **Jobs pruning:** Terminal jobs removed from `_jobs` after 300 seconds.
- **TTS:** Orchestrator speaks for `command.speak=True` unless streaming TTS already spoke chunks (`stream_spoken`).

## Event system

Primary bus (`orchestrator/events.py`):

- `job.state` — queued / running / done / failed / cancelled
- `job.transcript` — heard text + reply
- `pipeline.state` — IDLE, LISTENING, THINKING, WAITING_CONFIRM, SPEAKING
- `tool.run` — dashboard or voice tool execution
- `confirm.pending` — (via SSE replay from tools/confirm)

Legacy path: `events.py` holds pipeline state and conversation log for `/api/state`. `orchestrator/runtime.py` subscribes to the bus and mirrors `pipeline.state` into `events.set_pipeline_state()` for backward compatibility. New code should emit on the bus only.

## Tool system

- **Registry:** `tools/registry.py` — `TOOL_DEFINITIONS` (Anthropic schema) + `TOOL_DISPATCH` (callables).
- **Risk tiers:**
  - `READ_ONLY_TOOLS` — no confirm
  - `AUTO_ALLOW_TOOLS` — low-risk mutating (voice skips confirm when gate off)
  - `CONFIRM_REQUIRED_TOOLS` — voice waits on dashboard modal; dashboard `/api/tools/run` uses two-step `confirm_id`
- **Voice vs dashboard:** Voice uses `tools/confirm.py` (single pending, timeout). Dashboard high-risk uses `dashboard/tools_run_confirm.py` (UUID, 60s expiry).

## Hub and integrations

- **Source of truth:** `hub/integrations.json` — never hardcode service names in Python/JS.
- **Status:** `hub/registry.py` resolves connected/label from env keys, OAuth token files, or `auth_type: none`. Integrations with `"status": "coming_soon"` always show disconnected / Coming soon.
- **Secrets:** API keys in `.env`; non-secrets (budgets) in `config.json`.

## Plugin system

- **Manifest schema:** `plugins/manifest.py` — name, description, trigger, prompt, risk_tier.
- **Discovery:** `plugins/loader.py` scans `plugins/*/manifest.json` at startup.
- **Triggers:** `cron` (scheduler), `webhook` (`POST /hooks/<id>`), `voice`, `event` (reserved).
- **Lifecycle:** Enabled unless `plugins/<slug>/.disabled` exists. Cron reschedules after each fire. Shutdown cancels timers in `main.py`.

## Memory tiers

| Tier | Storage | Purpose |
|------|---------|---------|
| Variables | SQLite `variables` | Key-value facts |
| Notes | Markdown files under memory root | User/topic notes |
| Diary | Daily markdown logs | Auto-learn from turns (`memory_auto_learn`) |
| Semantic | FTS5 index | `search_memory` / `remember` tools |

Diary growth is capped by `memory_diary_max_mb`. SQLite retention (`db_retention_days`) prunes usage, conversations, and tool_runs at startup.

## Security model

- **Trust boundary:** Dashboard binds to 127.0.0.1 only; no auth (single-user machine).
- **Confirm gate:** High-risk tools require explicit approval (voice modal or dashboard confirm_id).
- **open_app:** AppleScript allowlist / escaping in `tools/system.py`.
- **PII:** Tool args may appear in confirm UI and logs; secrets never logged.

## Branch strategy

- **`develop`** — integration branch; PRs target here.
- **`main`** — release tip (fast-forward from develop).
- **Feature branches** (e.g. Oliver's remotes) — cherry-pick individual files; do not merge wholesale if they remove orchestrator/hub.

## File map

| Path | Role |
|------|------|
| `main.py` | Startup: DB, Google OAuth, dashboard, plugins, STT warm-up, pipeline |
| `pipeline.py` | Voice loop, STT, Claude streaming, streaming TTS |
| `orchestrator/` | Command queue, worker, EventBus |
| `dashboard/` | Flask control panel, SSE, tool run API, webhooks |
| `hub/` | Integration catalogue and status |
| `plugins/` | Manifests, loader, cron scheduler |
| `tools/` | Tool implementations and registry |
| `memory/` | SQLite, notes, semantic FTS5, diary learn |
| `config.py` | Cached settings + env keys |
