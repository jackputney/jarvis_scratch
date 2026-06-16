"""Calendar reminder plugin and scheduler tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from plugins.loader import discover_plugins
from plugins.manifest import validate_manifest
from plugins.scheduler import PluginScheduler


def test_calendar_reminder_manifest_valid():
    path = Path(__file__).resolve().parent.parent / "plugins" / "calendar_reminder" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert validate_manifest(data) is None


def test_calendar_reminder_manifest_fields():
    path = Path(__file__).resolve().parent.parent / "plugins" / "calendar_reminder" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "calendar_reminder"
    assert data["trigger"]["type"] == "cron"
    assert data["trigger"]["schedule"] == "*/30 * * * *"
    assert data["risk_tier"] == "read_only"
    assert "google" in data["requires"]


def test_scheduler_parses_every_30_min():
    s = PluginScheduler(MagicMock())
    assert s._parse_interval("*/30 * * * *") == 1800


def test_scheduler_parses_daily_8am():
    s = PluginScheduler(MagicMock())
    result = s._parse_interval("0 8 * * *")
    assert result is not None
    assert result > 0


def test_scheduler_fires_plugin():
    fired: list[str] = []
    orch = MagicMock()
    orch.submit.side_effect = lambda cmd: fired.append(cmd.text) or MagicMock(accepted=True)
    s = PluginScheduler(orch)
    plugin = {
        "name": "test",
        "trigger": {"type": "cron", "schedule": "*/30 * * * *"},
        "prompt": "test prompt",
        "enabled": True,
    }
    s._fire(plugin)
    assert len(fired) == 1
    assert fired[0] == "test prompt"
    s.shutdown()


def test_discover_plugins_finds_calendar_reminder():
    plugins = discover_plugins()
    names = [p["name"] for p in plugins]
    assert "calendar_reminder" in names


def test_discover_plugins_skips_invalid(tmp_path):
    bad_dir = tmp_path / "bad_plugin"
    bad_dir.mkdir()
    (bad_dir / "manifest.json").write_text('{"name": "bad"}', encoding="utf-8")
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 0
