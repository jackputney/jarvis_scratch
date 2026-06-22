"""Correction and repeat-request heuristics (pure Python, no I/O)."""

from __future__ import annotations

import re

_NEGATION_PREFIX = re.compile(
    r"^\s*(no\b|nope\b|not\b|wrong\b|i said\b|that's not\b|that is not\b)",
    re.IGNORECASE,
)


def _tokenise(text: str | None) -> set[str]:
    if not text:
        return set()
    return {w for w in re.findall(r"\w{3,}", text.lower(), flags=re.UNICODE)}


def _overlap_ratio(a: str | None, b: str | None) -> float:
    ta, tb = _tokenise(a), _tokenise(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def detect_correction(prev_text: str | None, curr_text: str | None) -> str | None:
    """Return correction kind or None.

    - ``asr_correction``: high token overlap with previous turn (>60%)
    - ``command_correction``: leading negation phrase
    """
    curr = (curr_text or "").strip()
    if not curr:
        return None
    if _NEGATION_PREFIX.search(curr):
        return "command_correction"
    prev = (prev_text or "").strip()
    if prev and _overlap_ratio(prev, curr) > 0.6:
        return "asr_correction"
    return None


def detect_repeat_request(
    turn_history: list[str],
    curr_text: str | None,
    *,
    window: int = 3,
) -> bool:
    """True when *curr_text* closely repeats a recent user utterance."""
    curr = (curr_text or "").strip()
    if not curr:
        return False
    recent = [t for t in turn_history[-window:] if (t or "").strip()]
    return any(_overlap_ratio(t, curr) > 0.7 for t in recent)
