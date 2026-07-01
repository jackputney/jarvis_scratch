"""Phone safety: escalation, halt switch, and tool blocking on the phone path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import tools.phone as phone
from config import Config
from tools.phone import (
    build_transfer_twiml,
    caller_requests_human,
    escalate_to_human,
    halt_phone_autonomous,
    reset_phone_safety_state_for_tests,
    resume_phone_autonomous,
)
from tools.registry import (
    CONFIRM_REQUIRED_TOOLS,
    MODERATE_TOOLS,
    PHONE_ALLOWED_TOOLS,
    READ_ONLY_TOOLS,
    dispatch_tool,
    phone_tool_allowed,
)


@pytest.fixture(autouse=True)
def _reset_phone_state():
    reset_phone_safety_state_for_tests()
    yield
    reset_phone_safety_state_for_tests()


def test_caller_requests_human_phrases():
    assert caller_requests_human("I need to talk to a person please")
    assert caller_requests_human("Can you transfer me to someone?")
    assert not caller_requests_human("what is on my calendar")


def test_build_transfer_twiml():
    xml = build_transfer_twiml("+15559876543")
    assert "+15559876543" in xml
    assert "<Dial>" in xml


def test_escalate_to_human_uses_fallback(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    monkeypatch.setenv("TWILIO_FALLBACK_NUMBER", "+15557654321")
    phone.set_active_call_sid("CAtest")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "in-progress"}
    with patch("requests.request", return_value=mock_resp) as req:
        result = escalate_to_human(reason="test")
    assert "transferring" in result.lower()
    assert req.call_args[1]["data"]["Twiml"]
    assert "+15557654321" in req.call_args[1]["data"]["Twiml"]


def test_escalate_without_fallback_ends_call(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    monkeypatch.delenv("TWILIO_FALLBACK_NUMBER", raising=False)
    phone.set_active_call_sid("CAend")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "completed"}
    with patch("requests.request", return_value=mock_resp):
        result = escalate_to_human()
    assert "ended" in result.lower()


def test_halt_and_resume_autonomous():
    assert not phone.is_phone_autonomous_halted()
    halt_phone_autonomous()
    assert phone.is_phone_autonomous_halted()
    resume_phone_autonomous()
    assert not phone.is_phone_autonomous_halted()


def test_phone_autonomous_allowed_respects_config():
    cfg = Config(phone_autonomous_enabled=False)
    assert not phone.phone_autonomous_allowed(cfg, "CA1")
    halt_phone_autonomous(call_sid="CA1")
    cfg_on = Config(phone_autonomous_enabled=True)
    assert not phone.phone_autonomous_allowed(cfg_on, "CA1")


def test_phone_tool_allowed_blocks_mutating():
    assert phone_tool_allowed("get_calendar_events")
    assert phone_tool_allowed("escalate")
    assert not phone_tool_allowed("send_email")
    assert not phone_tool_allowed("make_call")
    assert "make_call" in CONFIRM_REQUIRED_TOOLS
    assert "end_call" in MODERATE_TOOLS
    assert PHONE_ALLOWED_TOOLS == READ_ONLY_TOOLS | frozenset({"escalate"})


def test_dispatch_tool_phone_mode_denies_side_effects(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    out = dispatch_tool("make_call", {"to": "+14155551234"}, phone_mode=True, confirm=False)
    assert "cannot run during a phone call" in out
    out2 = dispatch_tool("send_email", {"to": "a@b.com", "subject": "x", "body": "y"}, phone_mode=True, confirm=False)
    assert "cannot run during a phone call" in out2


def test_run_phone_turn_escalates_on_human_request(monkeypatch):
    from adapters.twilio_call import run_phone_turn

    cfg = Config()
    out = run_phone_turn("please transfer me to a person", cfg)
    assert out["escalate"] is True
    assert "connecting" in out["reply"].lower()


def test_run_phone_turn_escalates_when_halted(monkeypatch):
    from adapters.twilio_call import run_phone_turn

    halt_phone_autonomous(call_sid="CAhalt")
    cfg = Config(phone_autonomous_enabled=True)
    out = run_phone_turn("hello", cfg, call_sid="CAhalt")
    assert out["escalate"] is True
