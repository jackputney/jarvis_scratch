# Platform Strategy — one codebase, adapter layer, per-OS builds

> **Status:** proposal + first proof-of-concept (STT adapter landed). Needs Jack's
> sign-off on the boundary before we migrate the remaining edges, since several
> live in macOS-owned files.

## TL;DR

Jarvis is a **cross-platform app with leaky seams**, not a Mac app that needs a
fork. Of ~75 production modules, only ~13 touch the OS, and three of those already
ship Windows **and** macOS implementations side by side. The fix is to **formalize
a thin adapter layer**, not split the repo.

**Decision: do _not_ fork.** Keep one shared core; isolate OS-specific code behind
adapters; separate only the **build + environment** per platform.

Why not a fork:
- The shared core (LLM, orchestrator, memory, tools, prompts, and the upcoming
  **calls + contacts** feature) is platform-agnostic — a fork would duplicate it
  to isolate ~13 files, then build every new feature twice.
- Parity between two codebases can only be kept by hand (Notion/GitHub). It will
  drift. Shared code keeps parity automatically.

## What's shared vs platform-specific

**🟢 Shared core (~80%, never branch on OS):** `llm/`, `orchestrator/`, `memory/`,
`hub/`, `tts/elevenlabs.py` + `tts/router.py`, most of `tools/` (gmail, calendar,
contacts, drive, sheets, slack, github, weather, web, time), `conversation.py`,
`costs.py`, `events.py`, dashboard app logic. **Calls / AI phone agent lands here.**

**🟡 Platform edges (~13 files):**

| File | Concern | Today |
|------|---------|-------|
| `tools/device_control.py` | volume/mute/brightness/DND | ✅ already dual (PowerShell + osascript) |
| `pipeline.py` + `tts/cartesia.py` | mic in / PCM out / STT | mlx↔faster, sounddevice↔pyaudio |
| `tools/system.py`, `tools/media.py`, `tools/music.py` | open app / media / music | mixed; music + photos/podcasts macOS-only |
| `tools/login_item.py` | launch at login | macOS only (launchctl) — **Windows gap** |
| `dashboard/window.py` | app window | pywebview ↔ Edge `--app` ✅ |
| `paths.py` | user-data dirs | ✅ already abstracted — the model to copy |
| `ui/face.py` | orb | PyQt6 (runs on Windows); Mac-tuned |

**🔴 Real Windows gaps to fill:** launch-at-login (Task Scheduler/Startup), music
playback control, Photos/Podcasts equivalents.

## The adapter layer

A package named **`adapters/`** (not `platform/` — that would shadow the stdlib
`platform` module). Each adapter is an interface with a per-OS implementation,
selected **once** at startup instead of scattered `if platform.system()` checks.

| Adapter | Replaces | macOS / Windows |
|---------|----------|-----------------|
| **`STTBackend`** ✅ done | inline `pipeline._transcribe` | mlx-whisper / faster-whisper |
| `AudioIO` | pipeline audio loop + `cartesia._OutputStream` | sounddevice/pyaudio + sample rate |
| `SystemControl` | `device_control.py` | osascript / PowerShell |
| `AppControl` | `system.py` + `media.py` + `music.py` | AppleScript / Start-Process |
| `LaunchAtLogin` | `login_item.py` | launchctl / Task Scheduler (new) |
| `AppWindow` | `dashboard/window.py` | pywebview / Edge `--app` |
| `Paths` | `paths.py` | already done — keep as the template |

## Build + environment — the separation that _is_ healthy

Same source, different packaging:
- **Per-OS deps:** `requirements-win.txt` (pyaudio, webrtcvad on **Python 3.11**)
  vs `requirements-mac.txt` (mlx*, pyobjc, pywebview).
- **Per-OS build:** `build_windows.bat` / `jarvis_windows.spec` (.exe) vs
  `build_mac.sh` / `jarvis.spec` (.app) — already exist.
- **Pin Python 3.11/3.12 on Windows** so native wheels install — which also gets
  `webrtcvad` working (better VAD → fixes barge-in misfires).

## Proof of concept — `STTBackend` (landed)

First migration, behavior-preserving:
- New `adapters/stt.py`: `STTBackend` protocol + `FasterWhisperBackend` /
  `MlxWhisperBackend`, with `resolve_backend()` (mlx→faster fallback) owning the
  model cache that used to be module globals in `pipeline.py`.
- `pipeline._transcribe` / `warmup_stt` now call `adapters.stt` and never import
  an engine or branch on platform.
- Covered by `tests/test_adapters_stt.py` (resolution + fallback, no model load).

## Suggested migration order

1. ✅ `STTBackend`
2. `AudioIO` (highest user-facing pain — playback/barge-in smoothness)
3. `AppControl` (consolidate `system`/`media`/`music`; fill Windows music)
4. `LaunchAtLogin` (add the Windows implementation)
5. `SystemControl` / `AppWindow` (mostly relabeling existing dual code)

Each step is a behavior-preserving extraction with tests, reviewable on its own.
