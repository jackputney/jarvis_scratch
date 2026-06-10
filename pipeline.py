"""
pipeline.py — The Jarvis voice pipeline.

Single clean loop:
  wake word detected → record audio → VAD trim → Whisper STT →
  budget check → route → Claude (with tools) → log cost → TTS → back to listening

ONE microphone stream is shared by the whole app (see _audio_loop): a single
audio thread reads the mic and either feeds wake detection, routes frames into a
capture queue for the recorder, or drains them (echo guard during think/speak).

The query side is factored into process_query(), which both the voice loop and
the dashboard's text box call. It enforces the daily budget before every Claude
call (80% → one-time spoken warning, 100% → hard stop), times each call, logs exact
token usage to costs.py, and records the exchange via events.py.

Config is reloaded fresh each cycle so dashboard edits apply without a restart;
changing the wake word transparently rebuilds the audio thread.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import anthropic
import pyaudio
import webrtcvad

import costs
import events
from config import Config
from memory.knowledge import get_recent_notes
from memory.variables import build_variables_block
from tools.registry import TOOL_DEFINITIONS, dispatch_tool
from tts.cartesia import speak

logger = logging.getLogger("jarvis.pipeline")

# ---------------------------------------------------------------------------
# Audio constants
# ---------------------------------------------------------------------------

AUDIO_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(AUDIO_RATE * FRAME_DURATION_MS / 1000)
CHANNELS = 1
PA_FORMAT = pyaudio.paInt16
SAMPLE_WIDTH = 2
MAX_RECORD_SECONDS = 20
POST_SPEECH_SILENCE_FRAMES = 25
WAIT_FOR_SPEECH_FRAMES = int(4000 / FRAME_DURATION_MS)
PRE_ROLL_FRAMES = 8
WAKE_THRESHOLD = 0.5
AUDIO_THREAD_RESTART_DELAY = 2.0

# Spoken budget messages.
WARN_80_MESSAGE = "Heads up, I'm at 80 percent of today's budget."
CAP_MESSAGE = "I've hit today's budget cap — raise it in the dashboard if you need me."

# One-time 80% warning bookkeeping (resets each calendar day).
_warn_state: dict[str, Any] = {"date": None}


# ---------------------------------------------------------------------------
# Wake word model bootstrap (F2)
# ---------------------------------------------------------------------------

def _ensure_wake_model(wake_word: str) -> None:
    """Ensure the openWakeWord ONNX model for `wake_word` is present on disk."""
    try:
        from openwakeword import MODELS
    except ImportError:
        return

    if wake_word not in MODELS:
        logger.warning(
            "⚠️  Wake word %r has no pretrained model. Available: %s",
            wake_word, ", ".join(sorted(MODELS.keys())),
        )
        return

    model_path = MODELS[wake_word]["model_path"]
    onnx_path = os.path.splitext(model_path)[0] + ".onnx"
    if os.path.exists(onnx_path):
        return

    download_name = os.path.splitext(os.path.basename(model_path))[0]
    logger.info("⬇️  First run: downloading wake word model %r…", download_name)
    try:
        from openwakeword.utils import download_models
        download_models([download_name])
    except Exception as exc:
        msg = (
            f"❌  Could not download the wake word model {download_name!r}. "
            f"Check your internet connection and try again. ({exc})"
        )
        logger.error(msg)
        raise RuntimeError(msg) from exc

    if not os.path.exists(onnx_path):
        msg = (
            f"❌  Wake model download finished but {onnx_path} is still missing — "
            f"openWakeWord asset names may have changed."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("✅  Wake word model ready: %s", os.path.basename(onnx_path))


# ---------------------------------------------------------------------------
# Shared audio thread: wake detection + frame routing
# ---------------------------------------------------------------------------

def _reset_oww(model: Any) -> None:
    try:
        for buf in model.prediction_buffer.values():
            buf.clear()
    except Exception:  # noqa: BLE001
        pass


def _drain_queue(q: "queue.Queue[bytes]") -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def _audio_loop(
    wake_event: threading.Event,
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    audio_stop: threading.Event,
    wake_word: str,
) -> None:
    """Own the single mic stream and route frames by mode. Returns when
    audio_stop is set; raises on hard failure so the supervisor can rebuild it."""
    import numpy as np
    from openwakeword.model import Model

    oww_model = Model(wakeword_models=[wake_word], inference_framework="onnx")
    pa = pyaudio.PyAudio()
    stream = pa.open(
        rate=AUDIO_RATE,
        channels=CHANNELS,
        format=PA_FORMAT,
        input=True,
        frames_per_buffer=FRAME_SIZE,
    )
    logger.info("👂 Wake word listener active — say '%s' to activate", wake_word)

    was_inactive = False
    try:
        while not audio_stop.is_set():
            data = stream.read(FRAME_SIZE, exception_on_overflow=False)

            if capturing.is_set():
                capture_queue.put(data)
                was_inactive = True
                continue

            if paused.is_set():
                was_inactive = True
                continue

            if was_inactive:
                _reset_oww(oww_model)
                was_inactive = False

            audio_int16 = np.frombuffer(data, dtype=np.int16)
            oww_model.predict(audio_int16)
            for name, scores in oww_model.prediction_buffer.items():
                if scores[-1] > WAKE_THRESHOLD:
                    logger.info("🎙️  Wake word '%s' detected (score=%.2f)", name, scores[-1])
                    _reset_oww(oww_model)
                    wake_event.set()
                    break
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def _start_audio_thread(
    wake_event: threading.Event,
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    audio_stop: threading.Event,
    wake_word: str,
) -> threading.Thread:
    """Spawn the self-healing daemon thread that owns the mic."""
    def _run() -> None:
        try:
            import openwakeword.model  # noqa: F401
        except ImportError:
            logger.warning(
                "⚠️  openwakeword not installed — wake word disabled. "
                "Press Enter to simulate a wake trigger."
            )
            while not audio_stop.is_set():
                try:
                    input()
                    if not (capturing.is_set() or paused.is_set()):
                        wake_event.set()
                except EOFError:
                    time.sleep(3600)
            return

        while not audio_stop.is_set():
            try:
                _audio_loop(wake_event, capture_queue, capturing, paused, audio_stop, wake_word)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "⚠️  Audio listener crashed (%s) — restarting in %.0fs",
                    exc, AUDIO_THREAD_RESTART_DELAY, exc_info=True,
                )
                time.sleep(AUDIO_THREAD_RESTART_DELAY)

    t = threading.Thread(target=_run, daemon=True, name="jarvis-audio")
    t.start()
    return t


# ---------------------------------------------------------------------------
# Utterance capture
# ---------------------------------------------------------------------------

def _record_from_queue(capture_queue: "queue.Queue[bytes]") -> bytes:
    """Drain frames from the shared audio thread, trimming with VAD. Returns
    b"" if no speech was detected within the wait window."""
    vad = webrtcvad.Vad(2)
    frames: list[bytes] = []
    silent_frames = 0
    speech_started = False
    max_frames = int(MAX_RECORD_SECONDS * 1000 / FRAME_DURATION_MS)

    logger.info("🎙️  Listening…")
    for i in range(max_frames):
        try:
            data = capture_queue.get(timeout=MAX_RECORD_SECONDS)
        except queue.Empty:
            break

        is_speech = vad.is_speech(data, AUDIO_RATE)
        if is_speech:
            speech_started = True
            silent_frames = 0
            frames.append(data)
        elif speech_started:
            silent_frames += 1
            frames.append(data)
            if silent_frames > POST_SPEECH_SILENCE_FRAMES:
                break
        else:
            frames.append(data)
            if len(frames) > PRE_ROLL_FRAMES:
                frames.pop(0)
            if i > WAIT_FOR_SPEECH_FRAMES:
                break

    if not speech_started:
        return b""
    return b"".join(frames)


# ---------------------------------------------------------------------------
# Whisper transcription (mlx-whisper)
# ---------------------------------------------------------------------------

def _transcribe(audio_bytes: bytes, cfg: Config) -> str:
    import mlx_whisper  # type: ignore[import]
    import numpy as np

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    repo = f"mlx-community/whisper-{cfg.whisper_model}-mlx"
    result = mlx_whisper.transcribe(audio_np, path_or_hf_repo=repo)
    text: str = result.get("text", "").strip()
    logger.info("📝 Heard: %r", text)
    return text


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(cfg: Config) -> str:
    variables_block = build_variables_block()
    notes_block = get_recent_notes(cfg.memory_inject_last_n_notes)
    return (
        "You are Jarvis, a fast personal AI assistant. You are direct, honest, and never "
        "flatter. You flag uncertainty rather than guessing. You have access to tools — use "
        "them when the task requires it, not otherwise. Keep spoken responses concise (under "
        "40 words for simple questions). You know the following about the user:\n"
        f"{variables_block}\n\nRecent notes:\n{notes_block}"
    )


# ---------------------------------------------------------------------------
# Claude call with tool loop — logs exact usage per call (costs.py)
# ---------------------------------------------------------------------------

def _call_claude(text: str, cfg: Config) -> tuple[str, str, float]:
    """Run the Claude tool loop. Returns (reply_text, model, total_cost_usd).

    Token usage is read from each response's `usage` field and logged via
    costs.log_usage after every call — never estimated.
    """
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    model = cfg.claude_model_fast if cfg.route_to_fast_model(text) else cfg.claude_model_smart
    logger.info("🧠 Routing to %s", model)

    messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
    system_prompt = _build_system_prompt(cfg)
    total_cost = 0.0

    for _ in range(5):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        total_cost += costs.log_usage(model, getattr(response, "usage", None), text)

        reply_text = ""
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                reply_text += block.text
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

        if not tool_uses:
            return reply_text.strip(), model, total_cost

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            logger.info("🔧 Tool: %s(%s)", tu["name"], tu["input"])
            result = dispatch_tool(tu["name"], tu["input"], confirm=cfg.confirm_before_execute)
            logger.info("   → %s", result[:120])
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    return "I ran into an issue completing that. Please try again.", model, total_cost


# ---------------------------------------------------------------------------
# Budget enforcement + shared query path (voice loop AND dashboard text box)
# ---------------------------------------------------------------------------

def _should_warn_80() -> bool:
    """Return True at most once per calendar day (for the 80% spoken warning)."""
    today = date.today().isoformat()
    if _warn_state["date"] == today:
        return False
    _warn_state["date"] = today
    return True


def budget_level(cfg: Config) -> str:
    """Return 'capped' | 'warn' | 'normal' for today's spend against the budget."""
    spend = costs.get_spend("today")
    if cfg.daily_budget_usd > 0 and spend >= cfg.daily_budget_usd:
        return "capped"
    if cfg.daily_budget_usd > 0 and spend >= 0.8 * cfg.daily_budget_usd:
        return "warn"
    return "normal"


