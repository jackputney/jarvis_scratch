"""
llm/router.py — Per-turn provider routing for llm_provider="auto".

A lightweight, zero-latency heuristic picks the provider best suited to the
current request, then the existing fast→smart escalation handles difficulty
*within* that provider. Routing only ever picks a provider whose API key is
configured; everything falls back to the first available provider (Anthropic
when present).

Balanced strategy — match request shape to provider strength:
  • images / vision        → Gemini   (native multimodal)
  • long context / summarise → Gemini (huge context window, fast)
  • code / debugging        → Anthropic (Claude is strong at code + reasoning)
  • structured extraction   → OpenAI   (reliable JSON / function output)
  • quick factual lookups   → Gemini   (flash tier is fast + cheap)
  • writing / general chat  → Anthropic (default all-rounder)
"""

from __future__ import annotations

import re
from typing import Any

LONG_CONTEXT_CHARS = 4000

_IMAGE_HINTS = re.compile(
    r"\b(image|images|photo|photos|picture|pictures|screenshot|screenshots|"
    r"diagram|chart|look at this|what'?s in this|describe (the|this))\b", re.I
)
_LONG_HINTS = re.compile(
    r"\b(summari[sz]e|summary of|tl;?dr|this (document|doc|article|transcript|essay|paper)|"
    r"the (transcript|attached))\b", re.I
)
_CODE_HINTS = re.compile(
    r"\b(code|function|debug|bug|stack ?trace|traceback|regex|python|javascript|typescript|"
    r"java|c\+\+|rust|golang|sql|refactor|compile|exception|api endpoint)\b", re.I
)
_STRUCTURED_HINTS = re.compile(
    r"\b(json|extract|parse|classify|categori[sz]e|table|csv|schema|structured|"
    r"list of|key-?value|fields?)\b", re.I
)
_QUICK_HINTS = re.compile(
    r"^\s*(what|when|who|where|which|define|how many|how much|is|are|whats|what's)\b", re.I
)


def models_for(provider: str, cfg: Any) -> tuple[str, str]:
    """Return (fast_model, smart_model) for a provider from config."""
    table = {
        "anthropic": (cfg.claude_model_fast, cfg.claude_model_smart),
        "openai": (cfg.openai_model_fast, cfg.openai_model_smart),
        "gemini": (cfg.gemini_model_fast, cfg.gemini_model_smart),
    }
    return table.get(provider, (cfg.claude_model_fast, cfg.claude_model_smart))


def available_providers(cfg: Any) -> list[str]:
    """Providers with a configured API key, in preference order."""
    avail = []
    if getattr(cfg, "anthropic_api_key", ""):
        avail.append("anthropic")
    if getattr(cfg, "openai_api_key", ""):
        avail.append("openai")
    if getattr(cfg, "gemini_api_key", ""):
        avail.append("gemini")
    return avail


def classify(text: str, cfg: Any) -> str:
    """Pick the best available provider for this request (heuristic, balanced)."""
    avail = available_providers(cfg)
    if not avail:
        return "anthropic"

    def pick(preferred: str, *fallbacks: str) -> str:
        for p in (preferred, *fallbacks):
            if p in avail:
                return p
        return avail[0]

    t = text or ""

    if _IMAGE_HINTS.search(t):
        return pick("gemini", "anthropic", "openai")
    if len(t) >= LONG_CONTEXT_CHARS or _LONG_HINTS.search(t):
        return pick("gemini", "anthropic", "openai")
    if _CODE_HINTS.search(t):
        return pick("anthropic", "openai", "gemini")
    if _STRUCTURED_HINTS.search(t):
        return pick("openai", "anthropic", "gemini")
    if len(t) <= 80 and _QUICK_HINTS.search(t):
        return pick("gemini", "anthropic", "openai")
    # writing / general conversation → balanced default
    return pick("anthropic", "openai", "gemini")


def resolve_models(text: str, cfg: Any) -> tuple[str, str, str]:
    """Return (provider, fast_model, smart_model) for this turn.

    Honours a fixed cfg.llm_provider; routes per-request only when it is "auto".
    """
    provider = (getattr(cfg, "llm_provider", "anthropic") or "anthropic").strip().lower()
    if provider == "auto":
        provider = classify(text, cfg)
    fast, smart = models_for(provider, cfg)
    return provider, fast, smart
