"""Phone call tools — mocked Twilio HTTP, no real calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import tools.phone as phone
from tools.phone import end_call, get_call_status, make_call
from tools.registry import CONFIRM_REQUIRED_TOOLS, MODERATE_TOOLS, READ_ONLY_TOOLS


def _env(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    monkeypatch.setenv("TWILIO_VOICE_URL", "https://example.com/voice")


def test_make_call_rejects_invalid_e164(monkeypatch):
    _env(monkeypatch)
    assert "Refused" in make_call("555-0100")
    assert "Refused" in make_call("14155551234")
    assert "Refused" in make_call("")


def test_make_call_missing_env(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)
    assert "not configured" in make_call("+14155551234").lower()


def test_make_call_missing_voice_url(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    monkeypatch.delenv("TWILIO_VOICE_URL", raising=False)
    assert "TWILIO_VOICE_URL" in make_call("+14155551234")


def test_make_call_success(monkeypatch):
    _env(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"sid": "CAabc", "status": "queued"}
    with patch("requests.request", return_value=mock_resp) as req:
        result = make_call("+14155559999", purpose="reminder")
    assert "initiated" in result.lower()
    assert "CAabc" in result
    req.assert_called_once()
    args, kwargs = req.call_args
    assert args[0] == "POST"
    assert kwargs["data"]["To"] == "+14155559999"
    assert kwargs["data"]["From"] == "+15551234567"
    assert kwargs["auth"] == ("ACtest123", "auth-token")


def test_end_call_uses_active_sid(monkeypatch):
    _env(monkeypatch)
    phone._active_call_sid = "CAactive"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "completed"}
    with patch("requests.request", return_value=mock_resp) as req:
        result = end_call()
    assert "ended" in result.lower()
    assert "CAactive" in req.call_args[0][1]


def test_end_call_specific_sid(monkeypatch):
    _env(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "completed"}
    with patch("requests.request", return_value=mock_resp) as req:
        end_call("CAexplicit")
    assert "CAexplicit" in req.call_args[0][1]


def test_end_call_no_sid(monkeypatch):
    _env(monkeypatch)
    phone._active_call_sid = ""
    assert "No active call SID" in end_call()


def test_get_call_status(monkeypatch):
    _env(monkeypatch)
    phone._active_call_sid = "CAstatus"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "in-progress"}
    with patch("requests.request", return_value=mock_resp) as req:
        result = get_call_status()
    assert "in-progress" in result
    assert "CAstatus" in req.call_args[0][1]


def test_get_call_status_missing_creds(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    assert "not configured" in get_call_status("CAx").lower()


def test_registry_tiers():
    assert "make_call" in CONFIRM_REQUIRED_TOOLS
    assert "end_call" in MODERATE_TOOLS
    assert "get_call_status" in READ_ONLY_TOOLS
