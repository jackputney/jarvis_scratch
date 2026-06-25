# Changelog

<!-- AGENTS: Add an entry here every time you make changes. -->
<!-- Sign every entry: [Agent: Claude/Cursor — acting for Jack/Oliver — DATE] -->
<!-- Format: date descending, newest first -->

## How to add an entry

```
### YYYY-MM-DD — [what changed] — [who]
[Agent: Claude/Cursor — acting for Jack/Oliver — YYYY-MM-DD]

**Branch:** branch-name | **Tests:** N passing

**What changed:**
- file.py — what and why
- other_file.py — what and why

**Why:** One sentence explaining the reasoning or problem solved.

**Watch out for:** Any gotchas the other dev should know.
```

---

## Log

---

### 2026-06-23 — GitHub write access — Jack

[Agent: Cursor — acting for Jack — 2026-06-23]

**Branch:** jack/sprint-6 | **Tests:** 439 passing

**What changed:**

- `tools/github_self.py` — five write tools: branch, file, PR, issue, comment
- `tools/registry.py` — MODERATE/HIGH_RISK tiers; `DASHBOARD_CONFIRM_TOOLS` unchanged pattern
- `improvement/reflect.py` — Accept opens branch + GitHub issue; stores `github_issue_url`
- `memory/db.py` — `suggestions.github_issue_url` column
- `improvement/trace.py` — `suggestion_github` write op
- `dashboard/app.py` — accept endpoint returns issue URL
- `tests/test_github_self.py` — write tool mocks + accept integration
- `DOCS/FEATURE_DOCS/GITHUB_SELF.md` — read + write documentation
- `costs.py` — daily tool/query counts use local midnight (fixes UTC `date('now') mismatch in tests)

**Why:** Jarvis Thinks suggestions need a concrete handoff to GitHub so Jack/Oliver can pick them up in Cursor and close the loop.

**Watch out for:** Write tools need PAT scopes beyond read-only. `create_own_file`/`create_own_pr` always require confirm. Dev Log Google Doc updated manually (no API access from repo).

---

### 2026-06-23 — confirm gate KeyError fix + Oliver sprint-5 review — Jack

[Agent: Cursor — acting for Jack — 2026-06-23]

**Branch:** jack/self-improve (cd84a3d) | **Tests:** 423 passing

**What changed:**

- `orchestrator/runtime.py` — `_sync_legacy` accepts both `state` and `pipeline_state` keys
- `dashboard/app.py` — SSE `_broadcast` normalises both keys, `/api/state` uses `.get()`
- `dashboard/tools_run_confirm.py` — added `reset_for_tests()`
- `tools/confirm.py` — added `reset_for_tests()`
- `conftest.py` — resets both confirm stores on every test

**Why:** v0.4.0 orchestrator changes introduced `state`/`pipeline_state` key mismatch. Dashboard SSE code expected `pipeline_state`, bus events used `state`. Surfaced as KeyError in high-risk confirm flow. Bug was in main, not Oliver's branch.

**Watch out for:** Any code that reads state snapshots directly with `state["pipeline_state"]` — use `.get()` or normalise via `_sync_legacy`.

---

### 2026-06-23 — Oliver sprint-5 reviewed and approved — Jack

**Branch:** oliver/sprint-5 (pending merge) | **Tests:** 386 pass / 11 pre-existing fails

**What Oliver built:**

- VAD barge-in: 450ms sustained speech + 1.5s grace (stops Windows self-triggering)
- TTS: pcm_22050 (fuller voice, still free-tier safe), continuous speak_stream session
- Diary-poison fix: `memory/semantic.py` filters stale Windows refusals from recall
- `docs/PLATFORM.md`: adapters/ layer proposal — ~80% shared core, ~13 OS-specific files
- `docs/WINDOWS_SETUP.md`: reproducible Windows env (Python 3.11)
- STTBackend adapter POC: mlx vs faster-whisper pulled out of `pipeline.py`

**Sign-offs granted:**

- PLATFORM.md adapters/ strategy approved
- Oliver clear to migrate AudioIO, AppControl, LaunchAtLogin behind adapters

**Watch out for:** `speech_state.py` barge-in thresholds changed — if Mac self-triggers after merge, bump `barge_in_min_ms` back down.

---

### 2026-06-18 — GitHub self-read tools — Jack

[Agent: Cursor — acting for Jack — 2026-06-18]

**Branch:** jack/self-improve | **Tests:** 423 passing

**What changed:**

- `tools/github_self.py` — five READ_ONLY tools: read/list/search/commits/issues against own repo
- `tools/registry.py` — registered all five as READ_ONLY
- `hub/integrations.json` — `github_self` integration entry
- `improvement/reflect.py` — reads tool source from GitHub before high-severity haiku suggestions
- `config.py` / `config.json` — `github_repo`, `github_branch` defaults
- `.env.example` — `GITHUB_PAT`
- `tests/test_github_self.py` — mocked API + reflect integration tests
- `DOCS/FEATURE_DOCS/GITHUB_SELF.md` — feature documentation

**Why:** Jarvis Thinks was guessing at fix locations; reading live repo code lets suggestions cite real line numbers and snippets.

**Watch out for:** PAT reads `main` on GitHub, not uncommitted local files. Rate limits apply to code search.

---

### 2026-06-22 — Agent protocol + feature docs index — Jack

[Agent: Cursor — acting for Jack — 2026-06-22]

**Branch:** jack/self-improve | **Tests:** 413 passing

**What changed:**

- `DOCS/AGENT_PROTOCOL.md` — canonical agent rules (human-only edits, session checklist, allowed/forbidden files)
- `DOCS/FEATURE_DOCS/README.md` — feature index (14 features, one doc per feature)
- `DOCS/FEATURE_DOCS/SELF_IMPROVEMENT.md` — synced to Stage 1–3 status
- `.cursorrules` + `DOCS/.cursorrules` — added ACTIVE STATE section (agents update this only each sprint)

**Why:** Gives Cursor/Claude a single, signed protocol so both devs' agents behave consistently without re-pasting Notion context.

**Watch out for:** `DOCS/AGENT_PROTOCOL.md` and `DOCS/BUILD_PROTOCOL.md` are human-only — agents must not edit them.

---

### 2026-06-22 — DOCS/ markdown structure created — Jack

[Agent: Claude — acting for Jack — 2026-06-22]

**Branch:** N/A (adding to repo root) | **Tests:** 413 passing

**What changed:**

- `DOCS/.cursorrules` — master Cursor context file, auto-loaded every session
- `DOCS/PROJECT_STATE.md` — current state, branches, known issues
- `DOCS/ARCHITECTURE.md` — real file structure, stack, platform matrix
- `DOCS/CHANGELOG.md` — this file, running log with agent signatures
- `DOCS/BUILD_PROTOCOL.md` — branch rules, commit format, PR template
- `DOCS/FEATURE_DOCS/` — one file per feature

**Why:** Notion ran out of free blocks. Migrating all project docs to markdown in the repo so Cursor agents on both machines always have full context without pasting, and Jarvis can eventually read its own docs.

**Watch out for:** `.cursorrules` goes in the REPO ROOT (not DOCS/). Copy it from `DOCS/.cursorrules` to the root when committing.

---

### 2026-06-22 — Stop button, orb state, Jarvis Thinks — Jack

[Agent: Cursor — acting for Jack — 2026-06-22]

**Branch:** jack/self-improve | **Tests:** 413 passing (up from 404)

**What changed:**

- orchestrator/ + runtime.py — `cancel_current()` stops TTS + Claude stream + sets IDLE + calls `TurnTrace.cancel()`
- dashboard/app.js — Stop shows "Stopping…" disabled state
- events.py — `set_pipeline_state()` single source of truth
- ui/face.py — `connect_pipeline_state()` with 50 ms debounce, removed duplicate callback
- improvement/reflect.py — heuristic metrics + haiku judge + tool offender analysis
- dashboard/templates/ — Jarvis Thinks view: severity cards, Accept/Dismiss/Send to Cursor
- dashboard/app.py — GET/POST suggestions endpoints + `/generate`

**Why:**

- Stop button was calling the API but `cancel_current()` wasn't propagating to TTS/Claude
- Orb state was set in multiple places causing THINKING/LISTENING mismatch
- Jarvis Thinks needed to be built so self-improvement suggestions are visible

**Watch out for:**

- Orb state must ONLY be set via `events.set_pipeline_state()` — never directly
- `TurnTrace.cancel()` is cross-thread safe via active-trace registry
- `reflect.py` uses haiku only — don't swap to sonnet (cost)

---

### 2026-06-22 — v0.4.0 merge — Jack + Oliver

[Agent: Cursor — acting for Jack — 2026-06-22]

**Branch:** main tagged v0.4.0 | **Tests:** 404 passing

**What changed:**

- jack/sprint-5 merged: pipeline reliability F1–F6, echo guard, structured state logging
- oliver/sprint-4 merged: cross-platform voice reliability pass
  - BargeInGate (0.48/2 hits), config caching, tighter VAD defaults
  - `_await_followup_utterance` with 3-miss forgiveness
  - ElevenLabs retry loop, `_clear_interrupt()` cancel reset
  - Windows .exe installer, `build_windows.bat`
- jack/self-improve rebased: TurnTrace hooks wired into Oliver's TTS retry + `_mark_speaking`

**Why:** Unified both platform voice passes into one clean base before starting self-improvement Stage 2.

**Watch out for:**

- Conflict resolution: BargeInGate (Jack) + VAD defaults (Oliver) both kept
- TurnTrace hooks in orchestrator/core.py use `_mark_speaking` fallback path

---

### 2026-06-19 — Self-improvement Stage 1 — Jack

[Agent: Cursor — acting for Jack — 2026-06-19]

**Branch:** jack/self-improve (commit a1624d1) | **Tests:** 394 passing

**What changed:**

- memory/db.py — 7 new tables: sessions, turns, events, corrections, lessons, suggestions, baselines
- improvement/trace.py — TurnTrace context manager, background writer thread (non-blocking hot path)
- improvement/signals.py — `detect_correction()`, `detect_repeat_request()` (pure Python, no LLM)
- improvement/stats.py — `compute_stats()`, `fetch_turns()`, `fetch_events()`
- orchestrator/core.py — session per process, TurnTrace wraps every command
- pipeline.py — thin hooks: STT confidence + timing stash, tool call recording
- tts/router.py — tts_ms + provider, tts_fallback event on ElevenLabs → Cartesia
- GET `/api/improvement/turns`, `/events`, `/stats`

**Why:** Every voice interaction now recorded to SQLite for future reflection, scoring, and suggestions. Zero blocking on the hot path (write queue + single writer thread).

**Watch out for:**

- improvement/ has ZERO imports from pipeline.py or registry.py
- STT flow: pipeline stashes metrics before submit(); orchestrator applies on TurnTrace open
- Future tables (lessons, suggestions, baselines) created but unused until Stage 2–4

---

### 2026-06-19 — ElevenLabs TTS + pcm_16000 fix — Jack

[Agent: Cursor — acting for Jack — 2026-06-19]

**Branch:** jack/sprint-4 | **Tests:** 365 passing

**What changed:**

- tts/elevenlabs.py — streaming via ElevenLabs SDK, pcm_16000 (pcm_44100 is Pro-tier only → 403)
- tts/router.py — ElevenLabs → Cartesia → pyttsx3 fallback, WARNING log on fallback
- tts/cartesia.py — sample-rate-aware PCM for non-44.1 kHz
- config.py — tts_provider, elevenlabs_voice_id, elevenlabs_model_id, ELEVENLABS_VOICES
- dashboard Settings — 2×2 voice picker, preview button, provider toggle
- GET `/api/tts/voices`, POST `/api/tts/preview`

**Why:** ElevenLabs was 403-ing on pcm_44100 (Pro tier only) and silently falling back to Cartesia's British voice. The voice picker wasn't reloading config on live turns — fixed with `Config.load_fresh()` per sentence chunk.

**Watch out for:**

- Free tier = 10k chars/month — runs out fast with daily use
- Router fallback logs at WARNING — check logs if voice sounds wrong
- pcm_16000 → sounddevice plays at 16 kHz, not 44.1 kHz

---

### 2026-06-18 — Sprint 3 — 8 features — Jack

[Agent: Cursor — acting for Jack — 2026-06-18]

**Branch:** jack/sprint-3 (commit 47eb04b) | **Tests:** 336 passing

**What changed:**

- onboarding.py — 4-step PyQt6 first-run wizard, live Anthropic key validation
- tools/hotkey.py — global hotkey Ctrl+Shift+Space (pynput daemon thread)
- paths.py — dev/frozen path resolution (MEIPASS vs Application Support)
- jarvis.spec + build_mac.sh — PyInstaller .app bundle (~1.2 GB)
- dashboard/window.py — PyWebView native window (child process, not thread)
- tools/login_item.py — LaunchAgent plist + Settings toggle
- tools/music.py — 7 tools: AppleScript Mac, Spotify URI Windows
- dashboard: Email triage view, Calendar day view
- Google tools: draft_email_reply(), fetch_calendar_day(), _extract_zoom_link()

**Why:** Sprint 3 goal — make Jarvis feel like a real distributable app.

**Watch out for:**

- PyWebView runs in child process (not thread) — PyQt6 owns main thread
- JARVIS_LAUNCHD=1 env var skips PyWebView in launchd context
- .onboarding_complete should be in .gitignore — git rm --cached if needed
- All file paths via paths.py in frozen mode — never hardcode
