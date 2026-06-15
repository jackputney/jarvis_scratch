"""GitHub integration tools."""

from __future__ import annotations

import os


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_github_issues(repo: str, query: str = "", state: str = "open") -> str:
    try:
        import requests
    except ImportError as exc:
        return f"GitHub error: {exc}"
    owner_repo = repo.strip("/")
    params: dict = {"state": state, "per_page": 10}
    if query:
        params["q"] = query
    resp = requests.get(
        f"https://api.github.com/repos/{owner_repo}/issues",
        headers=_headers(),
        params=params,
        timeout=10,
    )
    if resp.status_code >= 400:
        return f"GitHub error: HTTP {resp.status_code}"
    issues = []
    for issue in resp.json():
        if "pull_request" in issue:
            continue
        labels = ", ".join(l["name"] for l in issue.get("labels", []))
        line = f"#{issue['number']} [{issue['state']}] {issue['title']}"
        if labels:
            line += f" ({labels})"
        issues.append(line)
    return "\n".join(issues) if issues else "No issues found."


def create_github_comment(repo: str, issue_number: int, body: str) -> str:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return "Error: GitHub token not configured. Add it in Hub → Connections."
    try:
        import requests
    except ImportError as exc:
        return f"GitHub error: {exc}"
    resp = requests.post(
        f"https://api.github.com/repos/{repo.strip('/')}/issues/{int(issue_number)}/comments",
        headers=_headers(),
        json={"body": body or ""},
        timeout=10,
    )
    if resp.status_code >= 400:
        return f"GitHub error: HTTP {resp.status_code}"
    return f"Comment added to {repo}#{issue_number}"


def get_github_repo_summary(repo: str) -> str:
    try:
        import requests
    except ImportError as exc:
        return f"GitHub error: {exc}"
    resp = requests.get(
        f"https://api.github.com/repos/{repo.strip('/')}",
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code >= 400:
        return f"GitHub error: HTTP {resp.status_code}"
    r = resp.json()
    return (
        f"{r.get('full_name', repo)}: {r.get('description') or 'No description'}\n"
        f"Stars: {r.get('stargazers_count', 0)} | Forks: {r.get('forks_count', 0)} | "
        f"Open issues: {r.get('open_issues_count', 0)} | Language: {r.get('language') or 'N/A'}"
    )
