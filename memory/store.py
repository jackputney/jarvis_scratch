"""
memory/store.py — Resolve the user-assigned local memory folder.

When ``memory_root_path`` is set in config.json, all durable user memory
(notes, profile, diary, semantic index) lives under that folder on disk.
When unset, the project ``memory/`` directory is used (legacy layout).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config

_PROJECT_MEMORY = Path(__file__).parent
_memory_root_override: Path | None = None


def set_memory_root_override(path: Path | None) -> None:
    """Test hook — force a memory root without touching config.json."""
    global _memory_root_override
    _memory_root_override = path


def resolve_memory_root(cfg: "Config | None" = None) -> Path:
    if _memory_root_override is not None:
        return _memory_root_override.resolve()
    if cfg is None:
        from config import Config as _Config

        cfg = _Config.load()
    custom = (getattr(cfg, "memory_root_path", "") or "").strip()
    if custom:
        root = Path(custom).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return _PROJECT_MEMORY.resolve()


def notes_dir(cfg: "Config | None" = None) -> Path:
    root = resolve_memory_root(cfg)
    if root == _PROJECT_MEMORY.resolve():
        path = root / "knowledge"
    else:
        path = root / "notes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def diary_dir(cfg: "Config | None" = None) -> Path:
    path = resolve_memory_root(cfg) / "diary"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_path(cfg: "Config | None" = None) -> Path:
    return resolve_memory_root(cfg) / "profile.md"


def index_db_path(cfg: "Config | None" = None) -> Path:
    return resolve_memory_root(cfg) / "semantic_index.db"


def variables_db_path(cfg: "Config | None" = None) -> Path:
    return resolve_memory_root(cfg) / "variables.db"
