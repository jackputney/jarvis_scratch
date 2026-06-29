"""
conversation.py — In-memory rolling history for multi-turn Claude calls.

Persists only within a running Jarvis process (not SQLite). Capped by turn count
and approximate character budget so input tokens stay predictable.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

_lock = threading.Lock()
_turns: deque[tuple[str, str]] = deque(maxlen=50)


def clear_history() -> None:
    with _lock:
        _turns.clear()


def add_turn(user_text: str, assistant_text: str) -> None:
    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if not user_text and not assistant_text:
        return
    with _lock:
        _turns.append((user_text, assistant_text))


def _pairs_to_messages(
    pairs: list[tuple[str, str]],
    max_turns: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    max_turns = max(0, int(max_turns))
    max_chars = max(500, int(max_chars))
    if max_turns == 0 or not pairs:
        return []

    selected: list[tuple[str, str]] = []
    char_budget = 0
    for user_text, assistant_text in reversed(pairs[-max_turns:]):
        pair_chars = len(user_text) + len(assistant_text)
        if selected and char_budget + pair_chars > max_chars:
            break
        selected.append((user_text, assistant_text))
        char_budget += pair_chars

    messages: list[dict[str, Any]] = []
    for user_text, assistant_text in reversed(selected):
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    return messages


def build_messages(max_turns: int, max_chars: int) -> list[dict[str, Any]]:
    """Return prior turns as Anthropic messages (excludes the current user utterance)."""
    with _lock:
        pairs = list(_turns)
    return _pairs_to_messages(pairs, max_turns, max_chars)


def build_messages_from_session_turns(
    turns: list[Any],
    max_turns: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Build Anthropic messages from orchestrator Session.turns."""
    pairs: list[tuple[str, str]] = []
    for turn in turns:
        user_text = ""
        if turn.command is not None:
            user_text = (turn.command.text or "").strip()
        assistant_text = (turn.reply or "").strip()
        if user_text or assistant_text:
            pairs.append((user_text, assistant_text))
    return _pairs_to_messages(pairs, max_turns, max_chars)
