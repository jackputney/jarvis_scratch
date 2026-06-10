"""
memory/knowledge.py — Flat-folder Markdown note store for Jarvis.

Each topic is a single Markdown file in memory/knowledge/.
Jarvis can read and write these files via tool calls, and the N most recently
modified files are injected into every system prompt to give contextual memory
without a vector DB.
"""

from __future__ import annotations

import re
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# Cap per-note size when injecting into the system prompt so a single large
# note can't blow up the token cost (and context window) of every Claude call.
MAX_NOTE_INJECT_CHARS = 2000
_TRUNCATION_MARKER = "\n…[truncated]"


def _ensure_dir() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(title: str) -> str:
    """Convert a note title to a safe filename (lowercase, hyphens, .md)."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug + ".md"


def write_note(title: str, content: str) -> str:
    """Write or overwrite a Markdown note. Returns the file path as a string."""
    _ensure_dir()
    path = KNOWLEDGE_DIR / _safe_filename(title)
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    return str(path)


def read_note(title: str) -> str | None:
    """Read a note by title. Returns the full Markdown content or None if not found."""
    _ensure_dir()
    path = KNOWLEDGE_DIR / _safe_filename(title)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def delete_note(title: str) -> bool:
    """Delete a note by title. Returns True if the file existed and was removed."""
    _ensure_dir()
    path = KNOWLEDGE_DIR / _safe_filename(title)
    if path.exists():
        path.unlink()
        return True
    return False


def list_notes() -> list[str]:
    """Return all note titles (filenames without extension, humanised)."""
    _ensure_dir()
    return [p.stem.replace("-", " ").title() for p in sorted(KNOWLEDGE_DIR.glob("*.md"))]


def get_recent_notes(n: int = 5) -> str:
    """Return the content of the N most recently modified notes concatenated.

    Used to inject recent memory into the Claude system prompt. Each note is
    capped at MAX_NOTE_INJECT_CHARS characters with a clear [truncated] marker
    so the model knows content was cut and the prompt can't grow without bound.
    """
    _ensure_dir()
    files = sorted(KNOWLEDGE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    snippets: list[str] = []
    for path in files[:n]:
        content = path.read_text(encoding="utf-8")
        if len(content) > MAX_NOTE_INJECT_CHARS:
            keep = MAX_NOTE_INJECT_CHARS - len(_TRUNCATION_MARKER)
            content = content[:keep] + _TRUNCATION_MARKER
        snippets.append(content)
    return "\n\n---\n\n".join(snippets) if snippets else "(no notes yet)"
