"""Phase 0 hardening — query lock, confirm single-flight, injection guards."""

import threading
import time
from unittest.mock import patch

import pipeline
from config import Config
from tools import confirm as tool_confirm
from tools.gmail import send_email
from tools.registry import dispatch_tool
from tools.system import open_app, validate_app_name


def test_process_query_rejects_concurrent_calls(temp_env, monkeypatch):
    monkeypatch.setattr(pipeline, "_call_claude", lambda *a, **k: ("ok", "m", 0.0))
    lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()

    def slow_call(text, cfg, history=None, on_state=None):
        started.set()
        release.wait(timeout=2)
        return "done", "m", 0.0

    monkeypatch.setattr(pipeline, "_call_claude", slow_call)

    cfg = Config()
    holder: list[dict] = []

    def first():
        holder.append(pipeline.process_query("first", cfg))

    t = threading.Thread(target=first, daemon=True)
    t.start()
    assert started.wait(timeout=2)
    second = pipeline.process_query("second", cfg)
    assert second.get("busy") is True
    release.set()
    t.join(timeout=2)
    assert holder[0].get("busy") is False


def test_confirm_single_flight_rejects_second_waiter():
    result_holder: list[str] = []

    def waiter(tool: str) -> None:
        result_holder.append(
            tool_confirm.wait_for_confirm(tool, {"x": 1}, timeout_sec=5)
        )

    t1 = threading.Thread(target=waiter, args=("send_email",), daemon=True)
    t1.start()
    for _ in range(40):
        if tool_confirm.get_pending() is not None:
            break
        time.sleep(0.05)
    assert tool_confirm.get_pending() is not None

    # Second waiter should fail closed immediately.
    assert tool_confirm.wait_for_confirm("append_row", {"y": 2}, timeout_sec=5) == "deny"

    tool_confirm.respond(tool_confirm.get_pending()["id"], True)
    t1.join(timeout=2)
    assert result_holder == ["allow"]


def test_open_app_rejects_injection():
    malicious = 'Safari"; do shell script "echo pwned'
    out = open_app(malicious)
    assert "Refused" in out or "Invalid" in out
    assert validate_app_name(malicious) is None


def test_open_app_uses_open_cli(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "tools.system.subprocess.run",
        lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})(),
    )
    out = open_app("Safari")
    assert "Opened" in out
    assert calls == [["open", "-a", "Safari"]]


def test_send_email_rejects_invalid_address():
    out = send_email("not-an-email", "hi", "body")
    assert "Invalid email" in out


def test_monthly_budget_cap(temp_env, monkeypatch):
    monkeypatch.setattr(pipeline.costs, "get_spend", lambda period: 50.0 if period == "month" else 0.0)
    calls = []
    monkeypatch.setattr(pipeline, "_call_claude", lambda *a, **k: calls.append(1) or ("x", "m", 0.0))
    cfg = Config(daily_budget_usd=2.0, monthly_budget_usd=40.0)
    result = pipeline.process_query("hello", cfg)
    assert result["capped"] is True
    assert "month" in result["reply"].lower()
    assert calls == []


def test_interrupted_reply_not_stored_in_history(temp_env, monkeypatch):
    import conversation

    conversation.clear_history()
    monkeypatch.setattr(pipeline, "_call_claude", lambda *a, **k: ("Stopped.", "m", 0.0))
    pipeline._interrupt.set()
    try:
        pipeline.process_query("hello", Config())
    finally:
        pipeline._clear_interrupt()
    assert conversation.build_messages(8, 6000) == []


def test_confirm_ux_waiting_state_and_speech(temp_env, monkeypatch):
    """High-risk tools should announce approval and enter WAITING_CONFIRM before the modal wait."""
    import events

    pipeline._interrupt.clear()
    states: list[str] = []
    speaks: list[str] = []
    dispatch_order: list[str] = []

    monkeypatch.setattr(pipeline, "speak", lambda text, **kw: speaks.append(text))
    monkeypatch.setattr(
        pipeline,
        "dispatch_tool",
        lambda name, inp, **kw: dispatch_order.append(name) or "sent",
    )

    round_num = {"n": 0}

    class ToolBlock:
        type = "tool_use"
        id = "tu1"
        name = "send_email"
        input = {"to": "a@b.com", "subject": "s", "body": "b"}

    class TextBlock:
        type = "text"
        text = ""

    class TextOnly:
        type = "text"
        text = "Email sent."

    def fake_submit(fn, *args, **kwargs):
        round_num["n"] += 1
        content = [TextBlock(), ToolBlock()] if round_num["n"] == 1 else [TextOnly()]
        response = type("R", (), {"content": content, "usage": None})()

        class _Future:
            def done(self) -> bool:
                return True

            def result(self):
                return response

        return _Future()

    monkeypatch.setattr(pipeline._claude_executor, "submit", fake_submit)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def on_state(name: str) -> None:
        states.append(name)

    cfg = Config(confirm_before_execute=True)
    reply, _model, _cost = pipeline._call_claude(
        "send an email",
        cfg,
        on_state=on_state,
    )

    assert reply == "Email sent."
    assert states.index("WAITING_CONFIRM") < states.index("THINKING")
    assert speaks and "approval" in speaks[0].lower()
    assert dispatch_order == ["send_email"]
    assert speaks[0] == pipeline.CONFIRM_PROMPT
    assert events.get_state()["pipeline_state"] == "THINKING"


def test_create_claude_message_cancels_stream_on_interrupt():
    """Streaming call returns None and closes the connection when Stop fires."""
    pipeline._interrupt.clear()

    class FakeStream:
        def __iter__(self):
            yield from (1, 2, 3, 4, 5)

        def get_final_message(self):
            return "FINAL"

    class FakeCM:
        def __init__(self):
            self.closed = False
            self._stream = FakeStream()

        def __enter__(self):
            return self._stream

        def __exit__(self, *exc):
            self.closed = True
            return False

    class FakeMessages:
        def __init__(self):
            self.cm = FakeCM()

        def stream(self, **kwargs):
            return self.cm

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    client = FakeClient()
    assert pipeline._create_claude_message(client) == "FINAL"
    assert client.messages.cm.closed is True

    interrupted = FakeClient()
    pipeline._interrupt.set()
    try:
        assert pipeline._create_claude_message(interrupted) is None
        assert interrupted.messages.cm.closed is True
    finally:
        pipeline._interrupt.clear()
