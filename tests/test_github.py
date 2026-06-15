"""GitHub integration tools — mocked API."""

from unittest.mock import MagicMock, patch

from tools.github import create_github_comment, get_github_repo_summary, search_github_issues
from tools.registry import CONFIRM_REQUIRED_TOOLS, READ_ONLY_TOOLS


def test_github_issues_mocked():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"number": 42, "state": "open", "title": "Fix wake word", "labels": [{"name": "bug"}]},
    ]
    with patch("requests.get", return_value=mock_resp):
        result = search_github_issues("owner/repo")
    assert "#42" in result
    assert "Fix wake word" in result


def test_github_comment_mocked(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    with patch("requests.post", return_value=mock_resp):
        result = create_github_comment("owner/repo", 1, "Looks good")
    assert "Comment added" in result


def test_github_missing_token_still_reads(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "full_name": "owner/repo",
        "description": "Jarvis fork",
        "stargazers_count": 3,
        "forks_count": 1,
        "open_issues_count": 2,
        "language": "Python",
    }
    with patch("requests.get", return_value=mock_resp):
        result = get_github_repo_summary("owner/repo")
    assert "Jarvis fork" in result
    assert "create_github_comment" in CONFIRM_REQUIRED_TOOLS
    assert "search_github_issues" in READ_ONLY_TOOLS
