"""
memory/semantic.py — Local semantic recall over the user's memory folder.

Notes, profile facts, and diary entries are chunked and indexed in SQLite FTS5.
At query time the most relevant chunks are injected into the system prompt so
Jarvis recalls context by meaning, not just recency.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from memory import store

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 480
MAX_INJECT_CHARS = 4000
_TRUNC = "\n…[truncated]"

# Diary auto-learn can persist pre-fix refusals ("can't open Windows apps"). Drop them
# from recall so they don't override live tool capabilities.
_STALE_CAPABILITY_DENIAL = re.compile(
    r"can't open arbitrary|cannot open arbitrary|"
    r"can't open .+ directly on windows|cannot open .+ on windows|"
    r"isn't in (my|that) list for me on windows|"
    r"i work with a specific set of apps|"
    r"hardcoded list of applications|"
    r"constrained to a hardcoded",
    re.IGNORECASE,
)


def _filter_recall_hits(hits: list[dict]) -> list[dict]:
    return [h for h in hits if not _STALE_CAPABILITY_DENIAL.search(h.get("chunk", ""))]


def _connect(cfg: "Config | None" = None) -> sqlite3.Connection:
    path = store.index_db_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks USING fts5(
            source UNINDEXED,
            title UNINDEXED,
            chunk,
            tokenize='unicode61'
        );
        """
    )
    return conn


def _chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > MAX_CHUNK_CHARS:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            for i in range(0, len(para), MAX_CHUNK_CHARS):
                chunks.append(para[i : i + MAX_CHUNK_CHARS])
            continue
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= MAX_CHUNK_CHARS:
            buf = candidate
        else:
            if buf:
                chunks.append(buf.strip())
            buf = para
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or ([text[:MAX_CHUNK_CHARS]] if text.strip() else [])


def _fts_query(raw: str) -> str:
    tokens = re.findall(r"\w{2,}", raw, flags=re.UNICODE)
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens[:14])


def _index_file(path: Path, cfg: "Config | None" = None) -> int:
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    rel = str(path.relative_to(store.resolve_memory_root(cfg)))
    title = path.stem.replace("-", " ").title()
    chunks = _chunk_text(text)
    if not chunks:
        return 0
    with _connect(cfg) as conn:
        conn.execute("DELETE FROM memory_chunks WHERE source = ?", (rel,))
        conn.executemany(
            "INSERT INTO memory_chunks(source, title, chunk) VALUES (?, ?, ?)",
            [(rel, title, c) for c in chunks],
        )
        conn.commit()
    return len(chunks)


def reindex_all(cfg: "Config | None" = None) -> int:
    """Rebuild the FTS index from notes, profile, and diary files."""
    root = store.resolve_memory_root(cfg)
    paths: list[Path] = []
    notes = store.notes_dir(cfg)
    paths.extend(sorted(notes.glob("*.md")))
    profile = store.profile_path(cfg)
    if profile.is_file():
        paths.append(profile)
    diary = store.diary_dir(cfg)
    paths.extend(sorted(diary.glob("*.md")))
    total = 0
    with _connect(cfg) as conn:
        conn.execute("DELETE FROM memory_chunks")
        conn.commit()
    for path in paths:
        total += _index_file(path, cfg)
    logger.info("🧠 Reindexed %d chunks from %d files in %s", total, len(paths), root)
    return total


def search(query: str, top_k: int = 5, cfg: "Config | None" = None) -> list[dict]:
    fts = _fts_query(query)
    if not fts:
        return []
    with _connect(cfg) as conn:
        rows = conn.execute(
            """
            SELECT source, title, chunk, rank
            FROM memory_chunks
            WHERE memory_chunks MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts, top_k),
        ).fetchall()
    return [{"source": r["source"], "title": r["title"], "chunk": r["chunk"]} for r in rows]


def remember(text: str, cfg: "Config | None" = None) -> str:
    """Append a durable fact to the user profile and index it."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "Nothing to remember."
    path = store.profile_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"- [{ts}] {cleaned}\n"
    if not path.is_file():
        path.write_text(f"# User profile\n\n## Facts\n{line}", encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    _index_file(path, cfg)
    logger.info("🧠 Remembered fact (%d chars)", len(cleaned))
    return f"Remembered: {cleaned[:120]}"


def build_recall_context(query: str, cfg: "Config | None" = None) -> str:
    """Return relevant memory snippets for prompt injection."""
    if cfg is None:
        from config import Config as _Config

        cfg = _Config.load()
    top_k = getattr(cfg, "memory_recall_top_k", 5)
    hits = search(query, top_k=top_k * 3, cfg=cfg)
    hits = _filter_recall_hits(hits)[:top_k]
    if not hits:
        from memory.knowledge import get_recent_notes

        fallback_n = getattr(cfg, "memory_inject_last_n_notes", 5)
        recent = get_recent_notes(fallback_n)
        return recent if recent != "(no notes yet)" else "(no memories yet)"
    parts: list[str] = []
    used = 0
    for hit in hits:
        block = f"### {hit['title']} ({hit['source']})\n{hit['chunk']}"
        if used + len(block) > MAX_INJECT_CHARS:
            remain = MAX_INJECT_CHARS - used - len(_TRUNC)
            if remain > 80:
                parts.append(block[:remain] + _TRUNC)
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)
