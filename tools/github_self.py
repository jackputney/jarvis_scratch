"""Read-only access to Jarvis's own GitHub repository (jackputney/jarvis_scratch)."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("jarvis.tools.github_self")

MAX_FILE_BYTES = 50 * 1024
DEFAULT_REPO = "jackputney/jarvis_scratch"
DEFAULT_BRANCH = "main"


def _load_dotenv() -> None:
    try:
        from config import Config

        Config.load()
    except Exception:  # noqa: BLE001
        pass


def _pat() -> str:
    _load_dotenv()
    return (os.environ.get("GITHUB_PAT") or "").strip()


def _repo_settings() -> tuple[str, str]:
    _load_dotenv()
    try:
        from config import Config

        cfg = Config.load()
        repo = (getattr(cfg, "github_repo", "") or DEFAULT_REPO).strip("/")
        branch = (getattr(cfg, "github_branch", "") or DEFAULT_BRANCH).strip()
        return repo, branch
    except Exception:  # noqa: BLE001
        return DEFAULT_REPO, DEFAULT_BRANCH


def _headers(*, search: bool = False) -> dict[str, str] | None:
    token = _pat()
    if not token:
        return None
    accept = (
        "application/vnd.github.text-match+json"
        if search
        else "application/vnd.github+json"
    )
    return {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _missing_pat_message() -> str:
    return (
        "GitHub PAT not configured. Add GITHUB_PAT to .env "
        "(read-only repo scope). See Hub → GitHub Self."
    )


def _http_error_message(status_code: int, body: str = "") -> str:
    if status_code in (403, 429):
        return (
            f"GitHub API rate limit or access denied (HTTP {status_code}). "
            "Try again later or check your PAT scopes."
        )
    if status_code == 404:
        return f"GitHub: not found (HTTP 404)."
    snippet = (body or "")[:200]
    return f"GitHub API error: HTTP {status_code}" + (f" — {snippet}" if snippet else "")


def _normalise_repo_path(path: str) -> str:
    cleaned = (path or "").strip().lstrip("/")
    if ".." in cleaned.split("/"):
        raise ValueError("Invalid path: parent segments not allowed.")
    return cleaned


def read_own_file_content(path: str, *, ref: str | None = None) -> tuple[str | None, str | None]:
    """Return (content, error). Used by reflect.py and read_own_file."""
    headers = _headers()
    if headers is None:
        return None, _missing_pat_message()
    try:
        import requests
    except ImportError as exc:
        return None, f"GitHub error: {exc}"

    repo, branch = _repo_settings()
    ref = (ref or branch).strip()
    try:
        repo_path = _normalise_repo_path(path)
    except ValueError as exc:
        return None, str(exc)

    url = f"https://api.github.com/repos/{repo}/contents/{quote(repo_path, safe='/')}"
    try:
        resp = requests.get(url, headers=headers, params={"ref": ref}, timeout=15)
    except Exception as exc:  # noqa: BLE001
        logger.debug("GitHub read_own_file request failed: %s", exc)
        return None, f"GitHub request failed: {exc}"

    if resp.status_code >= 400:
        return None, _http_error_message(resp.status_code, resp.text)

    try:
        payload = resp.json()
    except ValueError:
        return None, "GitHub returned invalid JSON."

    if isinstance(payload, list):
        return None, "Path is a directory, not a file. Use list_own_files."

    encoding = payload.get("encoding")
    raw = payload.get("content")
    if encoding != "base64" or not raw:
        return None, "GitHub file is not base64-encoded text."

    try:
        decoded = base64.b64decode(raw, validate=False).decode("utf-8")
    except UnicodeDecodeError:
        return None, "File is not valid UTF-8 text."

    if len(decoded.encode("utf-8")) > MAX_FILE_BYTES:
        truncated = decoded.encode("utf-8")[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
        notice = f"\n\n[Truncated at {MAX_FILE_BYTES // 1024}KB — file is larger on GitHub.]"
        return truncated + notice, None
    return decoded, None


def read_own_file(path: str) -> str:
    """Read a file from the configured repo at HEAD of main (or github_branch)."""
    content, err = read_own_file_content(path)
    if err:
        return err
    return content or ""


def _list_own_files_paths(directory: str = "") -> tuple[list[str], str | None]:
    headers = _headers()
    if headers is None:
        return [], _missing_pat_message()
    try:
        import requests
    except ImportError as exc:
        return [], f"GitHub error: {exc}"

    repo, branch = _repo_settings()
    try:
        repo_path = _normalise_repo_path(directory)
    except ValueError as exc:
        return [], str(exc)

    url = f"https://api.github.com/repos/{repo}/contents/{quote(repo_path, safe='/')}" if repo_path else f"https://api.github.com/repos/{repo}/contents/"
    try:
        resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=15)
    except Exception as exc:  # noqa: BLE001
        return [], f"GitHub request failed: {exc}"

    if resp.status_code >= 400:
        return [], _http_error_message(resp.status_code, resp.text)

    try:
        payload = resp.json()
    except ValueError:
        return [], "GitHub returned invalid JSON."

    if not isinstance(payload, list):
        return [], "Path is a file, not a directory."

    paths = sorted(item.get("path", "") for item in payload if item.get("path"))
    return paths, None


def list_own_files(directory: str = "") -> str:
    """List file paths in a repo directory (single level)."""
    paths, err = _list_own_files_paths(directory)
    if err:
        return err
    return "\n".join(paths) if paths else "No files found."


def search_own_code_results(query: str, *, limit: int = 5) -> tuple[list[dict[str, Any]], str | None]:
    headers = _headers(search=True)
    if headers is None:
        return [], _missing_pat_message()
    if not (query or "").strip():
        return [], "Query is required."

    try:
        import requests
    except ImportError as exc:
        return [], f"GitHub error: {exc}"

    repo, _branch = _repo_settings()
    q = f"{query.strip()} repo:{repo}"
    try:
        resp = requests.get(
            "https://api.github.com/search/code",
            headers=headers,
            params={"q": q, "per_page": max(1, min(limit, 5))},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return [], f"GitHub request failed: {exc}"

    if resp.status_code >= 400:
        return [], _http_error_message(resp.status_code, resp.text)

    try:
        payload = resp.json()
    except ValueError:
        return [], "GitHub returned invalid JSON."

    out: list[dict[str, Any]] = []
    for item in payload.get("items", [])[:limit]:
        matches = item.get("text_matches") or []
        snippet = matches[0].get("fragment", "") if matches else ""
        out.append({
            "path": item.get("path", ""),
            "snippet": snippet,
            "url": item.get("html_url", ""),
        })
    return out, None


def search_own_code(query: str) -> str:
    """Search code in the Jarvis repo; returns top 5 matches."""
    results, err = search_own_code_results(query)
    if err:
        return err
    if not results:
        return "No code matches found."
    lines = []
    for row in results:
        lines.append(f"{row['path']}\n  {row.get('snippet', '').strip()}\n  {row.get('url', '')}")
    return "\n\n".join(lines)


def get_own_commits_results(limit: int = 10) -> tuple[list[dict[str, Any]], str | None]:
    headers = _headers()
    if headers is None:
        return [], _missing_pat_message()
    try:
        import requests
    except ImportError as exc:
        return [], f"GitHub error: {exc}"

    repo, branch = _repo_settings()
    per_page = max(1, min(int(limit or 10), 30))
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/commits",
            headers=headers,
            params={"sha": branch, "per_page": per_page},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return [], f"GitHub request failed: {exc}"

    if resp.status_code >= 400:
        return [], _http_error_message(resp.status_code, resp.text)

    try:
        payload = resp.json()
    except ValueError:
        return [], "GitHub returned invalid JSON."

    out: list[dict[str, Any]] = []
    for item in payload:
        commit = item.get("commit") or {}
        author = commit.get("author") or {}
        out.append({
            "sha": (item.get("sha") or "")[:7],
            "message": (commit.get("message") or "").split("\n")[0],
            "author": author.get("name") or "unknown",
            "date": author.get("date") or "",
        })
    return out, None


def get_own_commits(limit: int = 10) -> str:
    """Recent commits on the configured branch."""
    commits, err = get_own_commits_results(limit)
    if err:
        return err
    if not commits:
        return "No commits found."
    return "\n".join(
        f"{c['sha']} {c['date']} {c['author']}: {c['message']}" for c in commits
    )


def get_own_issues_results(state: str = "open") -> tuple[list[dict[str, Any]], str | None]:
    headers = _headers()
    if headers is None:
        return [], _missing_pat_message()
    try:
        import requests
    except ImportError as exc:
        return [], f"GitHub error: {exc}"

    repo, _branch = _repo_settings()
    state = (state or "open").strip().lower()
    if state not in {"open", "closed", "all"}:
        state = "open"
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            params={"state": state, "per_page": 20},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return [], f"GitHub request failed: {exc}"

    if resp.status_code >= 400:
        return [], _http_error_message(resp.status_code, resp.text)

    try:
        payload = resp.json()
    except ValueError:
        return [], "GitHub returned invalid JSON."

    out: list[dict[str, Any]] = []
    for item in payload:
        if "pull_request" in item:
            continue
        labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
        out.append({
            "number": item.get("number"),
            "title": item.get("title", ""),
            "body": (item.get("body") or "")[:500],
            "labels": labels,
            "created_at": item.get("created_at", ""),
        })
    return out, None


def get_own_issues(state: str = "open") -> str:
    """Open or closed issues on the Jarvis repo."""
    issues, err = get_own_issues_results(state)
    if err:
        return err
    if not issues:
        return f"No {state} issues found."
    lines = []
    for issue in issues:
        labels = ", ".join(issue.get("labels") or [])
        suffix = f" ({labels})" if labels else ""
        lines.append(f"#{issue['number']} {issue['title']}{suffix}")
    return "\n".join(lines)


def resolve_tool_source_path(tool_name: str) -> tuple[str | None, str | None]:
    """Best-effort path + content for a registered tool implementation."""
    name = (tool_name or "").strip()
    if not name:
        return None, None

    candidates = [
        f"tools/{name}.py",
        f"tools/{name.replace('__', '/')}.py",
    ]
    for path in candidates:
        content, err = read_own_file_content(path)
        if content and not err:
            return path, content

    results, err = search_own_code_results(f'"{name}"', limit=3)
    if err or not results:
        return None, None
    for row in results:
        path = row.get("path") or ""
        if not path.endswith(".py"):
            continue
        content, read_err = read_own_file_content(path)
        if content and not read_err:
            return path, content
    return None, None


def numbered_snippet(content: str, *, max_lines: int = 40) -> str:
    """Prefix lines with numbers for haiku / proposed_change context."""
    lines = content.splitlines()[:max_lines]
    numbered = "\n".join(f"{i + 1:4d}| {line}" for i, line in enumerate(lines))
    if len(content.splitlines()) > max_lines:
        numbered += f"\n... ({len(content.splitlines()) - max_lines} more lines on GitHub)"
    return numbered
