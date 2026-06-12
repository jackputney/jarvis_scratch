# Jarvis

A fast, conversational voice AI assistant for macOS (Apple Silicon). Local wake word, Metal-accelerated STT, Claude for reasoning, streaming TTS, a minimal animated face UI, token-cost budgeting, and a localhost control dashboard.

## The only thing you need to do

1. **Add your Anthropic API key** to `.env`:

   ```bash
   cp .env.example .env        # then open .env and paste your key
   # ANTHROPIC_API_KEY=sk-ant-...
   ```

2. **Run it:**

   ```bash
   ./run.sh
   ```

   `run.sh` installs PortAudio, creates the virtualenv, installs dependencies, and launches Jarvis. (Already set up? `python main.py` works too.)

Then say **"hey Jarvis"** to activate and watch the orb in the top-right corner. The control dashboard opens at **http://127.0.0.1:7777**.

> The trigger phrase is the openWakeWord pretrained model **"hey Jarvis"** — the bare word "Jarvis" alone will not wake it. On first run the wake model (~1–2 MB) downloads automatically; offline, it fails with a clear error rather than hanging.

## Control dashboard

A localhost-only Flask panel at **http://127.0.0.1:7777** (started automatically, no extra process):

- **Status bar** — pipeline state, mute, uptime, active models.
- **Spend** — today / week / month vs budget, with a daily-budget bar. Budgets editable inline.
- **Conversation log** — last 50 exchanges with model, latency, and cost.
- **Memory** — edit variables and notes (add / edit / delete).
- **Settings** — wake word on/off, confirm-before-execute, Whisper model, fast/smart models, routing threshold, TTS voice. Saved to `config.json` and applied live (no restart).
- **Talk box** — type to Jarvis and get a text reply (same pipeline, minus speech).
- **Tool confirm modal** — when Jarvis wants to run a high-risk tool (`send_email`, sheet writes), a popup appears here with Allow/Deny. Auto-denies after 30s if you do not respond. Stop on the orb cancels a pending confirm.

All `/api/*` endpoints bind to `127.0.0.1` only.

<!-- Dashboard screenshots: add screenshots/dashboard.png here. -->

## Budgets

Jarvis logs the **exact** token usage from each Claude response (never estimated) to `memory/variables.db` and enforces your budget before every call:

- At **80%** of the daily budget it speaks a one-time heads-up.
- At **100%** it hard-stops API calls and tells you to raise the budget in the dashboard. There is no voice override.

The orb turns **amber** at 80% and **red** when capped. Pricing: Haiku $1/$5 per Mtok (in/out), Sonnet $3/$15.

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4)
- Python 3.11+
- Anthropic API key (required)
- Cartesia API key (optional — falls back to pyttsx3 if unset)

## API keys

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
CARTESIA_API_KEY=sk_car_...    # optional

# Google Calendar / Gmail / Sheets (optional)
GOOGLE_CLIENT_ID=175840773134-....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...   # env only — never commit
```

Never commit `.env`. It is in `.gitignore`.

On first use of a Google tool, Jarvis opens your browser for OAuth sign-in once and stores a refresh token in `memory/google_token.json` (also gitignored).

## Configuration

Edit `config.json` (also gitignored — safe to customise):

| Key | Default | Description |
|-----|---------|-------------|
| `claude_model_fast` | `claude-haiku-4-5` | Model for short/simple queries (≤20 words) |
| `claude_model_smart` | `claude-sonnet-4-6` | Model for complex queries |
| `routing_word_threshold` | `20` | Word count below which fast model is used |
| `whisper_model` | `tiny` | mlx-whisper model size (`small` is more accurate but slower) |
| `cartesia_voice_id` | British male | Cartesia voice UUID |
| `confirm_before_execute` | `true` | Dashboard confirm for high-risk tools only (see below) |
| `ui_enabled` | `true` | Show the orb face widget |
| `wake_word` | `hey_jarvis` | openWakeWord model name (spoken trigger: "hey Jarvis") |
| `wake_word_enabled` | `true` | Listen for the wake word (off = dashboard text only) |
| `memory_inject_last_n_notes` | `5` | Notes injected into each prompt |
| `daily_budget_usd` | `2.00` | Hard daily spend cap (USD) |
| `monthly_budget_usd` | `40.00` | Monthly spend reference (USD) |
| `google_client_id` | `""` | Optional fallback if `GOOGLE_CLIENT_ID` is not in `.env` |
| `conversation_history_turns` | `8` | Prior user/assistant turns sent to Claude (in-memory, per session) |
| `conversation_history_max_chars` | `6000` | Character cap on injected history (limits input-token cost) |
| `confirm_timeout_sec` | `30` | Auto-deny high-risk tool confirms after this many seconds |

`GOOGLE_CLIENT_SECRET` lives in `.env` only — never in `config.json`.

All of these are also editable live from the dashboard Settings panel.

## Architecture

```
wake word (openwakeword, daemon thread)
    ↓ threading.Event
