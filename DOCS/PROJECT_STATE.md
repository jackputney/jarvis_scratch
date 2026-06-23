# Project State

<!-- AGENTS: Update this file every session. Takes 2 minutes. -->
<!-- Last updated: 2026-06-18 | Updated by: Cursor acting for Jack -->

## Quick status

| Item | Value |
|------|-------|
| Tests | 423 passing |
| Main tag | v0.4.0 |
| Pending merge | jack/self-improve → v0.5.0 |
| Jack branch | jack/self-improve |
| Oliver branch | oliver/sprint-4 (merged at v0.4.0) |

## What's on main (v0.4.0)

- Voice pipeline: wake → STT → Claude → ElevenLabs TTS
- Speech state machine: BargeInGate (0.48/2 hits), follow-up window with 3-miss forgiveness, `_clear_interrupt()` cancel reset
- ElevenLabs retry loop, pcm_16000 free-tier fix
- Cross-platform voice reliability (Oliver): tighter VAD defaults, config caching, Windows .exe installer, `build_windows.bat`
- Self-improvement Stage 1: TurnTrace, signals, 7-table schema, stats API wired into Oliver's TTS retry + orchestrator

## What's on jack/self-improve (pending merge → v0.5.0)

- Stop button full cancel path: TTS + Claude stream + IDLE + `TurnTrace.cancel()`
- Orb state single source of truth via EventBus, 50 ms debounce
- Jarvis Thinks dashboard view: `reflect.py`, haiku suggestions, severity cards, Accept/Dismiss/Send to Cursor, 30-min refresh
- GitHub self-read: five READ_ONLY tools + reflect.py reads live repo code for tool-fix suggestions
- All of v0.4.0 included

## Active branches

| Branch | Owner | Status |
|--------|-------|--------|
| jack/self-improve | Jack | Push ready — Oliver to review + merge |
| oliver/sprint-4 | Oliver | Merged at v0.4.0 |

## Known issues

| Issue | Severity | Status |
|-------|----------|--------|
| jack/self-improve not merged to main yet | High | Waiting Oliver review |
| Self-improvement Stage 2–4 not started | Medium | Next after v0.5.0 |
| Abort trap on Ctrl+C | Low | Cosmetic — PyQt6 shutdown quirk |
| Home Assistant tools not implemented | Low | Hub UI exists, no tools |
| Notion out of free blocks | Low | Migrating to DOCS/ markdown |
| ElevenLabs free tier 10k chars/month | Low | Upgrade for daily use |

## What's working

- Voice loop, barge-in, follow-up window
- Stop button (cancels everything)
- Orb state synced to pipeline
- Dashboard: 10 views including Jarvis Thinks
- ElevenLabs TTS: 4-voice picker, live reload, Cartesia fallback
- 61 tools: device control, Google, media, Slack, GitHub, GitHub self-read, music, email triage, calendar, pitch deck, weather
- .app launcher (Mac), .exe installer (Windows)
- Onboarding wizard, global hotkey Ctrl+Shift+Space
- Launch at login (Mac LaunchAgent, Windows registry)
- Self-improvement: TurnTrace recording every turn

## Next actions

1. Oliver: review jack/self-improve PR → merge → tag v0.5.0
2. Both: Self-improvement Stage 2 — golden set + LLM judge
3. Let Jarvis Thinks run for a day, check first real suggestions

## Repo

https://github.com/jackputney/jarvis_scratch
