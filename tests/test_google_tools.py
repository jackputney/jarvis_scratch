"""Google Calendar, Gmail, and Sheets tools — mocked API, no live calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.registry import CONFIRM_REQUIRED_TOOLS, READ_ONLY_TOOLS, dispatch_tool


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_get_credentials_loads_existing_token(tmp_path, monkeypatch):
    token = tmp_path / "google_token.json"
    token.write_text('{"token": "x", "refresh_token": "r", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]}')
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    import tools.google_auth as ga
    monkeypatch.setattr(ga, "TOKEN_PATH", token)
    monkeypatch.setattr(ga, "SCOPES", ["https://www.googleapis.com/auth/calendar.readonly"])

    with patch("tools.google_auth.Credentials") as mock_creds_cls:
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.expired = False
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds
        creds = ga.get_credentials()
    assert creds is mock_creds


def test_google_secret_read_from_config_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "GOCSPX-test-secret")
    import tools.google_auth as ga
    cfg = ga._client_config()
    assert cfg["installed"]["client_id"] == "cid.apps.googleusercontent.com"
    assert cfg["installed"]["client_secret"] == "GOCSPX-test-secret"


def test_get_credentials_missing_env_raises(monkeypatch, temp_env):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setattr("config._load_dotenv_if_present", lambda: None)
    import config
    config.Config.invalidate_cache()
    import tools.google_auth as ga
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        ga._client_config()


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def test_get_calendar_events_formats_output():
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {
        "items": [
            {
                "summary": "Standup",
                "start": {"dateTime": "2026-06-11T09:00:00-07:00"},
                "end": {"dateTime": "2026-06-11T09:30:00-07:00"},
                "location": "Zoom",
                "attendees": [{"email": "a@example.com"}],
            }
        ]
    }
    with patch("tools.google_calendar.get_calendar_service", return_value=mock_service):
        from tools.google_calendar import get_calendar_events
        out = get_calendar_events(days=3)
    assert "Standup" in out
    assert "Zoom" in out
    assert "a@example.com" in out


def test_get_todays_schedule_empty():
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": []}
    with patch("tools.google_calendar.get_calendar_service", return_value=mock_service):
        from tools.google_calendar import get_todays_schedule
        out = get_todays_schedule()
    assert "no events" in out.lower() or "nothing" in out.lower() or "clear" in out.lower()


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def test_get_unread_emails():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": [{"id": "m1"}]}
    mock_service.users().messages().get().execute.return_value = {
        "snippet": "Hello there",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "Subject", "value": "Hi"},
            ]
        },
    }
    with patch("tools.gmail.get_gmail_service", return_value=mock_service):
        from tools.gmail import get_unread_emails
        out = get_unread_emails(max_results=5)
    assert "Alice" in out or "alice@example.com" in out
    assert "Hi" in out


def test_search_emails():
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": [{"id": "m2"}]}
    mock_service.users().messages().get().execute.return_value = {
        "snippet": "Invoice attached",
        "payload": {"headers": [{"name": "Subject", "value": "Invoice"}]},
    }
    with patch("tools.gmail.get_gmail_service", return_value=mock_service):
        from tools.gmail import search_emails
        out = search_emails("invoice")
    assert "Invoice" in out


def test_send_email():
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent123"}
    with patch("tools.gmail.get_gmail_service", return_value=mock_service):
        from tools.gmail import send_email
        out = send_email("bob@example.com", "Test", "Body text")
    assert "sent" in out.lower() or "sent123" in out


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def test_read_sheet():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [["Name", "Score"], ["Ann", "97"]]
    }
    with patch("tools.google_sheets.get_sheets_service", return_value=mock_service):
        from tools.google_sheets import read_sheet
        out = read_sheet("abc123", "Sheet1!A1:B2")
    assert "Name" in out
    assert "Ann" in out


def test_append_row():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().append().execute.return_value = {"updates": {"updatedRows": 1}}
    with patch("tools.google_sheets.get_sheets_service", return_value=mock_service):
        from tools.google_sheets import append_row
        out = append_row("abc123", "Sheet1", ["a", "b", "c"])
    assert "append" in out.lower() or "row" in out.lower() or "1" in out


def test_update_cell():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().update().execute.return_value = {"updatedCells": 1}
    with patch("tools.google_sheets.get_sheets_service", return_value=mock_service):
        from tools.google_sheets import update_cell
        out = update_cell("abc123", "Sheet1!C5", "2931")
    assert "update" in out.lower() or "2931" in out or "C5" in out


# ---------------------------------------------------------------------------
# Registry confirm gate
# ---------------------------------------------------------------------------

def test_google_read_only_tools_skip_confirm():
    for name in (
        "get_calendar_events",
        "get_todays_schedule",
        "get_unread_emails",
        "search_emails",
        "read_sheet",
    ):
        assert name in READ_ONLY_TOOLS


def test_send_email_requires_confirm():
    assert "send_email" in CONFIRM_REQUIRED_TOOLS
    with patch("tools.confirm.wait_for_confirm", return_value="deny"):
        result = dispatch_tool(
            "send_email",
            {"to": "x@y.com", "subject": "s", "body": "b"},
            confirm=True,
        )
    assert "not executed" in result
