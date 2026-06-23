# GitHub Self-Read

Jarvis can read its own source repository (`jackputney/jarvis_scratch`) via the GitHub REST API. All tools are **read-only** — no push, PR, or write operations.

## What it does

- Lets Claude and `reflect.py` fetch **current code from GitHub main**, not stale local guesses
- Powers five voice/dashboard tools registered as `READ_ONLY`
- Used by Jarvis Thinks when a tool's error rate exceeds 20%: reads `tools/<name>.py`, passes numbered source to haiku, and embeds a code snippet in `proposed_change`

## Files

| File | Role |
|------|------|
| `tools/github_self.py` | API client + five tool functions |
| `tools/registry.py` | Tool registration |
| `hub/integrations.json` | Hub entry `github_self` |
| `improvement/reflect.py` | Reads tool source before high-severity suggestions |
| `config.py` / `config.json` | `github_repo`, `github_branch` (not the PAT) |

## Configuration

**.env only (never config.json):**

```bash
GITHUB_PAT=ghp_your_token_here
```

**config.json:**

```json
{
  "github_repo": "jackputney/jarvis_scratch",
  "github_branch": "main"
}
```

## PAT setup

1. GitHub → Settings → Developer settings → Personal access tokens
2. Fine-grained token recommended: **Contents: Read-only** on `jackputney/jarvis_scratch`
3. Classic token alternative: scope `repo` (read) or public-repo read if the repo is public
4. Add `GITHUB_PAT` to `.env` or Hub → GitHub Self-Read

## Tools

### `read_own_file(path)`

```python
read_own_file("tools/web.py")
# → file contents as string (max 50KB, truncated with notice if larger)
```

### `list_own_files(directory="")`

```python
list_own_files("tools")
# → newline-separated paths under tools/
```

### `search_own_code(query)`

```python
search_own_code("def web_search")
# → top 5 matches with path, snippet, URL
```

### `get_own_commits(limit=10)`

```python
get_own_commits(5)
# → recent commits on github_branch
```

### `get_own_issues(state="open")`

```python
get_own_issues("open")
# → issue list (pull requests excluded)
```

## reflect.py integration

When a tool in `top_tools` has error rate **> 10%** (metric threshold) and **> 20%** (high severity):

1. `resolve_tool_source_path(tool_name)` tries `tools/<name>.py` then code search
2. `_haiku_tool_suggestion()` sends numbered source + telemetry to haiku
3. `proposed_change` includes a fenced snippet of the current GitHub file

If `GITHUB_PAT` is missing, reflection continues with generic advice (no crash).

## Gotchas

| Topic | Detail |
|-------|--------|
| Rate limits | Unauthenticated search is very limited; PAT required. 403/429 returns a clear message |
| 50KB cap | Large files are truncated; notice appended |
| Branch | Reads `github_branch` from config (default `main`), not local uncommitted edits |
| PAT expiry | Expired tokens return 401/403 — rotate in Hub |
| Secrets | `GITHUB_PAT` is never logged or stored in config.json |

## How to test

```bash
pytest tests/test_github_self.py -v
```

With a real PAT:

```bash
export GITHUB_PAT=ghp_...
python -c "from tools.github_self import read_own_file; print(read_own_file('README.md')[:200])"
```
