"""
main.py — Entry point for Jarvis.

Startup sequence:
  1. Load config and validate API keys (.env). Missing ANTHROPIC_API_KEY is fatal
     with a clear, copy-pasteable message; missing CARTESIA_API_KEY just warns.
  2. Start the Flask control dashboard on a daemon thread (127.0.0.1:7777).
  3. Optionally start the PyQt6 face widget on the main thread.
  4. Start the voice pipeline on a daemon background thread.
  5. Enter the Qt event loop (or a simple blocking loop if UI is disabled).

The pipeline thread communicates state + budget changes to the UI via
FaceWidget.set_state()/set_budget_level(), which are thread-safe (they post to
the Qt event loop).

Run with:
  python main.py
"""

from __future__ import annotations

import logging
import platform
import sys
import threading

from dotenv import load_dotenv

# Load .env before importing anything that reads env vars
load_dotenv()

from config import Config

# Emoji-rich, single-line log output for the console (see project conventions).
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("jarvis")

DASHBOARD_URL = "http://127.0.0.1:7777"


def _resolve_stt_backend(cfg: Config) -> str:
    """Pick a working STT backend for this machine."""
    if cfg.stt_backend == "mlx":
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            logger.warning("⚠️  mlx-whisper unavailable — trying faster-whisper")
            try:
                from faster_whisper import WhisperModel  # noqa: F401
                return "faster"
            except ImportError:
                logger.error(
                    "❌  No STT backend available. Install mlx-whisper (macOS) "
                    "or faster-whisper (Windows/Linux)."
                )
                raise SystemExit(1) from None
    return cfg.stt_backend


def _init_persistence() -> None:
    from memory.db import enforce_retention, init_db
    from memory import semantic, store

    init_db()
    cfg = Config.load()
    enforce_retention(cfg.db_retention_days)
    store.resolve_memory_root()
    store.notes_dir()
    store.diary_dir()
    semantic.reindex_all()


_scheduler = None


def _init_automation() -> None:
    global _scheduler
    from orchestrator.runtime import get_orchestrator
    from plugins.loader import discover_plugins
    from plugins.scheduler import PluginScheduler

    orch = get_orchestrator()
    plugins = discover_plugins()
    _scheduler = PluginScheduler(orch)
    scheduled = _scheduler.register_plugins(plugins)
    print(f"   🔌 Plugins        : {len(plugins)} loaded · {scheduled} scheduled")


