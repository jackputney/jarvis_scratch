"""Stage 3 reflection — heuristic metrics + haiku-generated suggestions."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from config import Config
from improvement.stats import compute_stats, fetch_turns
from improvement.trace import _enqueue, _utc_now_iso, flush_writes

logger = logging.getLogger("jarvis.improvement.reflect")

METRIC_THRESHOLD = 0.10
HIGH_TOOL_ERROR_RATE = 0.20
VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})

_DEP_PACKAGES = ("anthropic", "elevenlabs", "openwakeword")


@dataclass
class SuggestionDraft:
    title: str
    body: str
    category: str
    severity: str
    proposed_change: str
    evidence_json: str

    @classmethod
    def from_llm_json(cls, raw: dict[str, Any], *, category: str, evidence: dict[str, Any]) -> SuggestionDraft:
        severity = str(raw.get("severity", "medium")).strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "medium"
        return cls(
            title=str(raw.get("title", "Improvement suggestion"))[:200],
            body=str(raw.get("body", ""))[:4000],
            category=category,
            severity=severity,
            proposed_change=str(raw.get("proposed_change", ""))[:8000],
            evidence_json=json.dumps(evidence, default=str),
        )


def persist_suggestion(draft: SuggestionDraft, *, status: str = "pending") -> str:
    sid = str(uuid.uuid4())
    _enqueue(
        "suggestion",
        sid,
        _utc_now_iso(),
        draft.title,
        draft.body,
        draft.category,
        draft.severity,
        status,
        draft.evidence_json,
        draft.proposed_change,
    )
    return sid


def fetch_suggestions(*, status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    from memory.db import connect

    limit = max(1, min(int(limit), 100))
    status = (status or "pending").strip().lower()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, title, body, category, severity, status,
                   evidence_json, proposed_change, github_issue_url
            FROM suggestions
            WHERE status = ?
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1
                END DESC,
                created_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    cols = [
        "id", "created_at", "title", "body", "category", "severity", "status",
        "evidence_json", "proposed_change", "github_issue_url",
    ]
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(cols, row))
        try:
            item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        except json.JSONDecodeError:
            item["evidence"] = {}
            item.pop("evidence_json", None)
        out.append(item)
    return out


def fetch_suggestion_by_id(suggestion_id: str) -> dict[str, Any] | None:
    from memory.db import connect

    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, created_at, title, body, category, severity, status,
                   evidence_json, proposed_change, github_issue_url
            FROM suggestions WHERE id = ?
            """,
            (suggestion_id,),
        ).fetchone()
    if not row:
        return None
    cols = [
        "id", "created_at", "title", "body", "category", "severity", "status",
        "evidence_json", "proposed_change", "github_issue_url",
    ]
    item = dict(zip(cols, row))
    try:
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
    except json.JSONDecodeError:
        item["evidence"] = {}
        item.pop("evidence_json", None)
    return item


def _store_github_issue_url(suggestion_id: str, url: str) -> None:
    _enqueue("suggestion_github", url, suggestion_id)


def _create_github_tracking_for_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    from tools.github_self import (
        create_own_branch,
        create_own_issue_url,
        extract_file_path_from_text,
        read_own_file_content,
    )

    sid = str(suggestion.get("id") or "")
    branch_name = f"jarvis/improvement/{sid}"
    branch_result = create_own_branch(branch_name)
    branch_url = branch_result if str(branch_result).startswith("http") else None

    proposed = str(suggestion.get("proposed_change") or "")
    file_path = extract_file_path_from_text(proposed)
    if not file_path:
        file_path = extract_file_path_from_text(json.dumps(suggestion.get("evidence") or {}, default=str))

    file_snippet = ""
    if file_path:
        content, err = read_own_file_content(file_path)
        if content and not err:
            file_snippet = f"\n\n## Current file ({file_path})\n```\n{content[:4000]}\n```"

    issue_title = f"[Jarvis Suggests] {suggestion.get('title', 'Improvement')}"
    issue_body = (
        f"{suggestion.get('body', '')}\n\n"
        f"## Proposed change\n{proposed}\n\n"
        f"## Evidence\n```json\n{json.dumps(suggestion.get('evidence') or {}, indent=2, default=str)[:4000]}\n```"
        f"{file_snippet}\n\n---\nSuggestion ID: `{sid}`"
    )
    if branch_url:
        issue_body += f"\nBranch: {branch_url}"

    url, err = create_own_issue_url(issue_title, issue_body, labels=["jarvis-suggests"])
    if url:
        _store_github_issue_url(sid, url)
        flush_writes()
        return {"ok": True, "github_issue_url": url, "branch_url": branch_url}

    logger.warning("⚠️  GitHub issue not created for suggestion %s: %s", sid, err)
    flush_writes()
    return {"ok": False, "github_issue_url": None, "error": err, "branch_url": branch_url}


