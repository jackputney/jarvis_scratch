# Architecture

<!-- AGENTS: Only update this when you make confirmed structural changes -->
<!-- Last updated: 2026-06-24 | Updated by: Cursor acting for Oliver -->

## Stack

| Layer | Tech | Version | Notes |
|-------|------|---------|-------|
| Wake word | openwakeword | 0.6.0 | Cross-platform |
| STT (Mac) | mlx-whisper | 0.4.3 | Apple Silicon, Metal |
| STT (Win) | faster-whisper | ≥1.0.0 | Oliver's primary |
| AI primary | Claude (Anthropic) | anthropic 0.107.1 | haiku → sonnet routing |
| AI fallback | OpenAI, Gemini | optional | `llm/` router |
| TTS primary | ElevenLabs | elevenlabs ≥1.0.0 | pcm_22050 streaming (free tier) |
| TTS fallback | Cartesia | 3.2.0 | pcm streaming |
| TTS last resort | pyttsx3 | 2.99 | local, no key needed |
| Orchestrator | Custom FIFO | — | depth 3, stale-drop 60 s |
| Dashboard | Flask + SSE | Flask 3.1.3 | localhost:7777 |
| Memory | SQLite WAL | — | `memory/db.py` only |
| Orb UI | PyQt6 | 6.11.0 | Cross-platform (Mac-tuned) |
| Audio | sounddevice | ≥0.4.6 | primary, cross-platform |
| App bundle | PyInstaller | — | Mac: .app, Win: .exe |

## Voice pipeline

```
Mic (sounddevice)
  → openwakeword (wake detection)
      ↓ wake word detected
  → adapters/stt.py (mlx-whisper / faster-whisper)
      ↓ transcript + confidence
  → TurnTrace.stash_stt_metrics()
      ↓
  → Orchestrator FIFO queue
      ↓
  → Claude (streaming, haiku or sonnet)
      ↓ sentence chunks
  → tts/router.py
      → ElevenLabs (primary, pcm_22050 streaming)
      → Cartesia (fallback on TTSError)
      → pyttsx3 (last resort)
      ↓
  → sounddevice playback
```

## Speech state machine

```
IDLE → LISTENING → THINKING → SPEAKING → FOLLOWUP → IDLE
                                  ↑
                            barge-in (BargeInGate)
                            cuts TTS, goes to LISTENING
```

Key components:

- `speech_state.py` — BargeInGate (1.5s grace, 450ms sustained speech, ~480 RMS floor)
- `events.py` — EventBus, ALL state changes via `set_pipeline_state()`
- `ui/face.py` — orb connects via `connect_pipeline_state()`, 50 ms debounce
- `runtime.py` — orchestrator ↔ pipeline interrupt hooks
- `_await_followup_utterance()` — 5 s window, 3-miss forgiveness

## Orchestrator

- FIFO queue, max depth 3
- Stale-drop at 60 s
- `cancel_current()` — stops TTS + Claude stream + sets IDLE + calls `TurnTrace.cancel()`
- `_mark_speaking()` — wired to TurnTrace `tts_audio_started`
- EventBus fires on every state change → SSE push to dashboard

## Self-improvement engine

```
Every turn:
  orchestrator → TurnTrace (write queue) → SQLite turns/events

On demand / nightly (APScheduler, future):
  reflect.py → compute_period_metrics() → haiku judge
  → suggestions table → Jarvis Thinks dashboard view

Weekly (future Stage 4):
  research.py → PyPI version check + web_search → suggestions
```

Decoupled: `improvement/` has ZERO imports from `pipeline.py` or `registry.py`.
Hooks go the other direction (pipeline calls trace methods).

DB tables: `sessions`, `turns`, `events`, `corrections`, `lessons`, `suggestions`, `baselines`

## Dashboard views (11)

1. Overview — quick-action panel, system status, music card
2. Activity — real-time SSE event feed with timestamps
3. Tools — registered tools with risk tiers
4. Memory — SQLite browser, notes, variables
5. Contacts — Google Contacts, searchable
6. Email — unread Gmail, Claude-drafted replies
7. Calendar — day view, timeline, Zoom links
8. Plugins — calendar_reminder, morning_briefing
9. Hub — integrations config (Anthropic, Google, Brave, Slack, GitHub, ElevenLabs, Cartesia)
10. **Jarvis Thinks** — self-improvement suggestions, Accept/Dismiss/Send to Cursor
11. Settings — budget, models, voice picker, VAD tuning, all wired to `config.json`

## Memory layout (user data, frozen .app mode)

```
~/Library/Application Support/Jarvis/   (Mac)
%APPDATA%/Jarvis/                        (Windows)
  ├── .env                    API keys
  ├── config.json             all settings
  ├── memory/
  │   ├── variables.db        SQLite WAL
  │   ├── semantic_index.db   FTS5 (delete if corrupt)
  │   ├── notes/              markdown notes
  │   ├── profile.md          durable learned facts
  │   └── diary/              auto-logged turns
  └── google_token.json       OAuth token
```

## Tool risk tiers

| Tier | Confirm? | Voice prompt? | Example |
|------|----------|---------------|---------|
| READ_ONLY | No | No | get_current_time, get_weather |
| MODERATE | UI modal | No | music_play, find_file |
| HIGH_RISK | UI modal | Yes (TTS) | send_email, send_slack_message |

## LLM routing

| Trigger | Model | Why |
|---------|-------|-----|
| ≤20 words, simple query | claude-haiku-4-5 | Fast, cheap |
| >20 words or complex | claude-sonnet-4-6 | Smart |
| Explicit escalate tool | claude-sonnet-4-6 | User-triggered |
| Improvement judge/suggest | claude-haiku-4-5 | Keep cost low |

## Platform matrix

| Feature | Mac | Windows |
|---------|-----|---------|
| STT | mlx-whisper (`adapters/stt.py`) | faster-whisper (`adapters/stt.py`) |
| Orb UI | PyQt6 ✅ | PyQt6 ✅ (Mac-tuned) |
| App bundle | .app (PyInstaller) | .exe (`build_windows.bat`) |
| Music | AppleScript + Music.app | Spotify URI |
| Device control | AppleScript | PowerShell (Oliver) |
| Dashboard window | PyWebView child process | Edge/Chrome --app mode |
| Launch at login | LaunchAgent plist | Not implemented (`login_item.py` macOS-only) |
| User data | ~/Library/Application Support/Jarvis/ | %APPDATA%/Jarvis/ |

## Coordinated files (message other dev before editing)

`pipeline.py` · `main.py` · `config.py` · `tools/registry.py` · `speech_state.py`
