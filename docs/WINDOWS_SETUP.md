# Windows Setup & Gotchas

Hard-won notes for running Jarvis on Windows. Pairs with `docs/PLATFORM.md`
(one codebase, adapter layer). The single biggest lever is **the Python version**.

## Use Python 3.11 or 3.12 — not 3.14

Several native deps ship prebuilt wheels for 3.11/3.12 but **not** 3.14, where
they need MSVC Build Tools and otherwise fail to install:

| Package | On 3.11/3.12 | On 3.14 |
|---------|--------------|---------|
| `pyaudio` | wheel installs | build fails → falls back to sounddevice |
| `webrtcvad` | wheel installs | build fails → **RMS-energy VAD only** |
| `pynput` (hotkey) | installs | may fail → global hotkey disabled |

`webrtcvad` matters most: without it, voice activity detection falls back to a
crude RMS-energy check that's far more likely to mis-fire (e.g. the barge-in
self-trigger). Getting `webrtcvad` installed materially improves smoothness.

```powershell
# from the repo root
py -3.11 -m venv .venv         # or -3.12
.\run.ps1                       # sets PYTHONUTF8, installs requirements, launches
```

`run.ps1` already exports `PYTHONUTF8=1` (the banner emojis crash the default
Windows console encoding without it) and warns instead of failing if a native dep
won't build.

## API keys

Copy `.env.example` → `.env` and set at least `ANTHROPIC_API_KEY`. Optional:
`ELEVENLABS_API_KEY` (primary voice), `CARTESIA_API_KEY` (fallback voice),
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (calendar/gmail/contacts).

## Gotchas seen in testing

- **Stray Python processes / port 7777** — if things feel stuck, check Task
  Manager for leftover `python.exe` from a previous run holding the dashboard port.
- **STT backend** — `stt_backend` defaults to `mlx` (macOS); on Windows the STT
  adapter auto-falls back to `faster-whisper`. Pin `"stt_backend": "faster"` in
  `config.json` to skip the fallback log. `stt_model` `small`/`small.en` is more
  accurate but slower than `base.en`.
- **Apps & media** — `open_app` works (PowerShell `Start-Process`). Music/Photos/
  Podcasts *control* is macOS-only; on Windows Jarvis can open Spotify but not
  control playback yet (see `docs/PLATFORM.md` → `AppControl` adapter).
- **Diary memory** — pre-fix refusals saved to `memory/diary/` are now filtered
  from recall (`memory/semantic.py`), but old entries still exist on disk; trim +
  reindex from the dashboard if behaviour regresses.

## Build a standalone .exe

```powershell
.\build_windows.bat      # → dist\Jarvis\Jarvis.exe ; user data in %APPDATA%\Jarvis\
```
