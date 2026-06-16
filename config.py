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
_ENV_PATH = Path(__file__).parent / ".env"

_cached_config: "Config | None" = None
_cached_mtime: float = -1.0


def _load_dotenv_if_present() -> None:
    if not _ENV_PATH.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=False)
    except ImportError:
        return


_PERSISTED_FIELDS = (
    "llm_provider",
    "claude_model_fast",
    "claude_model_smart",
    "openai_model_fast",
    "openai_model_smart",
    "gemini_model_fast",
    "gemini_model_smart",
    "routing_word_threshold",
    "whisper_model",
    "stt_backend",
    "stt_model",
    "streaming_tts",
    "cartesia_voice_id",
    "confirm_before_execute",
    "ui_enabled",
    "wake_word",
    "wake_word_enabled",
    "barge_in_enabled",
    "memory_inject_last_n_notes",
    "memory_root_path",
    "memory_auto_learn",
    "memory_semantic_recall",
    "memory_recall_top_k",
    "memory_diary_max_mb",
    "db_retention_days",
    "daily_budget_usd",
    "monthly_budget_usd",
    "google_client_id",
    "conversation_history_turns",
    "conversation_history_max_chars",
    "confirm_timeout_sec",
    "vad_silence_ms",
    "vad_min_capture_ms",
)


@dataclass
class Config:
    llm_provider: str = "anthropic"  # anthropic | openai | gemini | auto (per-turn routing)
    claude_model_fast: str = "claude-haiku-4-5"
    claude_model_smart: str = "claude-sonnet-4-6"
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_smart: str = "gpt-4o"
    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_smart: str = "gemini-2.5-pro"
    routing_word_threshold: int = 20
    whisper_model: str = "tiny"
    stt_backend: str = "mlx"
    stt_model: str = "tiny"
    streaming_tts: bool = True
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"
    confirm_before_execute: bool = True
    ui_enabled: bool = True
    wake_word: str = "hey_jarvis"
    wake_word_enabled: bool = True
    barge_in_enabled: bool = True  # say the wake word during a reply to cut it off and ask again
    memory_inject_last_n_notes: int = 5
    memory_root_path: str = ""
    memory_auto_learn: bool = True
    memory_semantic_recall: bool = True
    memory_recall_top_k: int = 5
    memory_diary_max_mb: int = 50
    db_retention_days: int = 90
    daily_budget_usd: float = 2.00
    monthly_budget_usd: float = 40.00
    google_client_id: str = ""
    conversation_history_turns: int = 8
    conversation_history_max_chars: int = 6000
    confirm_timeout_sec: int = 30
    vad_silence_ms: int = 1400
    vad_min_capture_ms: int = 2500

    anthropic_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    gemini_api_key: str = field(default="", repr=False)
    cartesia_api_key: str = field(default="", repr=False)
    google_client_secret: str = field(default="", repr=False)
    brave_api_key: str = field(default="", repr=False)

    @classmethod
    def _do_load(cls) -> "Config":
        _load_dotenv_if_present()
        data: dict = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as fh:
                data = json.load(fh)

        stt_model = data.get("stt_model") or data.get("whisper_model", cls.stt_model)
        cfg = cls(
            llm_provider=data.get("llm_provider", cls.llm_provider),
            claude_model_fast=data.get("claude_model_fast", cls.claude_model_fast),
            claude_model_smart=data.get("claude_model_smart", cls.claude_model_smart),
            openai_model_fast=data.get("openai_model_fast", cls.openai_model_fast),
            openai_model_smart=data.get("openai_model_smart", cls.openai_model_smart),
            gemini_model_fast=data.get("gemini_model_fast", cls.gemini_model_fast),
            gemini_model_smart=data.get("gemini_model_smart", cls.gemini_model_smart),
            routing_word_threshold=data.get("routing_word_threshold", cls.routing_word_threshold),
            whisper_model=data.get("whisper_model", cls.whisper_model),
            stt_backend=data.get("stt_backend", cls.stt_backend),
            stt_model=stt_model,
            streaming_tts=data.get("streaming_tts", cls.streaming_tts),
            cartesia_voice_id=data.get("cartesia_voice_id", cls.cartesia_voice_id),
            confirm_before_execute=data.get("confirm_before_execute", cls.confirm_before_execute),
            ui_enabled=data.get("ui_enabled", cls.ui_enabled),
            wake_word=data.get("wake_word", cls.wake_word),
            wake_word_enabled=data.get("wake_word_enabled", cls.wake_word_enabled),
            barge_in_enabled=data.get("barge_in_enabled", cls.barge_in_enabled),
            memory_inject_last_n_notes=data.get(
                "memory_inject_last_n_notes", cls.memory_inject_last_n_notes
            ),
            memory_root_path=data.get("memory_root_path", cls.memory_root_path),
            memory_auto_learn=data.get("memory_auto_learn", cls.memory_auto_learn),
            memory_semantic_recall=data.get(
                "memory_semantic_recall", cls.memory_semantic_recall
            ),
            memory_recall_top_k=data.get("memory_recall_top_k", cls.memory_recall_top_k),
            memory_diary_max_mb=data.get("memory_diary_max_mb", cls.memory_diary_max_mb),
            db_retention_days=data.get("db_retention_days", cls.db_retention_days),
            daily_budget_usd=data.get("daily_budget_usd", cls.daily_budget_usd),
            monthly_budget_usd=data.get("monthly_budget_usd", cls.monthly_budget_usd),
            google_client_id=data.get("google_client_id", cls.google_client_id),
            conversation_history_turns=data.get(
                "conversation_history_turns", cls.conversation_history_turns
            ),
            conversation_history_max_chars=data.get(
                "conversation_history_max_chars", cls.conversation_history_max_chars
            ),
            confirm_timeout_sec=data.get("confirm_timeout_sec", cls.confirm_timeout_sec),
            vad_silence_ms=data.get("vad_silence_ms", cls.vad_silence_ms),
            vad_min_capture_ms=data.get("vad_min_capture_ms", cls.vad_min_capture_ms),
        )

        cfg.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        cfg.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        cfg.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        cfg.cartesia_api_key = os.environ.get("CARTESIA_API_KEY", "")
        cfg.google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        cfg.brave_api_key = os.environ.get("BRAVE_API_KEY", "")
        env_google_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        if env_google_id:
            cfg.google_client_id = env_google_id
        elif cfg.google_client_id:
            os.environ.setdefault("GOOGLE_CLIENT_ID", cfg.google_client_id)
        return cfg

    @classmethod
    def load(cls) -> "Config":
        global _cached_config, _cached_mtime
        try:
            current_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0.0
        except OSError:
            current_mtime = 0.0
        if _cached_config is not None and current_mtime == _cached_mtime:
            return _cached_config
        cfg = cls._do_load()
        _cached_config = cfg
        _cached_mtime = current_mtime
        return cfg

    @classmethod
    def invalidate_cache(cls) -> None:
        global _cached_config, _cached_mtime
        _cached_config = None
        _cached_mtime = -1.0

    def effective_stt_model(self) -> str:
        return self.stt_model or self.whisper_model

    def to_persisted_dict(self) -> dict:
        return {name: getattr(self, name) for name in _PERSISTED_FIELDS}

    @staticmethod
    def update_persisted(changes: dict) -> "Config":
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
        Config.invalidate_cache()
        return Config.load()

    def route_to_fast_model(self, text: str) -> bool:
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
    return Config.load()
