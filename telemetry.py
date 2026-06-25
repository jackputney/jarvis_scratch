"""telemetry.py — Local crash/error telemetry (SQLite, no external services)."""
from __future__ import annotations

import json, logging, sys, threading, traceback
from datetime import datetime
from typing import Any

from memory.db import connect, init_db

log = logging.getLogger("jarvis")
_installed = False
_table_ready = False
_table_lock = threading.Lock()
_orig_sys_excepthook = sys.excepthook


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        init_db()
        with connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crash_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    category  TEXT    NOT NULL,
                    message   TEXT    NOT NULL,
                    traceback_text TEXT,
                    thread_name    TEXT,
                    extra_json     TEXT
                )
                """
            )
            conn.commit()
        _table_ready = True


def _write_row(category: str, message: str, tb_text: str | None = None,
                thread_name: str | None = None, extra: dict[str, Any] | None = None) -> None:
    _ensure_table()
    with connect() as conn:
        conn.execute(
            "INSERT INTO crash_log "
            "(timestamp, category, message, traceback_text, thread_name, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                category,
                message[:2000],
                (tb_text or "")[:8000] or None,
                thread_name,
                json.dumps(extra)[:2000] if extra else None,
            ),
        )
        conn.commit()


def install_crash_handler() -> None:
    """Set sys.excepthook and threading.excepthook to capture unhandled exceptions."""
    global _installed
    if _installed:
        return

    _orig_sys = sys.excepthook

    def _sys_hook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical("Unhandled exception: %s: %s", exc_type.__name__, exc_value)
        _write_row(
            category=exc_type.__name__,
            message=str(exc_value),
            tb_text=tb,
            thread_name="MainThread",
        )
        _orig_sys(exc_type, exc_value, exc_tb)

    sys.excepthook = _sys_hook

    def _thread_hook(args):
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log.critical(
            "Unhandled exception in thread %s: %s: %s",
            args.thread.name if args.thread else "?",
            args.exc_type.__name__,
            args.exc_value,
        )
        _write_row(
            category=args.exc_type.__name__,
            message=str(args.exc_value),
            tb_text=tb,
            thread_name=args.thread.name if args.thread else None,
        )

    threading.excepthook = _thread_hook
    _installed = True


def log_error(category: str, message: str, extra: dict[str, Any] | None = None) -> None:
    """Manually log a caught error to the crash_log table."""
    log.error("[%s] %s", category, message)
    _write_row(
        category=category,
        message=message,
        tb_text=traceback.format_stack()[-2] if len(traceback.format_stack()) > 1 else None,
        thread_name=threading.current_thread().name,
        extra=extra,
    )


def get_recent_errors(limit: int = 20) -> list[dict[str, Any]]:
    """Return the last *limit* errors as a list of dicts."""
    _ensure_table()
    with connect() as conn:
        conn.row_factory = _dict_factory
        return conn.execute(
            "SELECT id, timestamp, category, message, traceback_text, thread_name, extra_json "
            "FROM crash_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def get_error_summary(hours: int = 24) -> list[dict[str, Any]]:
    """Return error counts grouped by category for the last *hours* hours."""
    _ensure_table()
    with connect() as conn:
        conn.row_factory = _dict_factory
        return conn.execute(
            "SELECT category, COUNT(*) AS count "
            "FROM crash_log "
            "WHERE timestamp >= datetime('now', ?) "
            "GROUP BY category ORDER BY count DESC",
            (f"-{hours} hours",),
        ).fetchall()


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def reset_for_tests() -> None:
    """Allow tests to re-init the crash_log table against a fresh DB."""
    global _table_ready, _installed
    _table_ready = False
    _installed = False
    sys.excepthook = _orig_sys_excepthook
