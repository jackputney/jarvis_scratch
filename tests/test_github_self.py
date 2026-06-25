"""GitHub self-read tools and reflect integration."""

import base64
import json

import pytest

from dashboard.app import create_app
from tools.github_self import (
    comment_own_issue,
    create_own_branch,
    create_own_file,
    create_own_issue,
    create_own_pr,
    get_own_commits,
    list_own_files,
    read_own_file,
    resolve_tool_source_path,
    search_own_code,
)
from tools.registry import CONFIRM_REQUIRED_TOOLS, DASHBOARD_CONFIRM_TOOLS, MODERATE_TOOLS


@pytest.fixture
def client(temp_env):
    from dashboard.tools_run_confirm import reset_for_tests as reset_tools_run_confirm

    reset_tools_run_confirm()
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _mock_response(status_code: int, payload, text: str = ""):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = text or json.dumps(payload)
    resp.content = b"{}" if payload else b""
    return resp


@pytest.fixture(autouse=True)
def github_pat(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "ghp_test_token")


def test_read_own_file_returns_decoded_content(monkeypatch):
    import requests

    content = "def hello():\n    return 'world'\n"
    encoded = base64.b64encode(content.encode()).decode()
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(200, {"encoding": "base64", "content": encoded}),
    )
    assert read_own_file("tools/web.py") == content


def test_read_own_file_handles_404(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(404, {}, text="Not Found"),
    )
    result = read_own_file("missing.py")
    assert "404" in result or "not found" in result.lower()


def test_read_own_file_missing_pat(monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    result = read_own_file("tools/web.py")
    assert "GITHUB_PAT" in result
    assert "not configured" in result.lower()


def test_read_own_file_rate_limit(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(429, {}, text="rate limit"),
    )
    result = read_own_file("tools/web.py")
    assert "rate limit" in result.lower()


def test_list_own_files_returns_paths(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(
            200,
            [
                {"path": "tools/web.py", "type": "file"},
                {"path": "tools/github_self.py", "type": "file"},
            ],
        ),
    )
    result = list_own_files("tools")
    assert "tools/web.py" in result
    assert "tools/github_self.py" in result


def test_search_own_code_top_results(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(
            200,
            {
                "items": [
                    {
                        "path": "tools/web.py",
                        "html_url": "https://github.com/jackputney/jarvis_scratch/blob/main/tools/web.py",
                        "text_matches": [{"fragment": "def web_search("}],
                    },
                    {
                        "path": "pipeline.py",
                        "html_url": "https://github.com/example/pipeline.py",
                        "text_matches": [{"fragment": "web_search tool"}],
                    },
                ]
            },
        ),
    )
    result = search_own_code("web_search")
    assert "tools/web.py" in result
    assert "def web_search(" in result


def test_get_own_commits_returns_list(monkeypatch):
    import requests

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _mock_response(
            200,
            [
                {
                    "sha": "abc1234567890",
                    "commit": {
                        "message": "feat: add github self-read\n\nbody",
                        "author": {"name": "Jack", "date": "2026-06-18T12:00:00Z"},
                    },
                }
            ],
        ),
    )
    result = get_own_commits(5)
    assert "abc123" in result
    assert "Jack" in result
    assert "feat: add github self-read" in result


def test_reflect_reads_tool_file_before_suggestion(monkeypatch, temp_env):
    from improvement.reflect import run_reflection
    from improvement.trace import flush_writes, reset_writer_for_tests
    from memory.db import init_db

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    reset_writer_for_tests()
    init_db()

    read_calls: list[str] = []
    sample_code = "def web_search(q):\n    raise RuntimeError('boom')\n"

    def fake_resolve(tool_name: str):
        read_calls.append(tool_name)
        return f"tools/{tool_name}.py", sample_code

    monkeypatch.setattr(
        "improvement.reflect.compute_stats",
        lambda: {
            "correction_rate": 0.0,
            "tool_error_rate": 0.5,
            "tts_fallback_rate": 0.0,
            "slow_turn_rate": 0.0,
            "top_tools": [{"name": "web_search", "count": 2, "error_count": 8}],
        },
    )
    monkeypatch.setattr("improvement.reflect.fetch_turns", lambda **kw: [])
    monkeypatch.setattr("improvement.reflect._metric_suggestions", lambda *a, **k: [])
    monkeypatch.setattr("improvement.reflect._dep_upgrade_suggestions", lambda *a, **k: [])
    monkeypatch.setattr("tools.github_self.resolve_tool_source_path", fake_resolve)

    captured: dict = {}

    def fake_haiku_tool(cfg, **kwargs):
        captured.update(kwargs)
        from improvement.reflect import SuggestionDraft

        return SuggestionDraft(
            title=f"Fix {kwargs['tool_name']}",
            body="Tool errors need handling.",
            category="tools",
            severity="high",
            proposed_change="Wrap web_search in try/except at line 2.",
            evidence_json=json.dumps(kwargs["evidence"]),
        )

    monkeypatch.setattr("improvement.reflect._haiku_tool_suggestion", fake_haiku_tool)

    run_reflection()
    flush_writes()

    assert read_calls == ["web_search"]
    assert captured.get("source_code") == sample_code
    assert "def web_search" in (captured.get("source_code") or "")


