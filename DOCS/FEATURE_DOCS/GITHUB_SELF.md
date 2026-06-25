# GitHub Self (Read + Write)

Jarvis can read and write its own source repository (`jackputney/jarvis_scratch`) via the GitHub REST API.

## What it does

- **Read:** fetch live code from GitHub main for reflection and voice queries
- **Write:** create branches, files, pull requests, and issues (with confirm gates on high-risk ops)
- **Jarvis Thinks:** accepting a suggestion opens a GitHub issue + tracking branch automatically

## Files

| File | Role |
|------|------|
| `tools/github_self.py` | GitHub API client (read + write tools) |
| `tools/registry.py` | Tool registration and risk tiers |
| `hub/integrations.json` | Hub entry `github_self` |
| `improvement/reflect.py` | Accept flow → branch + issue |
| `memory/db.py` | `suggestions.github_issue_url` column |

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

Fine-grained token on `jackputney/jarvis_scratch`:

| Scope | Needed for |
|-------|------------|
| Contents | Read + write files |
| Issues | Create issues and comments |
| Pull requests | Open PRs |
| Metadata | Read (always) |

Classic token alternative: scope `repo` (full control of private repos).

## Read tools (READ_ONLY)

| Tool | Description |
|------|-------------|
| `read_own_file(path)` | File contents (50KB cap) |
| `list_own_files(directory)` | Paths in a directory |
| `search_own_code(query)` | Code search, top 5 |
| `get_own_commits(limit)` | Recent commits |
| `get_own_issues(state)` | Issue list |

## Write tools

| Tool | Risk tier | Description |
|------|-----------|-------------|
| `create_own_branch(name, from_branch="main")` | MODERATE | Create branch from ref |
| `create_own_issue(title, body, labels=[])` | MODERATE | Open an issue |
| `comment_own_issue(number, body)` | MODERATE | Comment on issue |
| `create_own_file(path, content, message, branch="main")` | **HIGH_RISK** | Create/update file (confirm required) |
| `create_own_pr(title, body, head, base="main")` | **HIGH_RISK** | Open pull request (confirm required) |

### Voice examples

- "Create a branch called `feature/voice-fix`" → `create_own_branch`
- "Open an issue about the TTS fallback" → `create_own_issue`
- "What are the open issues?" → `get_own_issues`
- "Open a PR from `feature/x` to main" → `create_own_pr`

## Jarvis Thinks accept flow

When you click **Accept** on a suggestion:

1. Status → `accepted`
2. Branch `jarvis/improvement/{suggestion_id}` created on GitHub
3. If `proposed_change` references a file, current GitHub contents are attached
4. Issue opened: `[Jarvis Suggests] {title}` with body, proposed change, and evidence
5. Issue URL stored in `suggestions.github_issue_url`

## Gotchas

| Topic | Detail |
|-------|--------|
| Confirm gates | `create_own_file` and `create_own_pr` require dashboard/voice confirm |
| Rate limits | 403/429 returns a clear message; PAT required |
| Branch vs local | GitHub reads/writes remote `main`, not uncommitted local edits |
| PAT expiry | Rotate in Hub when write calls start failing |
| Secrets | `GITHUB_PAT` is never logged |

## How to test

```bash
pytest tests/test_github_self.py -v
```
