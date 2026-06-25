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
import os
import platform
import signal
import sys
import threading

from dotenv import load_dotenv

from paths import bootstrap_app_paths, env_path, is_frozen, log_dir, needs_onboarding

# Prepare user-data dirs and seed .env before loading config (frozen .app first launch).
bootstrap_app_paths()

# Load .env before importing anything that reads env vars
load_dotenv(env_path())

from config import Config

# Emoji-rich, single-line log output for the console (see project conventions).
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

        prepare_wake_word_model(cfg.wakeword_model or cfg.wake_word)
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
        if is_frozen():
            print()
            print("❌  Anthropic API key missing — run Jarvis again to open the setup wizard.")
            print(f"   Or add ANTHROPIC_API_KEY to: {env_path()}")
            print()
            sys.exit(1)
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


def _start_dashboard_window(cfg: Config) -> None:
    """Open the Flask dashboard in a native PyWebView window (macOS/Windows)."""
    if not cfg.dashboard_native_window:
        return
    try:
        from dashboard.window import native_window_supported, start_native_dashboard_window

        if not native_window_supported():
            print(f"⚠️  Native dashboard window unavailable (install pywebview). Use {DASHBOARD_URL}")
            return
        start_native_dashboard_window()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Native dashboard window unavailable ({exc}). Use {DASHBOARD_URL}")


def _start_hotkey(cfg: Config) -> None:
    """Register the global hotkey if enabled.  Graceful if pynput missing."""
    if not cfg.hotkey_enabled:
        return
    try:
        import pipeline as _pipeline
        from tools.hotkey import start_hotkey_listener

        start_hotkey_listener(cfg.hotkey_combo, _pipeline.request_wake)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Global hotkey registration failed ({exc}). Continuing without it.")


def _print_banner(cfg: Config) -> None:
    trigger = cfg.wake_word.replace("_", " ")
    resolved_stt = _resolve_stt_backend(cfg)
    print(f"🖥️  Platform       : {platform.system()} {platform.machine()}")
    print("🤖 Jarvis is up.")
    print(f"   🗣️  Trigger phrase : “{trigger}”" + ("" if cfg.wake_word_enabled else "  (voice disabled)"))
    print(f"   📊 Dashboard      : {DASHBOARD_URL}")
    if cfg.dashboard_native_window:
        from dashboard.window import native_window_supported

        if native_window_supported():
            print("   🪟 Dashboard UI   : native window (PyWebView)")
        else:
            print(f"   🪟 Dashboard UI   : browser ({DASHBOARD_URL}) — pip install pywebview for app window")
    if cfg.hotkey_enabled:
        print(f"   ⌨️  Global hotkey  : {cfg.hotkey_combo}")
    print(f"   🧠 Models         : {cfg.claude_model_fast} (fast) / {cfg.claude_model_smart} (smart)")
    print(f"   🎧 Whisper        : {cfg.stt_model} ({resolved_stt})")
    from tts.router import effective_tts_provider

    tts = effective_tts_provider(cfg)
    if cfg.tts_provider == "elevenlabs" and tts != "elevenlabs":
        print(
            f"   🔊 Voice (TTS)    : {tts} (ElevenLabs selected but ELEVENLABS_API_KEY missing — "
            "add it to .env or pick Cartesia in Settings)"
        )
    elif tts == "elevenlabs":
        from config import ELEVENLABS_VOICES

        name = next(
            (v["name"] for v in ELEVENLABS_VOICES if v["id"] == cfg.elevenlabs_voice_id),
            cfg.elevenlabs_voice_id[:8],
        )
        print(f"   🔊 Voice (TTS)    : ElevenLabs · {name}")
    else:
        print(f"   🔊 Voice (TTS)    : {tts}")
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