def test_reflect_proposed_change_contains_code_snippet(monkeypatch, temp_env):
    from improvement.reflect import SuggestionDraft, _append_source_snippet

    code = "line one\nline two\n"
    out = _append_source_snippet(
        "Change error handling.",
        source_path="tools/web.py",
        source_code=code,
    )
    assert "Current code (tools/web.py)" in out
    assert "   1| line one" in out
    assert "   2| line two" in out


def test_resolve_tool_source_path_tries_candidates(monkeypatch):
    calls: list[str] = []

    def fake_read(path: str, **kw):
        calls.append(path)
        if path == "tools/web_search.py":
            return "def web_search(): pass", None
        return None, "not found"

    monkeypatch.setattr("tools.github_self.read_own_file_content", fake_read)
    path, content = resolve_tool_source_path("web_search")
    assert path == "tools/web_search.py"
    assert "web_search" in content
    assert calls[0] == "tools/web_search.py"


def test_create_own_branch_creates_ref(monkeypatch):
    import requests

    calls: list[tuple[str, str]] = []

    def fake_request(method, url, **kwargs):
        calls.append((method.upper(), url))
        if method.upper() == "GET" and "/git/ref/heads/main" in url:
            return _mock_response(200, {"object": {"sha": "abc123"}})
        if method.upper() == "POST" and "/git/refs" in url:
            assert kwargs["json"]["ref"] == "refs/heads/feature/test"
            assert kwargs["json"]["sha"] == "abc123"
            return _mock_response(201, {"ref": "refs/heads/feature/test"})
        return _mock_response(500, {}, text="unexpected")

    monkeypatch.setattr(requests, "request", fake_request)
    result = create_own_branch("feature/test")
    assert "feature/test" in result
    assert any(m == "POST" for m, _ in calls)


def test_create_own_pr_posts_payload(monkeypatch):
    import requests

    captured: dict = {}

    def fake_request(method, url, **kwargs):
        if method.upper() == "POST" and "/pulls" in url:
            captured.update(kwargs.get("json") or {})
            return _mock_response(201, {"html_url": "https://github.com/o/r/pull/1"})
        return _mock_response(404, {}, text="not found")

    monkeypatch.setattr(requests, "request", fake_request)
    url = create_own_pr("Fix bug", "Details", "feature/x", "main")
    assert url.endswith("/pull/1")
    assert captured == {"title": "Fix bug", "body": "Details", "head": "feature/x", "base": "main"}


def test_create_own_issue_posts_payload(monkeypatch):
    import requests

    captured: dict = {}

    def fake_request(method, url, **kwargs):
        if method.upper() == "POST" and url.endswith("/issues"):
            captured.update(kwargs.get("json") or {})
            return _mock_response(201, {"html_url": "https://github.com/o/r/issues/9"})
        return _mock_response(404, {}, text="not found")

    monkeypatch.setattr(requests, "request", fake_request)
    url = create_own_issue("Bug", "Body text", labels=["jarvis"])
    assert "/issues/9" in url
    assert captured["title"] == "Bug"
    assert captured["labels"] == ["jarvis"]


def test_write_tools_missing_pat(monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    for fn, args in (
        (create_own_branch, ("x",)),
        (create_own_file, ("a.py", "x", "msg")),
        (create_own_pr, ("t", "b", "head")),
        (create_own_issue, ("t", "b")),
        (comment_own_issue, (1, "hi")),
    ):
        result = fn(*args)
        assert "GITHUB_PAT" in result


def test_high_risk_github_self_tools_require_confirm():
    assert "create_own_file" in CONFIRM_REQUIRED_TOOLS
    assert "create_own_pr" in CONFIRM_REQUIRED_TOOLS
    assert "create_own_branch" in MODERATE_TOOLS
    assert "create_own_file" in DASHBOARD_CONFIRM_TOOLS


def test_create_own_file_requires_dashboard_confirm(client):
    r = client.post("/api/tools/run", json={
        "name": "create_own_file",
        "inputs": {"path": "notes/test.txt", "content": "hello", "message": "add test"},
    })
    body = r.get_json()
    assert body.get("confirm_required") is True
    assert body.get("confirm_id")


def test_accept_suggestion_opens_github_issue(monkeypatch, temp_env):
    from improvement.reflect import SuggestionDraft, accept_suggestion, fetch_suggestion_by_id, persist_suggestion
    from improvement.trace import flush_writes, reset_writer_for_tests
    from memory.db import init_db

    reset_writer_for_tests()
    init_db()
    sid = persist_suggestion(
        SuggestionDraft(
            "Fix web_search",
            "Errors too often",
            "tools",
            "high",
            "Update tools/web.py line 2",
            '{"tool": "web_search"}',
        ),
    )
    flush_writes()

    monkeypatch.setattr(
        "tools.github_self.create_own_branch",
        lambda name, from_branch="main": f"https://github.com/o/r/tree/{name}",
    )
    monkeypatch.setattr(
        "tools.github_self.create_own_issue_url",
        lambda title, body, labels=None: (
            "https://github.com/o/r/issues/42",
            None,
        ),
    )
    monkeypatch.setattr(
        "tools.github_self.read_own_file_content",
        lambda path, **kw: ("def web_search(): pass", None),
    )

    result = accept_suggestion(sid)
    flush_writes()
    assert result["ok"] is True
    assert result["github_issue_url"] == "https://github.com/o/r/issues/42"
    stored = fetch_suggestion_by_id(sid)
    assert stored["github_issue_url"] == "https://github.com/o/r/issues/42"
