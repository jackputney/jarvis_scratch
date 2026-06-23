"""Semantic memory — local folder, FTS recall, diary learning."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import Config
from memory import knowledge, semantic, store
from memory.learn import record_exchange


@pytest.fixture
def memory_root(temp_env, monkeypatch):
    root = temp_env / "jarvis_memory"
    root.mkdir()
    from memory import store

    monkeypatch.setattr(store, "_memory_root_override", root)
    (root / "notes").mkdir()
    return root


def test_default_memory_root_is_project_memory(temp_env, monkeypatch):
    monkeypatch.setattr(store, "_memory_root_override", None)
    cfg = Config.load()
    root = store.resolve_memory_root(cfg)
    assert root.name == "memory"
    assert store.notes_dir(cfg).name == "knowledge"


def test_custom_memory_root_from_config(temp_env, monkeypatch):
    monkeypatch.setattr(store, "_memory_root_override", None)
    custom = temp_env / "my_jarvis"
    Config.update_persisted({"memory_root_path": str(custom)})
    cfg = Config.load()
    assert store.resolve_memory_root(cfg) == custom.resolve()
    assert store.notes_dir(cfg) == (custom / "notes").resolve()


def test_remember_appends_to_profile(memory_root):
    semantic.remember("Prefers morning workouts", cfg=None)
    profile = store.profile_path()
    text = profile.read_text(encoding="utf-8")
    assert "Prefers morning workouts" in text
    assert profile.exists()


def test_semantic_search_finds_relevant_note(memory_root):
    knowledge.write_note("Fitness", "User trains at 6am before work.")
    semantic.reindex_all()
    hits = semantic.search("trains before work", top_k=3)
    assert hits
    assert any("6am" in h["chunk"] or "trains" in h["chunk"] for h in hits)


def test_build_recall_context_includes_matching_memory(memory_root):
    knowledge.write_note("Diet", "User is vegetarian and avoids dairy.")
    semantic.reindex_all()
    cfg = Config.load()
    block = semantic.build_recall_context("what can I eat for lunch", cfg)
    assert "vegetarian" in block.lower() or "dairy" in block.lower()


def test_record_exchange_writes_diary(memory_root):
    cfg = Config.load()
    cfg.memory_auto_learn = True
    record_exchange("I moved to Bristol last week.", "Noted.", cfg)
    diary_files = list((memory_root / "diary").glob("*.md"))
    assert len(diary_files) == 1
    assert "Bristol" in diary_files[0].read_text(encoding="utf-8")


def test_record_exchange_skipped_when_disabled(memory_root):
    cfg = Config.load()
    cfg.memory_auto_learn = False
    record_exchange("Secret thing.", "OK.", cfg)
    assert not (memory_root / "diary").exists()


def test_write_note_triggers_reindex(memory_root):
    knowledge.write_note("Pets", "Two cats named Pixel and Byte.")
    hits = semantic.search("cats", top_k=2)
    assert hits
    assert "Pixel" in hits[0]["chunk"]


def test_filter_recall_hits_drops_stale_windows_denials():
    hits = [
        {"source": "diary/x.md", "title": "Today", "chunk": "User asked to open Spotify."},
        {
            "source": "diary/x.md",
            "title": "Today",
            "chunk": "I can't open arbitrary Windows applications by name the way I can on Mac.",
        },
    ]
    filtered = semantic._filter_recall_hits(hits)
    assert len(filtered) == 1
    assert "Spotify" in filtered[0]["chunk"]


def test_build_recall_context_skips_stale_capability_denials(memory_root, monkeypatch):
    stale = {
        "source": "diary/x.md",
        "title": "Today",
        "chunk": "I can't open arbitrary Windows applications by name.",
    }
    good = {
        "source": "notes/prefs.md",
        "title": "Prefs",
        "chunk": "User prefers dark mode.",
    }
    monkeypatch.setattr(
        semantic,
        "search",
        lambda query, top_k=5, cfg=None: [stale, good][:top_k],
    )
    block = semantic.build_recall_context("open discord", Config.load())
    assert "arbitrary windows" not in block.lower()
    assert "dark mode" in block.lower()