def process_query(text: str, cfg: Config) -> dict:
    """Run one query through budget enforcement + Claude, recording the exchange.

    Returns a dict: {reply, warning, capped, model, latency_ms, cost}.
    Budget rules (checked BEFORE the API call):
      • spend ≥ 100% of daily budget → hard stop, no API call, cap message.
      • spend ≥ 80% → one-time-per-day warning returned in `warning`.
    There is deliberately no voice override of the hard stop.
    """
    spend_today = costs.get_spend("today")

    if cfg.daily_budget_usd > 0 and spend_today >= cfg.daily_budget_usd:
        logger.warning("🛑 Daily budget cap reached ($%.2f) — skipping API call.", spend_today)
        events.record_conversation(text, CAP_MESSAGE, "(capped)", 0, 0.0)
        return {"reply": CAP_MESSAGE, "warning": None, "capped": True,
                "model": "(capped)", "latency_ms": 0, "cost": 0.0}

    warning = None
    if cfg.daily_budget_usd > 0 and spend_today >= 0.8 * cfg.daily_budget_usd and _should_warn_80():
        warning = WARN_80_MESSAGE
        logger.warning("⚠️  80%% of daily budget used ($%.2f).", spend_today)

    t0 = time.time()
    reply, model, cost = _call_claude(text, cfg)
    latency_ms = int((time.time() - t0) * 1000)
    events.record_conversation(text, reply, model, latency_ms, cost)
    logger.info("💰 Call cost $%.4f (%dms) — %s", cost, latency_ms, model)
    return {"reply": reply, "warning": warning, "capped": False,
            "model": model, "latency_ms": latency_ms, "cost": cost}