def _request_ui_shutdown(
    stop_event: threading.Event,
    graceful_shutdown,
    app,
    *,
    force_exit=None,
    timer_factory=None,
) -> None:
    """Synchronously tear down enough state that Ctrl+C cannot leave Jarvis listening."""
    logger.info("👋 Shutdown requested.")
    stop_event.set()
    try:
        import pipeline

        pipeline.request_interrupt()
    except Exception:  # noqa: BLE001
        logger.debug("pipeline interrupt during shutdown failed", exc_info=True)
    graceful_shutdown()
    try:
        app.quit()
    except Exception:  # noqa: BLE001
        logger.debug("Qt quit during shutdown failed", exc_info=True)
    if force_exit is not None and timer_factory is not None:
        timer_factory(1500, force_exit)


def _run_with_ui(cfg: Config) -> None:
    """Start the face widget on the main thread, pipeline on a daemon thread."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from ui.face import FaceWidget
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
    face.connect_pipeline_state()
    face.show_overlay()

    _start_dashboard_window(cfg)

    stop_event = threading.Event()
    _warmup_voice(cfg)
    _init_automation()

    shutdown_done = False
    shutdown_lock = threading.Lock()

    def graceful_shutdown() -> None:
        nonlocal shutdown_done
        with shutdown_lock:
            if shutdown_done:
                return
            shutdown_done = True
        logger.info("👋 Shutting down Jarvis.")
        stop_event.set()
        face.shutdown()
        if _scheduler is not None:
            _scheduler.shutdown()

    pipeline_thread = threading.Thread(
        target=run_pipeline,
        kwargs={
            "cfg": cfg,
            "stop_event": stop_event,
            "is_muted": lambda: face.muted,            # F10: pipeline honours the mute orb
            "budget_callback": face.set_budget_level,  # orb turns amber/red on spend
        },
        daemon=True,
    )
    pipeline_thread.start()
    _start_hotkey(cfg)

    def _handle_signal(_signum: int, _frame: object) -> None:
        _request_ui_shutdown(
            stop_event,
            graceful_shutdown,
            app,
            force_exit=lambda: os._exit(0),
            timer_factory=QTimer.singleShot,
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Let Python deliver SIGINT while Qt owns the main thread.
    sig_wakeup = QTimer()
    sig_wakeup.timeout.connect(lambda: None)
    sig_wakeup.start(250)

    app.aboutToQuit.connect(graceful_shutdown)
    exit_code = app.exec()
    graceful_shutdown()
    sys.exit(exit_code)


def _run_headless(cfg: Config) -> None:
    """Pipeline only — no UI."""
    from pipeline import request_interrupt, run_pipeline

    stop_event = threading.Event()
    _warmup_voice(cfg)
    _init_automation()
    _start_dashboard_window(cfg)
    pipeline_thread = threading.Thread(
        target=run_pipeline,
        kwargs={"cfg": cfg, "state_callback": None, "stop_event": stop_event},
        daemon=True,
    )
    pipeline_thread.start()
    _start_hotkey(cfg)

    def _shutdown_headless() -> None:
        print("\n👋 Shutting down Jarvis.")
        stop_event.set()
        request_interrupt()
        if _scheduler is not None:
            _scheduler.shutdown()

    def _handle_signal(_signum: int, _frame: object) -> None:
        _shutdown_headless()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        pipeline_thread.join()
    except KeyboardInterrupt:
        _shutdown_headless()
        sys.exit(0)


def _ensure_stdio_utf8() -> None:
    """Windows consoles often default to cp1252; banner emoji need UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if is_frozen():
        log_file = log_dir() / "jarvis.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=handlers)


def main() -> None:
    _ensure_stdio_utf8()
    _setup_logging()

    if needs_onboarding():
        try:
            from onboarding import run_onboarding_wizard

            if not run_onboarding_wizard():
                print("👋 Setup cancelled.")
                sys.exit(0)
            load_dotenv(env_path(), override=True)
            from config import Config as _Config

            _Config.invalidate_cache()
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Onboarding failed (%s). Add keys to .env manually.", exc)
            sys.exit(1)

    cfg = Config.load()
    _check_keys(cfg)
    _init_persistence()

    from telemetry import install_crash_handler
    install_crash_handler()
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
