"""Jarvis Hub — integration registry, keys, plugins, health."""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from dashboard.app import create_app
from hub.registry import get_status, load_integrations


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def hub_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# test\n", encoding="utf-8")
    monkeypatch.setattr("dashboard.hub_routes.ENV_PATH", env_file)
    monkeypatch.setattr("dashboard.hub_routes.PLUGINS_DIR", tmp_path / "plugins")
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)
    return env_file


def test_hub_status_shape(client):
    data = client.get("/api/hub/status").get_json()
    assert {"services", "orchestrator", "plugins", "spend"} <= data.keys()
    assert isinstance(data["services"], list)
    assert {"queue_depth", "current_job"} <= data["orchestrator"].keys()
    assert {"total", "active"} <= data["plugins"].keys()
    assert {"today", "month", "remaining"} <= data["spend"].keys()


def test_hub_integrations_list(client):
    data = client.get("/api/hub/integrations").get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    first = data[0]
    assert {"id", "name", "connected", "label"} <= first.keys()
    ids = {item["id"] for item in data}
    assert "anthropic" in ids


def test_hub_keys_writes_env(client, hub_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    r = client.post("/api/hub/keys", json={
        "integration_id": "brave",
        "fields": {"BRAVE_API_KEY": "BSA-test-secret"},
    })
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    content = hub_env.read_text(encoding="utf-8")
    assert "BRAVE_API_KEY=BSA-test-secret" in content
    assert "BSA-test-secret" not in str(r.get_json())


def test_hub_keys_writes_config(client, hub_env, temp_env):
    r = client.post("/api/hub/keys", json={
        "integration_id": "anthropic",
        "fields": {"DAILY_BUDGET_USD": "7.5"},
    })
    assert r.status_code == 200
    cfg = Config.load()
    assert cfg.daily_budget_usd == 7.5


def test_hub_registry_status_connected_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    load_integrations.cache_clear()
    status = get_status("anthropic", Config.load())
    assert status["connected"] is True
    assert status["label"] == "Connected"


def test_hub_registry_status_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    load_integrations.cache_clear()
    status = get_status("anthropic", Config())
    assert status["connected"] is False


def test_hub_plugin_generate_manifest_shape(client, hub_env, monkeypatch):
    manifest = {
        "name": "urgent_email_monitor",
        "description": "Notify on urgent mail",
        "trigger": {"type": "cron", "schedule": "*/5 * * * *"},
        "prompt": "Check inbox for urgent messages",
        "risk_tier": "read_only",
        "requires": ["google"],
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=json.dumps(manifest))]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic = MagicMock(return_value=mock_client)
    monkeypatch.setattr("anthropic.Anthropic", mock_anthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    r = client.post("/api/hub/plugins/generate", json={
        "description": "Monitor inbox for urgent emails",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["manifest"]["name"] == "urgent_email_monitor"
    saved = hub_env.parent / "plugins" / "urgent_email_monitor" / "manifest.json"
    assert saved.is_file()


def test_hub_plugin_generate_invalid_json_returns_422(client, hub_env, monkeypatch):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="not json at all")]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    monkeypatch.setattr("anthropic.Anthropic", MagicMock(return_value=mock_client))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    r = client.post("/api/hub/plugins/generate", json={"description": "test"})
    assert r.status_code == 422
    assert r.get_json()["error"] == "Claude returned invalid JSON"


def test_hub_google_auth_nonblocking(client, monkeypatch):
    def slow_auth(*_a, **_k):
        time.sleep(2)

    monkeypatch.setattr("tools.google_auth.ensure_google_ready", slow_auth)
    t0 = time.perf_counter()
    r = client.post("/api/hub/google/auth")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert elapsed_ms < 500


def test_api_plugins_list(client):
    data = client.get("/api/plugins").get_json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)
