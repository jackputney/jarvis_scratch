"""Stage 2 eval judge — score Jarvis responses against golden cases."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("jarvis.improvement.judge")

_BEHAVIOR_PROMPTS = {
    "asks_clarification_or_uses_tool": (
        "The assistant should either call a contacts/search tool or ask a brief "
        "clarifying question — not refuse access or hallucinate a phone number."
    ),
}


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _check_must_not_contain(response: str, phrases: list[str]) -> tuple[bool, str]:
    lower = (response or "").lower()
    for phrase in phrases:
        if phrase.lower() in lower:
            return False, f"response contains forbidden phrase: {phrase!r}"
    return True, ""


def _check_must_use_tool(tools_called: list[str], tool_name: str) -> tuple[bool, str]:
    if tool_name in tools_called:
        return True, ""
    return False, f"expected tool {tool_name!r}, got {tools_called!r}"


def _check_must_not_use_tool(tools_called: list[str]) -> tuple[bool, str]:
    if tools_called:
        return False, f"expected no tools, got {tools_called!r}"
    return True, ""


def _score_behavior_with_haiku(
    golden: dict[str, Any],
    actual_response: str,
    tools_called: list[str],
    *,
    model: str = "claude-haiku-4-5",
) -> tuple[bool, str]:
    behavior = golden.get("expected_behavior", "")
    hint = _BEHAVIOR_PROMPTS.get(
        behavior,
        f"The assistant should satisfy expected_behavior={behavior!r}.",
    )
    prompt = (
        f"Golden case id: {golden.get('id', '?')}\n"
        f"User input: {golden.get('input', '')}\n"
        f"Tools called: {tools_called}\n"
        f"Assistant response: {actual_response}\n\n"
        f"Criterion: {hint}\n\n"
        "Reply with JSON only: {\"pass\": true|false, \"reason\": \"one sentence\"}"
    )
    try:
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text if msg.content else "{}"
        data = json.loads(raw.strip())
        ok = bool(data.get("pass"))
        return ok, str(data.get("reason", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Haiku judge failed for %s: %s", golden.get("id"), exc)
        return False, f"judge error: {exc}"


def judge_turn(
    golden: dict[str, Any],
    actual_response: str,
    tools_called: list[str],
    *,
    use_haiku: bool = True,
) -> dict[str, Any]:
    """Score a Jarvis response against a golden case.

    Returns ``{"pass": bool, "score": float, "reason": str, "case_id": str}``.
    """
    case_id = str(golden.get("id", "unknown"))
    checks: list[tuple[bool, str]] = []
    tools_called = list(tools_called or [])

    if golden.get("must_use_tool"):
        checks.append(_check_must_use_tool(tools_called, str(golden["must_use_tool"])))

    if golden.get("must_not_use_tool"):
        checks.append(_check_must_not_use_tool(tools_called))

    if golden.get("max_words") is not None:
        wc = _word_count(actual_response)
        limit = int(golden["max_words"])
        ok = wc <= limit
        checks.append((ok, f"word count {wc} vs max {limit}"))

    if golden.get("must_not_contain"):
        phrases = golden["must_not_contain"]
        if isinstance(phrases, str):
            phrases = [phrases]
        checks.append(_check_must_not_contain(actual_response, list(phrases)))

    if golden.get("requires_confirmation"):
        # Golden cases document intent; confirm is enforced at dispatch time.
        checks.append((True, "confirmation requirement noted"))

    if golden.get("expected_behavior") and use_haiku:
        ok, reason = _score_behavior_with_haiku(golden, actual_response, tools_called)
        checks.append((ok, reason or "haiku behavior check"))

    if not checks:
        return {"pass": True, "score": 1.0, "reason": "no criteria", "case_id": case_id}

    passed = sum(1 for ok, _ in checks if ok)
    score = passed / len(checks)
    failures = [msg for ok, msg in checks if not ok and msg]
    overall = all(ok for ok, _ in checks)
    reason = "; ".join(failures) if failures else "all checks passed"
    return {
        "pass": overall,
        "score": round(score, 3),
        "reason": reason,
        "case_id": case_id,
    }
