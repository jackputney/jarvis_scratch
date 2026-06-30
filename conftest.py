"""Shared pytest fixtures.

Redirects every persistent path (SQLite DB, config.json, memory folder) into a
per-test temp directory so the smoke tests never touch real user data, and resets
the lazily-initialised table flags so the temp DB gets its schema created.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Optional native deps — allow unit tests without a full audio stack installed.
for _optional in ("pyaudio", "mlx_whisper", "openwakeword", "webrtcvad"):
    if _optional not in sys.modules:
        sys.modules[_optional] = MagicMock()

import pytest

# Explicit path — find_dotenv() walks the call stack and breaks under heredocs / -c.
_PROJECT_ROOT = Path(__file__).resolve().parent
_ENV_FILE = _PROJECT_ROOT / ".env"


@pytest.fixture(scope="session", autouse=True)
def _load_env_for_integration_tests():
    """Load .env when present so ad-hoc integration checks see API keys."""
    if _ENV_FILE.is_file():
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    import config
    import costs
    import events
    from memory import db as memory_db, store, variables

    db = tmp_path / "variables.db"
    (tmp_path / "notes").mkdir()
    monkeypatch.setattr(store, "_memory_root_override", tmp_path)
    monkeypatch.setattr(memory_db, "DB_PATH", db)
    memory_db.reset_init_flag_for_tests()
    memory_db.init_db()
    monkeypatch.setattr(costs, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    monkeypatch.setattr(variables, "DB_PATH", db)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")

    events._events.clear()

    try:
        from dashboard.tools_run_confirm import reset_for_tests as reset_tools_run_confirm
        from tools.confirm import reset_for_tests as reset_voice_confirm

        reset_tools_run_confirm()
        reset_voice_confirm()
    except Exception:  # noqa: BLE001
        pass

    return tmp_path
