"""Plugin discovery, scheduler, webhooks, and manifest validation."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dashboard.app import create_app
from plugins.loader import discover_plugins
from plugins.manifest import validate_manifest
from plugins.scheduler import PluginScheduler


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_discover_plugins_finds_manifests(tmp_path):
    plugin_dir = tmp_path / "morning_briefing"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({
        "name": "morning_briefing",
        "description": "Daily briefing",
        "trigger": {"type": "cron", "schedule": "0 8 * * *"},
        "prompt": "Brief me",
        "risk_tier": "read_only",
    }), encoding="utf-8")
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0]["name"] == "morning_briefing"


def test_discover_plugins_skips_invalid_json(tmp_path):
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    assert discover_plugins(tmp_path) == []


def test_scheduler_registers_cron_plugins():
    orch = MagicMock()
    scheduler = PluginScheduler(orch)
    plugins = [{
        "name": "tick",
        "enabled": True,
        "trigger": {"type": "cron", "schedule": "*/1 * * * *"},
        "prompt": "ping",
    }]
    count = scheduler.register_plugins(plugins)
    assert count == 1
    scheduler.shutdown()


def test_scheduler_fires_command_to_orchestrator():
    orch = MagicMock()
    orch.submit.return_value = MagicMock(accepted=True, job_id="j1")
    scheduler = PluginScheduler(orch)
    plugin = {
        "name": "instant",
        "enabled": True,
        "trigger": {"type": "cron", "schedule": "*/1 * * * *"},
        "prompt": "Run now",
    }
    scheduler.register_plugins([plugin])
    scheduler._fire(plugin)
    orch.submit.assert_called_once()
    cmd = orch.submit.call_args[0][0]
    assert cmd.source.value == "schedule"
    scheduler.shutdown()


def test_webhook_handler_matches_plugin(client, temp_env, tmp_path, monkeypatch):
    plugin_dir = tmp_path / "alert_hook"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({
        "name": "alert_hook",
        "description": "Webhook alert",
        "trigger": {"type": "webhook", "path": "hooks/alert_hook"},
        "prompt": "Process alert",
        "risk_tier": "read_only",
    }), encoding="utf-8")
    monkeypatch.setattr("paths.bundled_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr("paths.user_plugins_dir", lambda: tmp_path / "user_plugins")
    r = client.post("/hooks/alert_hook", json={"event": "ping"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert r.get_json()["job_id"]


def test_webhook_handler_unknown_plugin_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr("paths.bundled_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr("paths.user_plugins_dir", lambda: tmp_path / "user_plugins")
    r = client.post("/hooks/unknown", json={})
    assert r.status_code == 404


def test_manifest_validation_rejects_missing_fields():
    err = validate_manifest({"name": "bad"})
    assert err is not None
    assert "Missing required keys" in err


def test_plugin_manifest_validation_rejects_bad_tier():
    err = validate_manifest({
        "name": "test_plugin",
        "description": "x",
        "trigger": {"type": "cron", "schedule": "0 8 * * *"},
        "prompt": "go",
        "risk_tier": "dangerous",
    })
    assert err is not None
    assert "risk_tier" in err


def test_plugin_manifest_validation_requires_cron_schedule():
    err = validate_manifest({
        "name": "test_plugin",
        "description": "x",
        "trigger": {"type": "cron"},
        "prompt": "go",
        "risk_tier": "read_only",
    })
    assert err is not None
    assert "schedule" in err


def test_morning_briefing_manifest_is_valid():
    path = Path(__file__).resolve().parent.parent / "plugins" / "morning_briefing" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert validate_manifest(data) is None
