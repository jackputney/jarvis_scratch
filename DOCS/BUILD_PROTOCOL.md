# Build Protocol

<!-- AGENTS: Read this before touching any coordinated file -->
<!-- Last updated: 2026-06-22 -->

## The golden rule

If it only works on your machine, it doesn't ship.

## Branch strategy

```
main (protected — always working on both platforms)
  ├── jack/sprint-N       Jack's features
  ├── jack/self-improve   Self-improvement engine
  └── oliver/sprint-N     Oliver's features
```

## Rules

| Rule | Detail |
|------|--------|
| Never push to main directly | Both devs |
| Push your branch every session | Even if incomplete |
| Cross-review only | Jack merges Oliver's PRs, Oliver merges Jack's |
| No self-merge | Ever |
| Coordinate before editing core files | Message first |
| New tools in own file | `tools/<name>.py` |
| Run pytest before every push | Baseline: 413 |

## Coordinated files — message other dev before editing

`pipeline.py` · `main.py` · `config.py` · `tools/registry.py` · `speech_state.py`

## Commit format

```
feat(scope): description
fix(scope): description
chore(scope): description
```

Scopes: `voice` `dashboard` `tools` `hub` `memory` `orb` `tests` `docs` `improvement` `chore`

Examples:

```
feat(tools): add get_current_time as READ_ONLY tool
fix(tts): use pcm_16000 for ElevenLabs free tier compatibility
feat(improvement): Stage 1 instrumentation — trace, signals, hooks
fix(orb): single source of truth for state via EventBus
```

## PR description template

```
## What this does
[One sentence]

## Files changed
-

## Tested on
- [ ] macOS (Jack)
- [ ] Windows (Oliver)

## How to test
1.

## Risks / things to watch
-

## Platform guards added?
- [ ] Yes  /  [ ] N/A (pure Python)

## Tests
- [ ] pytest passing (N tests)
```

## Merge order (end of every sprint)

1. Jack: rebase branch on main → run tests → open PR
2. Oliver: review + merge Jack's PR
3. Oliver: rebase his branch on new main → run tests → open PR
4. Jack: review + merge Oliver's PR
5. Both: verify Mac tests pass, Windows tests pass, voice loop works
6. Tag: `git tag v0.X.0 && git push origin v0.X.0`
7. Update `DOCS/PROJECT_STATE.md` + `DOCS/CHANGELOG.md`

## Cross-platform rules

### Platform guards (required)

```python
import platform
if platform.system() == "Darwin":
    # macOS only
if platform.system() == "Windows":
    # Windows only
```

Never put platform-specific imports at module level — they crash on import.

### File paths — always pathlib

```python
# ✅ Correct
from pathlib import Path
downloads = Path.home() / "Downloads" / "file.txt"

# ❌ Wrong
downloads = "~/Downloads/file.txt"
```

### Dependencies — platform markers

```
pywebview ; sys_platform == "darwin"
pywin32 ; sys_platform == "win32"
```

## Daily standup message format

```
working on X / done with Y / blocked on Z
```

Send to the other dev at start of each session.

## When something breaks on the other machine

1. Stop — don't push more code
2. Message the other dev immediately
3. Create a GitHub issue: what broke, which OS, which commit
4. Person who wrote the breaking code fixes it
5. Fix goes on a `hotfix/` branch, merged by the other person
6. Update `BUILD_PROTOCOL.md` if a new rule is needed