def accept_suggestion(suggestion_id: str) -> dict[str, Any]:
    """Mark accepted and open a GitHub tracking issue + branch.

    Idempotent: if the suggestion is already accepted with a GitHub issue URL,
    returns the existing URL without creating a second issue.  If a previous
    accept run set status=accepted but failed before creating the issue, we
    retry the GitHub work without re-writing the DB status.
    """
    suggestion = fetch_suggestion_by_id(suggestion_id)
    if suggestion is None:
        return {"ok": False, "error": "not found"}
    if suggestion.get("github_issue_url"):
        return {"ok": True, "github_issue_url": suggestion["github_issue_url"]}
    already_accepted = suggestion.get("status") == "accepted"
    if not already_accepted:
        if not update_suggestion_status(suggestion_id, "accepted"):
            return {"ok": False, "error": "not found"}
        suggestion["status"] = "accepted"
    return _create_github_tracking_for_suggestion(suggestion)


def update_suggestion_status(suggestion_id: str, status: str) -> bool:
    from memory.db import connect

    status = (status or "").strip().lower()
    if status not in {"pending", "accepted", "dismissed"}:
        return False
    with connect() as conn:
        cur = conn.execute(
            "UPDATE suggestions SET status = ? WHERE id = ?",
            (status, suggestion_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def _append_source_snippet(
    proposed_change: str,
    *,
    source_path: str | None,
    source_code: str | None,
    max_lines: int = 40,
) -> str:
    if not source_path or not source_code:
        return proposed_change
    from tools.github_self import numbered_snippet

    block = numbered_snippet(source_code, max_lines=max_lines)
    if block in proposed_change:
        return proposed_change
    return (
        f"{proposed_change.rstrip()}\n\n"
        f"Current code ({source_path}):\n```\n{block}\n```"
    )


def _haiku_tool_suggestion(
    cfg: Config,
    *,
    tool_name: str,
    error_rate: float,
    errors: int,
    calls: int,
    source_path: str | None,
    source_code: str | None,
    evidence: dict[str, Any],
) -> SuggestionDraft | None:
    if not (cfg.anthropic_api_key or "").strip():
        return None
    from llm import get_llm_client
    from tools.github_self import numbered_snippet

    model = cfg.claude_model_fast
    client = get_llm_client(cfg, timeout=45.0, provider="anthropic")
    code_block = numbered_snippet(source_code or "", max_lines=60) if source_code else "(source not available)"
    prompt = (
        "You analyse Jarvis voice-assistant tool failures and propose one concrete code fix.\n"
        f"Tool: {tool_name}\n"
        f"Error rate: {error_rate:.0%} ({errors} errors / {calls + errors} invocations)\n"
        f"Evidence: {json.dumps(evidence, default=str)[:2000]}\n\n"
        f"Source file: {source_path or 'unknown'}\n"
        f"Numbered source:\n{code_block}\n\n"
        "Respond with JSON only:\n"
        '{"title": str, "body": str, "category": "tools", "severity": "low|medium|high|critical", '
        '"proposed_change": str}\n'
        "proposed_change must cite specific line numbers from the numbered source and show "
        "concrete before/after edits. Include a short quoted snippet of the current code. "
        "No markdown fences in JSON values."
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        blocks = getattr(response, "content", [])
        text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text")
        parsed = _parse_json_object(text)
        if not parsed:
            return None
        draft = SuggestionDraft.from_llm_json(parsed, category="tools", evidence=evidence)
        draft.proposed_change = _append_source_snippet(
            draft.proposed_change,
            source_path=source_path,
            source_code=source_code,
        )
        return draft
    except Exception as exc:  # noqa: BLE001
        logger.error("⚠️  Haiku tool reflection failed: %s", exc, exc_info=True)
        return None


def _haiku_suggestion(
    cfg: Config,
    *,
    category: str,
    metric_name: str,
    metric_value: float,
    evidence: dict[str, Any],
) -> SuggestionDraft | None:
    if not (cfg.anthropic_api_key or "").strip():
        logger.warning("⚠️  Skipping haiku reflection — no ANTHROPIC_API_KEY.")
        return None
    from llm import get_llm_client

    model = cfg.claude_model_fast
    client = get_llm_client(cfg, timeout=45.0, provider="anthropic")
    prompt = (
        "You analyse Jarvis voice-assistant telemetry and propose one concrete fix.\n"
        f"Metric: {metric_name} = {metric_value:.2%} (threshold {METRIC_THRESHOLD:.0%}).\n"
        f"Evidence: {json.dumps(evidence, default=str)[:3000]}\n\n"
        "Respond with JSON only:\n"
        '{"title": str, "body": str, "category": str, "severity": "low|medium|high|critical", '
        '"proposed_change": str}\n'
        "proposed_change should be actionable (config tweak, code hint, or workflow change). "
        "No markdown fences."
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        blocks = getattr(response, "content", [])
        text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text")
        parsed = _parse_json_object(text)
        if not parsed:
            return None
        parsed.setdefault("category", category)
        return SuggestionDraft.from_llm_json(parsed, category=category, evidence=evidence)
    except Exception as exc:  # noqa: BLE001
        logger.error("⚠️  Haiku reflection failed: %s", exc, exc_info=True)
        return None


def _metric_suggestions(cfg: Config, stats: dict[str, Any], turns: list[dict[str, Any]]) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    checks = [
        ("correction_rate", stats.get("correction_rate", 0.0), "corrections"),
        ("tool_error_rate", stats.get("tool_error_rate", 0.0), "tools"),
        ("tts_fallback_rate", stats.get("tts_fallback_rate", 0.0), "tts"),
        ("slow_turn_rate", stats.get("slow_turn_rate", 0.0), "latency"),
    ]
    for metric_name, value, category in checks:
        if float(value or 0) <= METRIC_THRESHOLD:
            continue
        evidence = {
            "metric": metric_name,
            "value": value,
            "threshold": METRIC_THRESHOLD,
            "sample_turns": turns[:5],
        }
        draft = _haiku_suggestion(
            cfg,
            category=category,
            metric_name=metric_name,
            metric_value=float(value),
            evidence=evidence,
        )
        if draft is not None:
            drafts.append(draft)
    return drafts


def _tool_offender_suggestions(cfg: Config, stats: dict[str, Any]) -> list[SuggestionDraft]:
    from tools.github_self import resolve_tool_source_path

    drafts: list[SuggestionDraft] = []
    for tool in stats.get("top_tools", []):
        errors = int(tool.get("error_count", 0))
        calls = int(tool.get("count", 0))
        if errors == 0:
            continue
        rate = errors / max(1, calls + errors)
        if rate <= METRIC_THRESHOLD:
            continue
        name = tool.get("name", "unknown")
        source_path, source_code = resolve_tool_source_path(name)
        evidence: dict[str, Any] = {"tool": tool, "error_rate": rate}
        if source_path:
            evidence["source_path"] = source_path

        if rate > HIGH_TOOL_ERROR_RATE:
            draft = _haiku_tool_suggestion(
                cfg,
                tool_name=name,
                error_rate=rate,
                errors=errors,
                calls=calls,
                source_path=source_path,
                source_code=source_code,
                evidence=evidence,
            )
            if draft is not None:
                drafts.append(draft)
                continue

        severity = "high" if rate > HIGH_TOOL_ERROR_RATE else "medium"
        proposed = (
            f"Inspect recent tool_error events for `{name}`; add validation or "
            f"clearer user-facing errors before retry."
        )
        proposed = _append_source_snippet(
            proposed,
            source_path=source_path,
            source_code=source_code,
            max_lines=20,
        )
        drafts.append(
            SuggestionDraft(
                title=f"Tool {name} failing often",
                body=(
                    f"{name} failed {errors} times out of {calls + errors} recent invocations "
                    f"({rate:.0%} error rate). Review inputs, permissions, and error payloads."
                ),
                category="tools",
                severity=severity,
                proposed_change=proposed,
                evidence_json=json.dumps(evidence, default=str),
            )
        )
    return drafts[:3]


def _dep_upgrade_suggestions(cfg: Config) -> list[SuggestionDraft]:
    api_key = (cfg.brave_api_key or "").strip()
    if not api_key:
        return []
    drafts: list[SuggestionDraft] = []
    try:
        from tools.web import web_search
    except ImportError:
        return []

    for pkg in _DEP_PACKAGES:
        try:
            result = web_search(f"{pkg} python latest release version 2026")
        except Exception:  # noqa: BLE001
            continue
        if not result or "error" in result.lower()[:80]:
            continue
        drafts.append(
            SuggestionDraft(
                title=f"Check {pkg} for updates",
                body=f"Web search summary for {pkg}:\n{result[:1200]}",
                category="dependencies",
                severity="low",
                proposed_change=f"Compare installed {pkg} version in requirements/pyproject with latest release.",
                evidence_json=json.dumps({"package": pkg, "search_preview": result[:500]}, default=str),
            )
        )
    return drafts


def run_reflection() -> list[dict[str, Any]]:
    """Run heuristic + haiku reflection; persist suggestions to SQLite."""
    cfg = Config.load()
    stats = compute_stats()
    turns = fetch_turns(limit=100)
    drafts: list[SuggestionDraft] = []
    drafts.extend(_metric_suggestions(cfg, stats, turns))
    drafts.extend(_tool_offender_suggestions(cfg, stats))
    drafts.extend(_dep_upgrade_suggestions(cfg))

    saved: list[dict[str, Any]] = []
    for draft in drafts:
        sid = persist_suggestion(draft)
        saved.append({
            "id": sid,
            "title": draft.title,
            "severity": draft.severity,
            "category": draft.category,
            "status": "pending",
        })
    flush_writes()
    logger.info("💡 Reflection generated %d suggestion(s).", len(saved))

    _auto_log_reflection(cfg, saved)

    return saved


def _auto_log_reflection(cfg: "Config", saved: list[dict[str, Any]]) -> None:
    """Silently append a brief reflection note to the Dev Log if Google OAuth is set up."""
    if not (cfg.google_client_id or "").strip():
        return
    try:
        import subprocess
        import sys

        branch = "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=3,
            )
            branch = result.stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001
            pass

        top_issue = saved[0]["title"] if saved else "none"
        lines = [
            f"Ran reflection: {len(saved)} suggestion(s) generated",
            f"Top issue: {top_issue}",
            f"Branch: {branch}",
        ]
        summary = "\n".join(lines)
        default_author = "Jack's Claude"
        author = f"{getattr(cfg, 'dev_log_author', default_author)} — auto"

        from tools.dev_log import append_dev_log_entry
        result = append_dev_log_entry(summary, author=author)
        logger.debug("📓 Auto dev-log: %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Auto dev-log skipped: %s", exc)
