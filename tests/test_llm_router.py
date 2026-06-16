"""Per-turn LLM router — heuristic classification, availability, model resolution."""

from types import SimpleNamespace as NS

from llm.router import available_providers, classify, models_for, resolve_models

MODELS = dict(
    claude_model_fast="claude-haiku-4-5", claude_model_smart="claude-sonnet-4-6",
    openai_model_fast="gpt-4o-mini", openai_model_smart="gpt-4o",
    gemini_model_fast="gemini-2.5-flash", gemini_model_smart="gemini-2.5-pro",
)


def _cfg(provider="auto", anthropic=True, openai=True, gemini=True):
    return NS(
        llm_provider=provider,
        anthropic_api_key="k" if anthropic else "",
        openai_api_key="k" if openai else "",
        gemini_api_key="k" if gemini else "",
        **MODELS,
    )


def test_available_providers_filters_by_key():
    assert available_providers(_cfg()) == ["anthropic", "openai", "gemini"]
    assert available_providers(_cfg(openai=False)) == ["anthropic", "gemini"]
    assert available_providers(_cfg(anthropic=False, gemini=False)) == ["openai"]


def test_classify_routes_by_request_shape():
    cfg = _cfg()
    assert classify("Can you debug this Python function and fix the traceback?", cfg) == "anthropic"
    assert classify("Look at this screenshot and tell me what's wrong", cfg) == "gemini"
    assert classify("Extract the fields as JSON from this", cfg) == "openai"
    assert classify("What time is it in Tokyo?", cfg) == "gemini"  # quick factual
    assert classify("Summarize this document for me", cfg) == "gemini"
    assert classify("x" * 5000, cfg) == "gemini"  # long context
    assert classify("Write me a thank-you note to my team", cfg) == "anthropic"  # writing/default


def test_classify_respects_availability():
    # Structured normally → openai, but with no openai key it falls back to anthropic.
    assert classify("extract as json", _cfg(openai=False)) == "anthropic"
    # Vision normally → gemini, but with only openai available it falls back to openai.
    assert classify("describe this image", _cfg(anthropic=False, gemini=False)) == "openai"
    # No keys at all → safe anthropic default.
    assert classify("anything", _cfg(anthropic=False, openai=False, gemini=False)) == "anthropic"


def test_models_for():
    cfg = _cfg()
    assert models_for("anthropic", cfg) == ("claude-haiku-4-5", "claude-sonnet-4-6")
    assert models_for("openai", cfg) == ("gpt-4o-mini", "gpt-4o")
    assert models_for("gemini", cfg) == ("gemini-2.5-flash", "gemini-2.5-pro")


def test_resolve_models_fixed_provider_bypasses_routing():
    cfg = _cfg(provider="openai")
    assert resolve_models("describe this image", cfg) == ("openai", "gpt-4o-mini", "gpt-4o")


def test_resolve_models_auto_routes():
    cfg = _cfg(provider="auto")
    provider, fast, smart = resolve_models("debug this stack trace", cfg)
    assert provider == "anthropic"
    assert (fast, smart) == ("claude-haiku-4-5", "claude-sonnet-4-6")
    provider, _, _ = resolve_models("describe this photo", cfg)
    assert provider == "gemini"
