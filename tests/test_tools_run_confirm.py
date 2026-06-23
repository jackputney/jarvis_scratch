"""Dashboard /api/tools/run — server-side confirm for high-risk tools."""

from unittest.mock import patch

import pytest

from dashboard.app import create_app
from dashboard.tools_run_confirm import reset_for_tests as reset_tools_run_confirm


@pytest.fixture
def client(temp_env):
    reset_tools_run_confirm()
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture(autouse=True)
def _clear_tools_run_confirm():
    reset_tools_run_confirm()
    yield
    reset_tools_run_confirm()


def test_high_risk_tool_requires_confirm(client):
    r = client.post("/api/tools/run", json={
        "name": "send_email",
        "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body is not None
    assert body.get("confirm_required") is True
    assert body.get("confirm_id")
    assert body.get("tool") == "send_email"


def test_high_risk_tool_executes_after_confirm(client):
    with patch("tools.registry.send_email", return_value="Email sent."):
        first = client.post("/api/tools/run", json={
            "name": "send_email",
            "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
        }).get_json()
        assert first is not None, "expected JSON body from confirm step"
        assert first.get("confirm_id"), f"missing confirm_id: {first!r}"
        second = client.post("/api/tools/run", json={
            "name": "send_email",
            "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
            "confirm_id": first["confirm_id"],
            "confirmed": True,
        })
    assert second.status_code == 200
    body = second.get_json()
    assert body is not None
    assert body.get("ok") is True
    assert "sent" in (body.get("result") or "").lower()


def test_read_only_tool_runs_immediately(client, temp_env):
    r = client.post("/api/tools/run", json={
        "name": "set_variable",
        "inputs": {"key": "city", "value": "London"},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body is not None
    assert body.get("confirm_required") is not True
    assert body.get("ok") is True
