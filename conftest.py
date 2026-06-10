"""Shared pytest fixtures.

Redirects every persistent path (SQLite DB, config.json, knowledge notes) into a
per-test temp directory so the smoke tests never touch real user data, and resets
the lazily-initialised table flags so the temp DB gets its schema created.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    import config
    import costs
    import events
    from memory import knowledge, variables

    db = tmp_path / "variables.db"

    monkeypatch.setattr(costs, "DB_PATH", db)
    monkeypatch.setattr(costs, "_initialised", False)
    monkeypatch.setattr(events, "DB_PATH", db)
    monkeypatch.setattr(events, "_initialised", False)
    monkeypatch.setattr(variables, "DB_PATH", db)
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")

    events._events.clear()

    return tmp_path
