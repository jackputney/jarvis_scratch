"""
memory/knowledge.py — Flat-folder Markdown note store for Jarvis.

Each topic is a single Markdown file under the user's memory folder
(``memory/knowledge/`` by default, or ``{memory_root}/notes/`` when configured).
Jarvis can read and write these files via tool calls; relevant notes are recalled
semantically (or by recency as fallback) into every system prompt.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

from memory import semantic, store

logger = logging.getLogger("jarvis.memory.knowledge")

# Back-compat for tests that monkeypatch this name directly.
KNOWLEDGE_DIR = store.notes_dir()

# Cap per-note size when injecting into the system prompt so a single large
# note can't blow up the token cost (and context window) of every Claude call.
MAX_NOTE_INJECT_CHARS = 2000
MAX_NOTES_BLOCK_CHARS = 8000
_TRUNCATION_MARKER = "\n…[truncated]"


def _notes() -> Path:
    return store.notes_dir()


def _ensure_dir() -> None:
    _notes().mkdir(parents=True, exist_ok=True)


def _safe_filename(title: str) -> str:
    """Convert a note title to a safe filename (lowercase, hyphens, .md)."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug + ".md"


def write_note(title: str, content: str) -> str:
    """Write or overwrite a Markdown note. Returns the file path as a string."""
    _ensure_dir()
    path = _notes() / _safe_filename(title)
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    semantic._index_file(path)
    return str(path)


def read_note(title: str) -> str | None:
    """Read a note by title. Returns the full Markdown content or None if not found."""
    _ensure_dir()
    path = _notes() / _safe_filename(title)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def delete_note(title: str) -> bool:
    """Delete a note by title. Returns True if the file existed and was removed."""
    _ensure_dir()
    path = _notes() / _safe_filename(title)
    if path.exists():
        path.unlink()
        semantic.reindex_all()
        return True
    return False


def list_notes() -> list[str]:
    """Return all note titles (filenames without extension, humanised)."""
    _ensure_dir()
    return [p.stem.replace("-", " ").title() for p in sorted(_notes().glob("*.md"))]


def get_recent_notes(n: int = 5) -> str:
    """Return the content of the N most recently modified notes concatenated."""
    _ensure_dir()
    files = sorted(_notes().glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    snippets: list[str] = []
    for path in files[:n]:
        content = path.read_text(encoding="utf-8")
        if len(content) > MAX_NOTE_INJECT_CHARS:
            keep = MAX_NOTE_INJECT_CHARS - len(_TRUNCATION_MARKER)
            logger.warning(
                "Note %r truncated for prompt injection (%d → %d chars)",
                path.name, len(content), MAX_NOTE_INJECT_CHARS,
            )
            content = content[:keep] + _TRUNCATION_MARKER
        snippets.append(content)
    if not snippets:
        return "(no notes yet)"
    block = "\n\n---\n\n".join(snippets)
    if len(block) > MAX_NOTES_BLOCK_CHARS:
        logger.warning(
            "Notes block truncated for prompt injection (%d → %d chars)",
            len(block), MAX_NOTES_BLOCK_CHARS,
        )
        keep = MAX_NOTES_BLOCK_CHARS - len(_TRUNCATION_MARKER)
        block = block[:keep] + _TRUNCATION_MARKER
    return block
