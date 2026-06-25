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


def test_search_github_issues_uses_search_api_when_query_given():
    """Regression: previously used the list endpoint which ignores the q param.
    Now uses /search/issues when a free-text query is provided."""
    captured_urls: list[str] = []

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": [
        {"number": 7, "state": "open", "title": "wake word misfire", "labels": []},
    ]}

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        return mock_resp

    with patch("requests.get", side_effect=fake_get):
        result = search_github_issues("owner/repo", query="wake word")

    assert any("search/issues" in u for u in captured_urls), (
        f"Expected /search/issues endpoint, got: {captured_urls}"
    )
    assert "#7" in result
    assert "wake word misfire" in result


def test_search_github_issues_uses_list_api_without_query():
    """Without a query, the list endpoint should be used (more efficient)."""
    captured_urls: list[str] = []

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"number": 1, "state": "open", "title": "test issue", "labels": []},
    ]

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        return mock_resp

    with patch("requests.get", side_effect=fake_get):
        result = search_github_issues("owner/repo")

    assert any("repos/owner/repo/issues" in u for u in captured_urls)
    assert "#1" in result


def test_search_github_issues_query_string_contains_repo():
    """The search query must scope results to the given repo."""
    captured_params: list[dict] = []

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}

    def fake_get(url, params=None, **kwargs):
        captured_params.append(params or {})
        return mock_resp

    with patch("requests.get", side_effect=fake_get):
        search_github_issues("owner/repo", query="STT latency")

    q = captured_params[0].get("q", "")
    assert "repo:owner/repo" in q
    assert "STT latency" in q
