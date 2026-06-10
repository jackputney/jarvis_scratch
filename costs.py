"""
costs.py — Token tracking and budget accounting for Jarvis.

Every Claude call's real token usage (read from the Anthropic response `usage`
field — never estimated) is logged to the `usage_log` table in
memory/variables.db together with the computed USD cost. The pipeline uses
get_spend() to enforce daily/monthly budgets BEFORE each call.

Pricing (USD per million tokens, input / output):
    haiku   $1 / $5
    sonnet  $3 / $15
Unknown models fall back to sonnet pricing (the more expensive tier) so we can
never under-count spend.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "memory" / "variables.db"

# USD per single token (input, output).
_PER_MTOK = {
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
}
_DEFAULT_TIER = "sonnet"  # safest (most expensive) fallback for unknown models

_init_lock = threading.Lock()
_initialised = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    global _initialised
    if not _initialised:
        with _init_lock:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS usage_log ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  timestamp TEXT NOT NULL,"
                "  model TEXT NOT NULL,"
                "  input_tokens INTEGER NOT NULL,"
                "  output_tokens INTEGER NOT NULL,"
                "  cost_usd REAL NOT NULL,"
                "  query_preview TEXT"
                ")"
            )
            conn.commit()
            _initialised = True
    return conn


def _tier_for_model(model: str) -> str:
    lower = model.lower()
    if "haiku" in lower:
        return "haiku"
    if "sonnet" in lower:
        return "sonnet"
    return _DEFAULT_TIER


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the USD cost of a call given exact token counts."""
    in_rate, out_rate = _PER_MTOK[_tier_for_model(model)]
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0


def _extract_tokens(usage: Any) -> tuple[int, int]:
    """Pull (input_tokens, output_tokens) from an Anthropic usage object or dict."""
    if usage is None:
        return 0, 0
    if isinstance(usage, dict):
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    return int(getattr(usage, "input_tokens", 0)), int(getattr(usage, "output_tokens", 0))


def log_usage(model: str, usage: Any, query: str = "") -> float:
    """Record one Claude call's usage and return its USD cost.

    Args:
        model: The model name (used for pricing tier).
        usage: The Anthropic response `usage` object (or a dict / None).
        query: The user text, stored truncated as a preview.
    """
    input_tokens, output_tokens = _extract_tokens(usage)
    cost = compute_cost(model, input_tokens, output_tokens)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage_log "
            "(timestamp, model, input_tokens, output_tokens, cost_usd, query_preview) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                model,
                input_tokens,
                output_tokens,
                cost,
                (query or "")[:80],
            ),
        )
        conn.commit()
    return cost


def _period_start(period: str) -> str:
    """Return the ISO timestamp marking the start of the requested period."""
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        start = midnight
    elif period == "week":
        start = midnight - timedelta(days=now.weekday())  # Monday 00:00
    elif period == "month":
        start = midnight.replace(day=1)
    else:
        raise ValueError(f"Unknown period: {period!r} (use today/week/month)")
    return start.isoformat()


def get_spend(period: str) -> float:
    """Return total USD spend for 'today', 'week', or 'month'."""
    start = _period_start(period)
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM usage_log WHERE timestamp >= ?",
            (start,),
        ).fetchone()
    return float(row[0]) if row else 0.0


def get_spend_summary(daily_budget: float, monthly_budget: float) -> dict:
    """Convenience bundle for the dashboard spend panel."""
    today = get_spend("today")
    return {
        "today": round(today, 4),
        "week": round(get_spend("week"), 4),
        "month": round(get_spend("month"), 4),
        "daily_budget": daily_budget,
        "monthly_budget": monthly_budget,
        "daily_pct": round(100.0 * today / daily_budget, 1) if daily_budget > 0 else 0.0,
    }
