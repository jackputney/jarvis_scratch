"""Dashboard email triage view — mocked Gmail API and draft endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dashboard.app import create_app

_SAMPLE_EMAIL = {
    "id": "m1",
    "thread_id": "t1",
    "from": "Alice <alice@example.com>",
    "from_email": "alice@example.com",
    "subject": "Project update",
    "date": "Mon, 1 Jan 2024 10:00:00 +0000",
    "snippet": "Can we meet tomorrow?",
}


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_fetch_unread_emails_structured():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": [{"id": "m1"}]}
    mock_service.users().messages().get().execute.return_value = {
        "threadId": "t1",
        "snippet": "Hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "Mon"},
            ]
        },
    }
    with patch("tools.google_gmail.get_gmail_service", return_value=mock_service):
        from tools.google_gmail import fetch_unread_emails

        items = fetch_unread_emails(max_results=5)
    assert len(items) == 1
    assert items[0]["from_email"] == "alice@example.com"
    assert items[0]["subject"] == "Hi"
    assert "Hello there" in items[0]["snippet"]


def test_extract_email_and_reply_subject():
    from tools.google_gmail import _extract_email, reply_subject

    assert _extract_email("Alice <alice@example.com>") == "alice@example.com"
    assert _extract_email("bob@example.com") == "bob@example.com"
    assert reply_subject("Hello") == "Re: Hello"
    assert reply_subject("Re: Hello") == "Re: Hello"


def test_api_email_unread(client):
    with patch(
        "tools.google_gmail.fetch_unread_emails",
        return_value=[_SAMPLE_EMAIL],
    ):
        resp = client.get("/api/email/unread")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["emails"][0]["subject"] == "Project update"


def test_api_email_unread_handles_error(client):
    with patch("tools.google_gmail.fetch_unread_emails", side_effect=Exception("No auth")):
        resp = client.get("/api/email/unread")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert data["emails"] == []
    assert "No auth" in data["error"]


def test_api_email_draft_reply(client, temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = __import__("config").Config.load()
    monkeypatch.setattr("config.Config.load", lambda: cfg)

    with patch("tools.google_gmail.fetch_unread_emails", return_value=[_SAMPLE_EMAIL]), \
         patch("tools.google_gmail.fetch_thread_context", return_value="Earlier thread text"), \
         patch(
             "tools.google_gmail.draft_email_reply",
             return_value="Thanks for the update — tomorrow works for me.",
         ):
        resp = client.post("/api/email/draft-reply", json={"message_id": "m1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["to"] == "alice@example.com"
    assert data["subject"] == "Re: Project update"
    assert "tomorrow" in data["body"]


def test_api_email_draft_reply_missing_message(client, temp_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("tools.google_gmail.fetch_unread_emails", return_value=[]):
        resp = client.post("/api/email/draft-reply", json={"message_id": "missing"})
    assert resp.status_code == 404


def test_api_email_draft_reply_requires_api_key(client, temp_env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = __import__("config").Config.load()
    cfg.anthropic_api_key = ""
    monkeypatch.setattr("config.Config.load", lambda: cfg)
    resp = client.post("/api/email/draft-reply", json={"message_id": "m1"})
    assert resp.status_code == 400


def test_index_includes_email_nav(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b'data-view="email"' in r.data
    assert b"Email</span>" in r.data


def test_get_unread_emails_still_string_format():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": [{"id": "m1"}]}
    mock_service.users().messages().get().execute.return_value = {
        "threadId": "t1",
        "snippet": "Hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "Subject", "value": "Hi"},
                {"name": "Date", "value": "Mon"},
            ]
        },
    }
    with patch("tools.google_gmail.get_gmail_service", return_value=mock_service):
        from tools.google_gmail import get_unread_emails

        out = get_unread_emails(max_results=5)
    assert "Unread emails" in out
    assert "Alice" in out
    assert "Hi" in out