def _warmup_voice(cfg: Config) -> None:
    try:
        from pipeline import warmup_stt

        warmup_stt(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  STT warm-up skipped ({exc}).")


def _prepare_wake_word(cfg: Config) -> None:
    """Download wake word model before the pipeline thread starts (first-run UX)."""
    if not cfg.wake_word_enabled:
        return
    try:
        from pipeline import prepare_wake_word_model

        prepare_wake_word_model(cfg.wake_word)
    except RuntimeError as exc:
        print(f"⚠️  {exc}")
        print("   Wake word detection will not work until the model downloads (internet required on first launch).")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Could not prepare wake word model ({exc}).")


def _prepare_google(cfg: Config) -> None:
    if not cfg.google_client_id or not cfg.google_client_secret:
        return
    try:
        from tools.google_auth import ensure_google_ready

        ensure_google_ready(interactive=True)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Google sign-in skipped ({exc}). Google tools may fail until configured.")


def _check_keys(cfg: Config) -> None:
    if not cfg.anthropic_api_key:
        print()
        print("╔════════════════════════════════════════════════════════════╗")
        print("║  ❌  ANTHROPIC_API_KEY is not set — Jarvis can't think.       ║")
        print("╠════════════════════════════════════════════════════════════╣")
        print("║  Do this, then run again:                                    ║")
        print("║                                                              ║")
        print("║    1.  cp .env.example .env                                  ║")
        print("║    2.  open .env and add:                                    ║")
        print("║          ANTHROPIC_API_KEY=sk-ant-...                        ║")
        print("║    3.  python main.py                                        ║")
        print("║                                                              ║")
        print("║  Get a key at: https://console.anthropic.com/settings/keys   ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        sys.exit(1)
    if not cfg.cartesia_api_key:
        print("⚠️  CARTESIA_API_KEY not set — using local TTS (no streaming British voice).")
    if not cfg.google_client_id or not cfg.google_client_secret:
        print("⚠️  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set — Google tools disabled.")


def _start_dashboard() -> None:
    """Launch the Flask dashboard on a daemon thread (zero extra processes)."""
    try:
        from dashboard.app import run_dashboard
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Dashboard unavailable ({exc}). Continuing without it.")
        return
    threading.Thread(target=run_dashboard, daemon=True, name="jarvis-dashboard").start()


def _print_banner(cfg: Config) -> None:
    trigger = cfg.wake_word.replace("_", " ")
    resolved_stt = _resolve_stt_backend(cfg)
    print(f"🖥️  Platform       : {platform.system()} {platform.machine()}")
    print("🤖 Jarvis is up.")
    print(f"   🗣️  Trigger phrase : “{trigger}”" + ("" if cfg.wake_word_enabled else "  (voice disabled)"))
    print(f"   📊 Dashboard      : {DASHBOARD_URL}")
    print(f"   🧠 Models         : {cfg.claude_model_fast} (fast) / {cfg.claude_model_smart} (smart)")
    print(f"   🎧 Whisper        : {cfg.stt_model} ({resolved_stt})")
    print(f"   💰 Budget         : ${cfg.daily_budget_usd:.2f}/day · ${cfg.monthly_budget_usd:.2f}/month")
    from memory import store

    mem_root = store.resolve_memory_root(cfg)
    print(f"   🧠 Memory folder  : {mem_root}")
    confirm_label = (
        "dashboard (high-risk only)"
        if cfg.confirm_before_execute
        else "off"
    )
    print(f"   🔧 Confirm tools  : {confirm_label}")
    print(f"   🖥️  UI             : {'on' if cfg.ui_enabled else 'off'}")


def _run_with_ui(cfg: Config) -> None:
    """Start the face widget on the main thread, pipeline on a daemon thread."""
    from PyQt6.QtWidgets import QApplication
    from ui.face import FaceWidget, JarvisState
    from pipeline import run_pipeline
    from orchestrator.runtime import get_orchestrator

    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setApplicationDisplayName("Jarvis")
    app.setOrganizationName("Jarvis")
    app.setQuitOnLastWindowClosed(False)

    face = FaceWidget()
    # Stop button / Escape cancels the running turn and clears the queue.
    face.set_interrupt_callback(get_orchestrator().cancel_current)
    face.show_overlay()

    stop_event = threading.Event()
    _warmup_voice(cfg)
    _init_automation()

    def state_callback(state_name: str) -> None:
        try:
            state = JarvisState[state_name]
        except KeyError:
            return
        face.set_state(state)

    pipeline_thread = threading.Thread(
        target=run_pipeline,
        kwargs={
            "cfg": cfg,
            "state_callback": state_callback,
            "stop_event": stop_event,
            "is_muted": lambda: face.muted,            # F10: pipeline honours the mute orb
            "budget_callback": face.set_budget_level,  # orb turns amber/red on spend
        },
        daemon=True,
    )
    pipeline_thread.start()

    try:
        sys.exit(app.exec())
    except SystemExit:
        stop_event.set()
        face.shutdown()
        if _scheduler is not None:
            _scheduler.shutdown()


def _run_headless(cfg: Config) -> None:
    """Pipeline only — no UI."""
    from pipeline import run_pipeline

    stop_event = threading.Event()
    _warmup_voice(cfg)
    _init_automation()
    pipeline_thread = threading.Thread(
        target=run_pipeline,
        kwargs={"cfg": cfg, "state_callback": None, "stop_event": stop_event},
        daemon=True,
    )
    pipeline_thread.start()

    try:
        pipeline_thread.join()
    except KeyboardInterrupt:
        print("\n👋 Shutting down Jarvis.")
        stop_event.set()
        if _scheduler is not None:
            _scheduler.shutdown()


def main() -> None:
    cfg = Config.load()
    _check_keys(cfg)
    _init_persistence()
    _prepare_google(cfg)
    _prepare_wake_word(cfg)
    _start_dashboard()
    _print_banner(cfg)

    if cfg.ui_enabled:
        _run_with_ui(cfg)
    else:
        _run_headless(cfg)


if __name__ == "__main__":
    main()