# ---------------------------------------------------------------------------
# Main pipeline loop
# ---------------------------------------------------------------------------

def run_pipeline(
    cfg: Config,
    state_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
    is_muted: Callable[[], bool] | None = None,
    budget_callback: Callable[[str], None] | None = None,
) -> None:
    """The main voice pipeline loop. Run this on a background daemon thread.

    Args:
        cfg:             Initial Config (reloaded fresh each cycle for hot-reload).
        state_callback:  Optional callable(state_name) to update the UI orb.
        stop_event:      If set, the loop exits.
        is_muted:        Optional callable → True when muted (cycle is skipped).
        budget_callback: Optional callable(level) where level is
                         'normal' | 'warn' | 'capped' (drives the orb colour).
    """
    def set_state(name: str) -> None:
        events.set_pipeline_state(name)
        if state_callback:
            state_callback(name)

    last_budget_level = ""

    def push_budget_level(active_cfg: Config) -> None:
        nonlocal last_budget_level
        level = budget_level(active_cfg)
        if level != last_budget_level:
            last_budget_level = level
            if budget_callback:
                budget_callback(level)

    capture_queue: "queue.Queue[bytes]" = queue.Queue()
    capturing = threading.Event()
    paused = threading.Event()
    wake_event = threading.Event()
    audio_stop = threading.Event()

    current_wake_word = cfg.wake_word
    _ensure_wake_model(current_wake_word)
    audio_thread = _start_audio_thread(
        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word
    )

    try:
        while not (stop_event and stop_event.is_set()):
            try:
                cfg = Config.load()  # hot-reload config each cycle

                # Live wake-word change → rebuild the audio thread.
                if cfg.wake_word != current_wake_word:
                    logger.info("🔁 Wake word changed to %r — rebuilding listener.", cfg.wake_word)
                    audio_stop.set()
                    _ensure_wake_model(cfg.wake_word)
                    current_wake_word = cfg.wake_word
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word
                    )

                # Resurrect the audio thread if it died.
                if audio_thread is not None and not audio_thread.is_alive():
                    logger.error("⚠️  Audio thread is dead — restarting it.")
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word
                    )

                if is_muted is not None:
                    events.set_muted(is_muted())
                push_budget_level(cfg)

                set_state("IDLE")

                # Voice disabled via settings → keep loop alive (dashboard text
                # still works) but don't listen.
                if not cfg.wake_word_enabled:
                    paused.set()
                    time.sleep(0.5)
                    continue

                paused.clear()
                capturing.clear()
                logger.info("💤 Waiting for wake word…")

                if not wake_event.wait(timeout=1.0):
                    continue
                wake_event.clear()

                if is_muted is not None and is_muted():
                    logger.info("🔇 Muted — ignoring wake word.")
                    continue

                set_state("LISTENING")
                _drain_queue(capture_queue)
                capturing.set()
                audio_bytes = _record_from_queue(capture_queue)

                paused.set()
                capturing.clear()
                _drain_queue(capture_queue)

                if len(audio_bytes) < FRAME_SIZE * SAMPLE_WIDTH * 3:
                    logger.info("⚠️  No speech captured — ignoring.")
                    continue

                set_state("THINKING")
                try:
                    text = _transcribe(audio_bytes, cfg)
                except Exception as exc:  # noqa: BLE001
                    logger.error("⚠️  Transcription failed: %s", exc, exc_info=True)
                    continue

                if not text:
                    logger.info("🤔 Nothing intelligible heard — back to listening.")
                    continue

                try:
                    result = process_query(text, cfg)
                except Exception as exc:  # noqa: BLE001
                    logger.error("⚠️  Query failed: %s", exc, exc_info=True)
                    result = {"reply": "Sorry, I couldn't reach my brain. Please check your API key.",
                              "warning": None, "capped": False}

                push_budget_level(cfg)

                spoken = result["reply"]
                if result.get("warning"):
                    spoken = result["warning"] + " " + spoken

                logger.info("💬 Reply: %s", result["reply"])
                set_state("SPEAKING")
                speak(spoken, voice_id=cfg.cartesia_voice_id)

            except Exception as exc:  # noqa: BLE001
                logger.error("⚠️  Pipeline cycle failed: %s", exc, exc_info=True)
            finally:
                capturing.clear()
                paused.clear()
                wake_event.clear()
                _drain_queue(capture_queue)

    finally:
        audio_stop.set()
