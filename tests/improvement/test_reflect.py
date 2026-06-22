"""Jarvis Thinks — suggestions API and reflection."""

from __future__ import annotations

import json

import pytest

from improvement.reflect import (
    SuggestionDraft,
    fetch_suggestions,
    persist_suggestion,
    run_reflection,
    update_suggestion_status,
)
from improvement.trace import flush_writes, reset_writer_for_tests
from memory.db import init_db


@pytest.fixture
def client(temp_env):
    from dashboard.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def improvement_db(temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    reset_writer_for_tests()
    init_db()
    yield
    flush_writes()
    reset_writer_for_tests()


def test_fetch_suggestions_ordered_by_severity(improvement_db):
    persist_suggestion(
        SuggestionDraft("Low", "body", "latency", "low", "fix", "{}"),
    )
    persist_suggestion(
        SuggestionDraft("Critical", "body", "tools", "critical", "fix", "{}"),
    )
    flush_writes()
    items = fetch_suggestions(status="pending", limit=10)
    assert len(items) >= 2
    assert items[0]["severity"] == "critical"


def test_update_suggestion_status(improvement_db):
    sid = persist_suggestion(
        SuggestionDraft("T", "b", "tools", "medium", "change", "{}"),
    )
    flush_writes()
    assert update_suggestion_status(sid, "accepted") is True
    pending = fetch_suggestions(status="pending", limit=10)
    assert all(s["id"] != sid for s in pending)
    accepted = fetch_suggestions(status="accepted", limit=10)
    assert any(s["id"] == sid for s in accepted)


def test_run_reflection_tool_offenders(monkeypatch, improvement_db):
    monkeypatch.setattr(
        "improvement.reflect.compute_stats",
        lambda: {
            "correction_rate": 0.0,
            "tool_error_rate": 0.2,
            "tts_fallback_rate": 0.0,
            "slow_turn_rate": 0.0,
            "top_tools": [{"name": "web_search", "count": 2, "error_count": 5}],
        },
    )
    monkeypatch.setattr("improvement.reflect.fetch_turns", lambda **kw: [])
    monkeypatch.setattr("improvement.reflect._metric_suggestions", lambda *a, **k: [])
    monkeypatch.setattr("improvement.reflect._dep_upgrade_suggestions", lambda *a, **k: [])

    items = run_reflection()
    flush_writes()
    assert len(items) >= 1
    stored = fetch_suggestions(status="pending", limit=10)
    assert any("web_search" in (s.get("title") or "") for s in stored)


def test_suggestions_api(client, improvement_db, monkeypatch):
    sid = persist_suggestion(
        SuggestionDraft("API test", "body", "tools", "high", "do thing", json.dumps({"x": 1})),
    )
    flush_writes()
    listed = client.get("/api/improvement/suggestions?status=pending&limit=5").get_json()
    assert any(s["id"] == sid for s in listed["suggestions"])

    assert client.post(f"/api/improvement/suggestions/{sid}/accept").status_code == 200

    monkeypatch.setattr("improvement.reflect.run_reflection", lambda: [])
    resp = client.post("/api/improvement/suggestions/generate").get_json()
    assert resp["ok"] is True
