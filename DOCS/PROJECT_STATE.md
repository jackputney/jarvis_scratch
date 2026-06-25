# Project State

<!-- AGENTS: Update this file every session. Takes 2 minutes. -->
<!-- Last updated: 2026-06-24 | Updated by: Cursor acting for Oliver -->

## Quick status

| Item | Value |
|------|-------|
| Tests | 423 passing (Mac); ~420 passing on Windows after darwin skips |
| Main tag | **v0.5.0** |
| Branch | `main` at `eced13b` |
| Oliver branch | `oliver/sprint-6` (tracking main, no new commits yet) |
| Jack branch | `jack/self-improve` (merged into v0.5.0) |

## What's on main (v0.5.0)

- Everything from v0.4.0 (voice pipeline, speech state machine, cross-platform voice)
- Oliver sprint-5: VAD barge-in tuning, pcm_22050 TTS, Windows `open_app`, STT adapter, diary-poison filter
- Jack self-improve stack: TurnTrace instrumentation, Jarvis Thinks, GitHub self-read, stop/orb fixes
- Confirm gate `state`/`pipeline_state` normalisation
- `DOCS/` knowledge base + `.cursorrules`

## Active branches

| Branch | Owner | Status |
|--------|-------|--------|
| main | both | v0.5.0 tagged and pushed |
| oliver/sprint-6 | Oliver | Placeholder — next Windows/adapter work |
| Oliver_Jarvis_smarter | Oliver | Unmerged — wake-word barge-in, relevance memory, prompt caching |

## Known issues

| Issue | Severity | Status |
|-------|----------|--------|
| Self-improvement Stage 2–4 not started | Medium | Stage 2 (golden set + judge) is next |
| Windows venv on Python 3.14 | Medium | Recreate with 3.12; `webrtcvad` missing → energy VAD only |
| Adapter layer only has STT | Medium | AudioIO, AppControl, LaunchAtLogin still inline |
| Home Assistant tools not implemented | Low | Hub UI exists, no tools |
| Music playback control Windows gap | Low | open_app works; play/pause macOS-only |
| Abort trap on Ctrl+C | Low | Cosmetic — PyQt6 shutdown quirk |
| ElevenLabs free tier 10k chars/month | Low | Upgrade for daily use |

## What's working

- Voice loop, barge-in (tuned), follow-up window, stop button
- Orb state synced to pipeline via EventBus
- Dashboard: 11 views including Jarvis Thinks
- ElevenLabs TTS: pcm_22050, 4-voice picker, Cartesia fallback
- 61+ tools: device control, Google, media, Slack, GitHub, GitHub self-read, music, email, calendar, pitch deck, weather
- .app launcher (Mac), .exe installer (Windows)
- Onboarding wizard, global hotkey Ctrl+Shift+Space
- Launch at login (Mac LaunchAgent; Windows registry path exists but login_item is macOS-only)
- Self-improvement: TurnTrace recording every turn, Jarvis Thinks suggestions

## Next actions

1. Oliver: recreate Windows venv on Python 3.12; live smoke-test sprint-5 fixes
2. Migrate `AudioIO` adapter (next platform step per PLATFORM.md)
3. Self-improvement Stage 2 — golden set + LLM judge
4. Review `Oliver_Jarvis_smarter` for merge (wake-word barge-in, relevance memory)
5. Update stale docs after each sprint (this file, ARCHITECTURE.md, .cursorrules)

## Repo

https://github.com/jackputney/jarvis_scratch