audio capture + VAD trim (pyaudio + webrtcvad)
    ↓ raw PCM
transcription (mlx-whisper, tiny, Metal)
    ↓ text
route: word count + keywords → haiku or sonnet
    ↓
Claude API (tools= for function calling)
    ↓ tool_use blocks
tools/registry.py dispatch loop
    ↓ final reply text
Cartesia streaming TTS → pyaudio (first audio ~150ms)
    ↓
UI state: IDLE → LISTENING → THINKING → SPEAKING
```

## Tools available to Jarvis

| Tool | What it does |
|------|-------------|
| `open_app` | Open any macOS app via AppleScript |
| `web_search` | DuckDuckGo instant answer lookup |
| `set_variable` | Persist a personal fact (e.g. `home_city=London`) |
| `get_variable` | Retrieve a stored fact |
| `write_note` | Save a Markdown note to `memory/knowledge/` |
| `read_note` | Read a note by title |
| `get_calendar_events` | Upcoming Google Calendar events (read-only) |
| `get_todays_schedule` | Today's calendar, formatted for speech |
| `get_unread_emails` | Unread Gmail summaries (read-only) |
| `search_emails` | Search Gmail by query (read-only) |
| `send_email` | Send email via Gmail (**confirm required**) |
| `read_sheet` | Read a Google Sheets range (read-only) |
| `append_row` | Append a row to a sheet (**confirm required**) |
| `update_cell` | Update one sheet cell (**confirm required**) |

Set `confirm_before_execute: false` in `config.json` to skip dashboard confirms entirely (not recommended for `send_email` or sheet writes).

When confirm is on, **low-risk tools run immediately** (`write_note`, `set_variable`, `open_app`). **High-risk tools** (`send_email`, `append_row`, `update_cell`) show a dashboard Allow/Deny modal and auto-deny after `confirm_timeout_sec`. Press **Stop** on the orb to cancel a pending confirm without freezing the voice loop.

For better speech recognition, set `"whisper_model": "small"` in `config.json` or the dashboard Settings panel.

## Memory

Two-tier local storage — never leaves your machine:

- **`memory/variables.db`** — SQLite key-value store for structured facts injected into every prompt.
- **`memory/knowledge/`** — Markdown files (one per topic); the 5 most recently modified are injected into every prompt.

Both paths are gitignored.

## UI states

| State | Animation |
|-------|-----------|
| IDLE | Static orb |
| LISTENING | Slow breathing pulse (0.9×–1.1× scale, 1.5s cycle) |
| THINKING | Fast rotating arc around the orb |
| SPEAKING | Ripple rings expanding from centre |

Click the orb to toggle mute. Drag the window to reposition it.

## Headless mode

Set `"ui_enabled": false` in `config.json` to run without the Qt window (useful for SSH or server environments).

## Troubleshooting

**`portaudio` not found** — install it first: `brew install portaudio`

**`openwakeword` model download fails** — Jarvis downloads the wake model automatically on first run. If it fails (no internet), you will see a clear error. To fetch it manually once online, run `python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis_v0.1'])"`.

**No audio output** — check that your default audio output device is set correctly in macOS System Settings → Sound.

**Cartesia TTS sounds robotic** — ensure `CARTESIA_API_KEY` is set; pyttsx3 fallback is lower quality by design.
