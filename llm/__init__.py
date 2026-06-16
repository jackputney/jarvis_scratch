"""
llm/ — Pluggable LLM provider layer.

`get_llm_client(cfg)` returns a client that quacks like `anthropic.Anthropic`
(it exposes `.messages.stream(**kwargs)` / `.messages.create(**kwargs)` taking
Anthropic-format args and returning Anthropic-shaped responses). For the default
provider it returns the real Anthropic SDK client — the working path is
untouched. For "openai" / "gemini" it returns a translating adapter.

Selected via `cfg.llm_provider`. Adding a provider = one module + one branch
here; nothing downstream (pipeline tool loop, streaming, cost accounting)
changes.
"""

from __future__ import annotations

from typing import Any

PROVIDERS = ("anthropic", "openai", "gemini")


def get_llm_client(cfg: Any, timeout: float = 60.0) -> Any:
    provider = (getattr(cfg, "llm_provider", "anthropic") or "anthropic").strip().lower()

    if provider == "openai":
        from llm.openai_client import OpenAIClient
        return OpenAIClient(api_key=getattr(cfg, "openai_api_key", ""), timeout=timeout)

    if provider == "gemini":
        from llm.gemini_client import GeminiClient
        return GeminiClient(api_key=getattr(cfg, "gemini_api_key", ""), timeout=timeout)

    import anthropic
    return anthropic.Anthropic(api_key=cfg.anthropic_api_key, timeout=timeout)
