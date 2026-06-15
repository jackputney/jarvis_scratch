"""
memory/learn.py — Continuous learning from conversations.

Each exchange can be appended to a daily diary file in the user's memory folder
and re-indexed for semantic recall on future turns.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from memory import semantic, store

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_MIN_USER_CHARS = 8


def _diary_size_bytes(diary_dir: Path) -> int:
    if not diary_dir.is_dir():
        return 0
    return sum(f.stat().st_size for f in diary_dir.glob("*.md") if f.is_file())


def record_exchange(user: str, assistant: str, cfg: "Config | None" = None) -> None:
    """Append a turn to today's diary when auto-learn is enabled."""
    if cfg is None:
        from config import Config as _Config

        cfg = _Config.load()
    if not getattr(cfg, "memory_auto_learn", True):
        return
    user_clean = (user or "").strip()
    assistant_clean = (assistant or "").strip()
    if len(user_clean) < _MIN_USER_CHARS or not assistant_clean:
        return
    diary_dir = store.diary_dir(cfg)
    max_bytes = int(getattr(cfg, "memory_diary_max_mb", 50)) * 1024 * 1024
    if _diary_size_bytes(diary_dir) >= max_bytes:
        logger.warning(
            "📓 Diary folder exceeds %d MB cap — skipping auto-learn entry.",
            getattr(cfg, "memory_diary_max_mb", 50),
        )
        return
    path = diary_dir / f"{date.today().isoformat()}.md"
    stamp = datetime.now().strftime("%H:%M")
    entry = (
        f"\n## {stamp}\n"
        f"**User:** {user_clean}\n"
        f"**Jarvis:** {assistant_clean}\n"
    )
    if not path.is_file():
        path.write_text(f"# Diary — {date.today().isoformat()}\n{entry}", encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(entry)
    semantic._index_file(path, cfg)
    logger.debug("📓 Diary entry recorded (%s)", path.name)
