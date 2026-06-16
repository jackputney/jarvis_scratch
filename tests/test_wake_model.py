"""Wake word model resolution and note injection caps."""

import pytest

from memory.knowledge import (
    MAX_NOTE_INJECT_CHARS,
    MAX_NOTES_BLOCK_CHARS,
    get_recent_notes,
    write_note,
)
from pipeline import WAKE_WORD_MODELS, resolve_wake_model, prepare_wake_word_model


@pytest.mark.parametrize(
    ("config_value", "expected"),
    [
        ("hey_jarvis", "hey_jarvis"),
        ("hey jarvis", "hey_jarvis"),
        ("alexa", "alexa"),
        ("something_unmapped", "hey_jarvis"),  # unknown → safe default
    ],
)
def test_resolve_wake_model_maps_config_to_openwakeword_id(config_value, expected):
    assert resolve_wake_model(config_value) == expected


def test_prepare_wake_word_model_resolves_before_ensure(monkeypatch):
    seen: list[str] = []

    def _capture(model: str) -> None:
        seen.append(model)

    monkeypatch.setattr("pipeline._ensure_wake_model", _capture)
    prepare_wake_word_model("hey_jarvis")
    assert seen == ["hey_jarvis"]


def test_get_recent_notes_caps_each_note(temp_env):
    write_note("Big", "x" * (MAX_NOTE_INJECT_CHARS + 500))
    block = get_recent_notes(1)
    assert len(block) <= MAX_NOTE_INJECT_CHARS
    assert block.endswith("…[truncated]")


def test_get_recent_notes_caps_total_block(temp_env):
    for i in range(6):
        write_note(f"Note{i}", "word " * 400)
    block = get_recent_notes(6)
    assert len(block) <= MAX_NOTES_BLOCK_CHARS
