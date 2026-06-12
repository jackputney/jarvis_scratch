"""Shared pytest fixtures.

Redirects every persistent path (SQLite DB, config.json, knowledge notes) into a
per-test temp directory so the smoke tests never touch real user data, and resets
the lazily-initialised table flags so the temp DB gets its schema created.
"""

from __future__ import annotations

from pathlib import Path

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
    from memory import db as memory_db, knowledge, variables

    db = tmp_path / "variables.db"

    monkeypatch.setattr(memory_db, "DB_PATH", db)
    memory_db.reset_init_flag_for_tests()
    monkeypatch.setattr(costs, "DB_PATH", db)
    monkeypatch.setattr(events, "DB_PATH", db)
    monkeypatch.setattr(variables, "DB_PATH", db)
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")

    events._events.clear()

    return tmp_path
