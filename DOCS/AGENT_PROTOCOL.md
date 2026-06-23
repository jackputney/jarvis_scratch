# Agent Protocol

<!-- This file is for AI agents (Claude, Cursor, Copilot, GPT) -->
<!-- Read this FIRST before making any changes to this repo -->
<!-- Last updated: 2026-06-22 -->

## Who you are working for

This repo is maintained by two developers:

| Developer | Machine | GitHub |
|-----------|---------|--------|
| Jack | macOS | jputney667 |
| Oliver | Windows | Odugan405 |

Before doing anything, identify which developer you are acting for.

## Read these files before starting any session

In this order:

1. `DOCS/PROJECT_STATE.md` — current branch, tests, what's broken right now
2. `DOCS/ARCHITECTURE.md` — real file structure, how systems connect
3. `DOCS/CHANGELOG.md` — what changed recently and WHY
4. `DOCS/BUILD_PROTOCOL.md` — branch rules, commit format, PR template

Do NOT rely on memory from previous sessions. Always read these files fresh.

## How to sign your work

Every change you make must be signed. Format:

```
[Agent: Claude/Cursor — acting for Jack/Oliver — YYYY-MM-DD]
```

Add this to:

- `DOCS/CHANGELOG.md` — required for every change
- Any section of DOCS/ you significantly update

## Required: Update DOCS/ after every change

After any code change, you MUST update:

1. **DOCS/CHANGELOG.md** — add an entry (newest first):

   ```
   ### YYYY-MM-DD — [what changed] — [who]
   [Agent: Cursor — acting for Jack — YYYY-MM-DD]

   **Branch:** branch-name | **Tests:** N passing

   **What changed:**
   - file.py — what and why

   **Why:** One sentence.

   **Watch out for:** Gotchas for the other dev.
   ```

2. **DOCS/PROJECT_STATE.md** — update if:
   - Test count changed
   - Branch changed
   - A known issue was fixed
   - A new known issue was found

3. **DOCS/FEATURE_DOCS/<feature>.md** — update if you changed how a feature works, added gotchas, or changed file locations

## What you are allowed to edit

| File/Folder | Allowed? | Notes |
|------------|---------|-------|
| DOCS/CHANGELOG.md | ✅ Always | Add entries, never edit existing ones |
| DOCS/PROJECT_STATE.md | ✅ Yes | Keep current |
| DOCS/FEATURE_DOCS/ | ✅ Yes | Add/update your developer's features |
| .cursorrules (root) | ⚠️ Careful | Only update ACTIVE STATE section each sprint |
| DOCS/BUILD_PROTOCOL.md | ❌ No | Only humans edit this |
| DOCS/AGENT_PROTOCOL.md | ❌ No | Only humans edit this |

## What you are NOT allowed to do

- Do not delete any existing DOCS/ content
- Do not edit another developer's signed entries
- Do not mark tests as passing unless you ran pytest
- Do not invent file paths — only use paths confirmed from the repo
- Do not edit coordinated files without flagging it:
  `pipeline.py` · `main.py` · `config.py` · `tools/registry.py` · `speech_state.py`
- Do not push to main directly
- Do not self-merge PRs

## Coordinated files — flag before touching

If you need to edit any of these, say so explicitly before changing them and confirm the other developer has been notified:

```
⚠️ About to edit pipeline.py — coordinated file.
Oliver should be aware before this merges.
```

## Cross-platform guards — always add these

```python
# macOS-specific code
if platform.system() == "Darwin":
    # AppleScript, mdfind, mlx-whisper, PyQt6 orb, LaunchAgent

# Windows-specific code
if platform.system() == "Windows":
    # win32api, registry, Edge WebView2, PowerShell
```

Never put platform-specific imports at module level.
Always use `pathlib.Path` for file paths, never string concatenation.

## Self-improvement engine — special rules

The `improvement/` package is intentionally decoupled:

- It has ZERO imports from `pipeline.py` or `registry.py`
- Hooks go the other way: pipeline calls `trace.record_*()` methods
- The TurnTrace write queue is non-blocking — never put I/O in the hot path
- Use `claude-haiku-4-5` for judge/suggest jobs — never sonnet (cost)

## Testing

Always run pytest before committing:

```bash
pytest                    # full suite
pytest tests/improvement/ # just improvement tests
```

Current baseline: **413 tests passing**

Never submit code that drops this count without explanation.

## Session startup checklist

Before writing any code:

- [ ] Read DOCS/PROJECT_STATE.md
- [ ] Read DOCS/CHANGELOG.md (last 3 entries minimum)
- [ ] Identify which developer I'm acting for
- [ ] Check which files are coordinated and if I need to flag anything
- [ ] Confirm which branch I'm on

After writing code:

- [ ] pytest passing
- [ ] DOCS/CHANGELOG.md updated with signed entry
- [ ] DOCS/PROJECT_STATE.md updated if state changed
- [ ] Commit message follows `feat(scope): description` format
