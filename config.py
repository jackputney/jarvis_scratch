"""
config.py — Settings dataclass for Jarvis.

Loads configuration from config.json (user-editable, never committed with real values).
API keys are read from environment variables only — never from the config file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


# Config fields that live in config.json (everything except the env-only keys).
_PERSISTED_FIELDS = (
    "claude_model_fast",
    "claude_model_smart",
    "routing_word_threshold",
    "whisper_model",
    "cartesia_voice_id",
    "confirm_before_execute",
    "ui_enabled",
    "wake_word",
    "wake_word_enabled",
    "memory_inject_last_n_notes",
    "daily_budget_usd",
    "monthly_budget_usd",
)


@dataclass
class Config:
    claude_model_fast: str = "claude-haiku-4-5"
    claude_model_smart: str = "claude-sonnet-4-6"
    routing_word_threshold: int = 20
    whisper_model: str = "tiny"
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"
    confirm_before_execute: bool = True
    ui_enabled: bool = True
    wake_word: str = "hey_jarvis"  # openWakeWord pretrained model name; trigger phrase is "hey Jarvis"
    wake_word_enabled: bool = True
    memory_inject_last_n_notes: int = 5
    daily_budget_usd: float = 2.00
    monthly_budget_usd: float = 40.00

    # Derived from env — never stored in config.json
    anthropic_api_key: str = field(default="", repr=False)
    cartesia_api_key: str = field(default="", repr=False)

    @classmethod
    def load(cls) -> "Config":
        data: dict = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as fh:
                data = json.load(fh)

        cfg = cls(
            claude_model_fast=data.get("claude_model_fast", cls.claude_model_fast),
            claude_model_smart=data.get("claude_model_smart", cls.claude_model_smart),
            routing_word_threshold=data.get("routing_word_threshold", cls.routing_word_threshold),
            whisper_model=data.get("whisper_model", cls.whisper_model),
            cartesia_voice_id=data.get("cartesia_voice_id", cls.cartesia_voice_id),
            confirm_before_execute=data.get("confirm_before_execute", cls.confirm_before_execute),
            ui_enabled=data.get("ui_enabled", cls.ui_enabled),
            wake_word=data.get("wake_word", cls.wake_word),
            wake_word_enabled=data.get("wake_word_enabled", cls.wake_word_enabled),
            memory_inject_last_n_notes=data.get(
                "memory_inject_last_n_notes", cls.memory_inject_last_n_notes
            ),
            daily_budget_usd=data.get("daily_budget_usd", cls.daily_budget_usd),
            monthly_budget_usd=data.get("monthly_budget_usd", cls.monthly_budget_usd),
        )

        cfg.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        cfg.cartesia_api_key = os.environ.get("CARTESIA_API_KEY", "")

        return cfg

    def to_persisted_dict(self) -> dict:
        """Return only the config.json-backed fields (never the API keys)."""
        return {name: getattr(self, name) for name in _PERSISTED_FIELDS}

    @staticmethod
    def update_persisted(changes: dict) -> "Config":
        """Merge `changes` into config.json (coercing types) and return the
        freshly reloaded Config. Used by the dashboard settings panel so edits
        apply without a restart (the pipeline reloads config each cycle).
        Unknown keys and the env-only API keys are ignored.
        """
        current: dict = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as fh:
                current = json.load(fh)

        template = Config()
        for key, value in changes.items():
            if key not in _PERSISTED_FIELDS:
                continue
            default = getattr(template, key)
            try:
                if isinstance(default, bool):
                    value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
                elif isinstance(default, int):
                    value = int(value)
                elif isinstance(default, float):
                    value = float(value)
                else:
                    value = str(value)
            except (TypeError, ValueError):
                continue
            current[key] = value

        with open(CONFIG_PATH, "w") as fh:
            json.dump(current, fh, indent=2)
        return Config.load()

    def route_to_fast_model(self, text: str) -> bool:
        """Return True if the query should be sent to the fast (haiku) model.

        Heuristic: short queries OR queries that look like simple lookups use the
        fast model; anything else uses the smart model.
        """
        words = text.split()
        if len(words) <= self.routing_word_threshold:
            return True
        complex_keywords = {"explain", "write", "generate", "summarise", "summarize",
                            "analyse", "analyze", "compare", "plan", "design", "create",
                            "draft", "list all", "give me a", "how do i"}
        lower = text.lower()
        for kw in complex_keywords:
            if kw in lower:
                return False
        return len(words) <= self.routing_word_threshold + 10


def load_config() -> Config:
    """Module-level convenience wrapper around Config.load()."""
    return Config.load()
