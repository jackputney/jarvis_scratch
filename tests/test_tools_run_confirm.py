"""Dashboard /api/tools/run — server-side confirm for high-risk tools."""

from unittest.mock import patch

import pytest

from dashboard.app import create_app


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_high_risk_tool_requires_confirm(client):
    r = client.post("/api/tools/run", json={
        "name": "send_email",
        "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["confirm_required"] is True
    assert body["confirm_id"]
    assert body["tool"] == "send_email"


def test_high_risk_tool_executes_after_confirm(client):
    with patch("tools.registry.send_email", return_value="Email sent."):
        first = client.post("/api/tools/run", json={
            "name": "send_email",
            "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
        }).get_json()
        second = client.post("/api/tools/run", json={
            "name": "send_email",
            "inputs": {"to": "a@b.com", "subject": "Hi", "body": "Test"},
            "confirm_id": first["confirm_id"],
            "confirmed": True,
        })
    assert second.status_code == 200
    assert second.get_json()["ok"] is True
    assert "sent" in second.get_json()["result"].lower()


def test_read_only_tool_runs_immediately(client, temp_env):
    r = client.post("/api/tools/run", json={
        "name": "set_variable",
        "inputs": {"key": "city", "value": "London"},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("confirm_required") is not True
    assert body["ok"] is True
