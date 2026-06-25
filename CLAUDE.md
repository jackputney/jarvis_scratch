# Jarvis — Claude Session Guide

## Project Overview
Personal voice assistant running locally on Mac (Jack) and Windows (Oliver). Speaks to users, uses Claude AI to respond, executes tools, manages automations. Browser dashboard at `localhost:7777`.

**Tech stack:** openwakeword → faster-whisper/mlx-whisper → Claude → Cartesia TTS. Flask + SSE dashboard, SQLite memory, PyQt6 orb UI (Mac).

Key files and folders:
- `main.py` · `pipeline.py` · `config.py` · `conversation.py` · `costs.py` · `events.py` · `preflight.py`
- `orchestrator/` · `memory/` · `hub/` · `llm/` · `tools/` · `plugins/` · `tts/` · `dashboard/` · `ui/`

**Model routing:** word count threshold → haiku (fast) or sonnet (smart), configurable in `config.json`.  
**Budget:** daily + monthly hard caps enforced before every Claude call.  
**Tests:** 238 passing — never go below this. Run `pytest` before finishing any session.

## Collaborators
- **Oliver** (you) — oliverdugan5@gmail.com · branch: `oliver/sprint-2` (in progress)
- **Jack Putney** — Mac dev · branch: `jack/sprint-2` (PR open, waiting Oliver review)

## Sprint 3 targets
- Jack: Playwright browser automation, video analysis, iMessage
- Oliver: Twilio calls, AI phone agent

---

## Session Protocol

### START of every session — do this before touching any files:

1. Fetch the shared Notion context page:
   ```
   Notion page ID: 382f382154d28131918ee365a71c3f17
   URL: https://app.notion.com/p/Cursor-Claude-Context-382f382154d28131918ee365a71c3f17
   ```
2. Read what Jack is actively working on — **avoid those files**.
3. Note any open decisions, blockers, or context from the last session.

### END of every session (or after any significant decision):

Update the same Notion page (`382f382154d28131918ee365a71c3f17`) with:
- **What you did** — files changed, features added/fixed
- **What you decided** — architectural or design choices made
- **Safe to touch** — areas with no active work
- **Unsafe to touch** — files Oliver or Jack are mid-change on
- **Open questions** — anything unresolved for next time

---

## How to Use This Protocol in Practice

Claude (Cursor/Claude Code) should run the following at session start:
```
Read Notion page 382f382154d28131918ee365a71c3f17 and summarize:
what is Jack currently working on, and what files should I avoid?
```

And at session end:
```
Update Notion page 382f382154d28131918ee365a71c3f17 with a session summary:
[what was done, decisions made, safe/unsafe files]
```

> **⚠️ Notion access setup (one-time):** The Notion integration currently only has access to Oliver's workspace.
> For Claude to read/write this page automatically, Jack needs to add the integration to his workspace:
> 1. Jack goes to **Notion Settings → Connections**
> 2. Finds and adds the integration named **"Cowork"** (integration ID: `1f8d872b-594c-80a4-b2f4-00370af2b13f`)
> 3. Once added, the page will be fully readable and writable by Claude in Cowork sessions

---

## Rules

**Files requiring coordination — message the other dev before editing:**  
`pipeline.py` · `main.py` · `config.py` · `tools/registry.py`

**Git:**
- Never push to `main` directly
- Push your branch every session
- Cross-review only: Jack merges Oliver's PRs, Oliver merges Jack's
- Commit format: `feat(scope): description`
- Scopes: `voice` · `dashboard` · `tools` · `hub` · `memory` · `orb` · `tests` · `docs`

**Tools:** every new tool gets its own file under `tools/`, registered in `registry.py` with a risk tier (READ_ONLY / MODERATE / HIGH_RISK). Type hints + docstring + risk tier comment required.

**Cross-platform (critical):**
- macOS code: `if platform.system() == 'Darwin':` — Windows: `if platform.system() == 'Windows':`
- Never platform-specific imports at module level — they crash on import on the other OS
- Always `pathlib.Path` for file paths, never string concatenation

**Known issues:**
- `semantic_index.db` corrupts on dirty shutdown → `rm -f memory/semantic_index.db*` to fix
- Abort trap on Ctrl+C — cosmetic, ignore it
