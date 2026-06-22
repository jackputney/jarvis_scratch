"""Aggregate stats for dashboard read endpoints."""

from __future__ import annotations

import json
from typing import Any

from memory.db import connect


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[idx])


def compute_stats() -> dict[str, Any]:
    """Return summary metrics over all recorded turns."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT total_ms FROM turns WHERE total_ms IS NOT NULL"
        ).fetchall()
        turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        correction_count = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]

        tool_calls = conn.execute(
            "SELECT COUNT(*) FROM events WHERE type = 'tool_call'"
        ).fetchone()[0]
        tool_errors = conn.execute(
            "SELECT COUNT(*) FROM events WHERE type = 'tool_error'"
        ).fetchone()[0]
        tts_fallbacks = conn.execute(
            "SELECT COUNT(*) FROM events WHERE type = 'tts_fallback'"
        ).fetchone()[0]

        tool_rows = conn.execute(
            """
            SELECT json_extract(payload_json, '$.tool_name') AS name,
                   type
            FROM events
            WHERE type IN ('tool_call', 'tool_error')
              AND payload_json IS NOT NULL
            """
        ).fetchall()

    totals = [float(r[0]) for r in rows if r[0] is not None]
    avg_total = sum(totals) / len(totals) if totals else 0.0
    p95_total = _percentile(totals, 95)

    tool_map: dict[str, dict[str, int]] = {}
    for name, etype in tool_rows:
        key = name or "unknown"
        bucket = tool_map.setdefault(key, {"name": key, "count": 0, "error_count": 0})
        if etype == "tool_error":
            bucket["error_count"] += 1
        else:
            bucket["count"] += 1

    top_tools = sorted(
        tool_map.values(),
        key=lambda x: x["count"] + x["error_count"],
        reverse=True,
    )[:10]

    tc = max(1, int(turn_count))
    return {
        "total_turns": int(turn_count),
        "avg_total_ms": round(avg_total, 1),
        "p95_total_ms": round(p95_total, 1),
        "correction_rate": round(correction_count / tc, 4),
        "tool_error_rate": round(tool_errors / max(1, tool_calls + tool_errors), 4),
        "tts_fallback_rate": round(tts_fallbacks / tc, 4),
        "top_tools": top_tools,
    }


def fetch_turns(*, limit: int = 50, session_id: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    query = """
        SELECT turn_id, session_id, ts, source, wake_latency_ms, stt_text,
               stt_confidence, stt_ms, llm_ms, tool_ms, tts_ms, total_ms,
               model, tokens_in, tokens_out, cache_read_tokens,
               interrupted, cancelled, details_json
        FROM turns
    """
    params: list[Any] = []
    if session_id:
        query += " WHERE session_id = ?"
        params.append(session_id)
    query += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    with connect() as conn:
        rows = conn.execute(query, params).fetchall()

    cols = [
        "turn_id", "session_id", "ts", "source", "wake_latency_ms", "stt_text",
        "stt_confidence", "stt_ms", "llm_ms", "tool_ms", "tts_ms", "total_ms",
        "model", "tokens_in", "tokens_out", "cache_read_tokens",
        "interrupted", "cancelled", "details_json",
    ]
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(cols, row))
        if item.get("details_json"):
            try:
                item["details"] = json.loads(item["details_json"])
            except json.JSONDecodeError:
                item["details"] = {}
        else:
            item["details"] = {}
        del item["details_json"]
        out.append(item)
    return out


def fetch_events(*, turn_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT event_id, turn_id, ts, type, payload_json
            FROM events
            WHERE turn_id = ?
            ORDER BY ts ASC
            """,
            (turn_id,),
        ).fetchall()

    events: list[dict[str, Any]] = []
    for eid, tid, ts, etype, payload in rows:
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {}
        events.append({
            "event_id": eid,
            "turn_id": tid,
            "ts": ts,
            "type": etype,
            "payload": data,
        })
    return events
