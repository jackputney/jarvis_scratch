"""
pipeline.py — The Jarvis voice pipeline.

Single clean loop:
  wake word detected → record audio → VAD trim → Whisper STT →
  budget check → route → Claude (with tools) → log cost → TTS → back to listening

ONE microphone stream is shared by the whole app (see _audio_loop): a single
audio thread reads the mic and either feeds wake detection, routes frames into a
capture queue for the recorder, or drains them (echo guard during think/speak).

Stop/interrupt is handled via request_interrupt() (UI Stop button, Escape,
dashboard) which halts TTS and abandons the current cycle. Verbal barge-in was
removed — it fought the mic during think/speak and caused false cut-offs.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from typing import Any

import anthropic
import pyaudio
import webrtcvad

import costs
import conversation
import events
from config import Config
from memory.knowledge import get_recent_notes
from memory.variables import build_variables_block
from tools.registry import CONFIRM_REQUIRED_TOOLS, TOOL_DEFINITIONS, dispatch_tool
from tts.cartesia import speak, stop_speech

logger = logging.getLogger("jarvis.pipeline")

_interrupt = threading.Event()
_query_lock = threading.Lock()
# TODO(Phase 1): Replace thread-pool Claude calls with AsyncAnthropic + streaming so
# Stop cancels the in-flight HTTP request and stops burning tokens after interrupt.
_claude_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-claude")
_QUEUE_POLL_SEC = 0.25
CLAUDE_HTTP_TIMEOUT_SEC = 30.0

AUDIO_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(AUDIO_RATE * FRAME_DURATION_MS / 1000)
CHANNELS = 1
PA_FORMAT = pyaudio.paInt16
SAMPLE_WIDTH = 2
MAX_RECORD_SECONDS = 20
POST_SPEECH_SILENCE_FRAMES = 25  # fallback if config not passed
WAIT_FOR_SPEECH_FRAMES = int(6000 / FRAME_DURATION_MS)
PRE_ROLL_FRAMES = 8
WAKE_THRESHOLD = 0.55
WAKE_CONSECUTIVE_HITS = 2
AUDIO_THREAD_RESTART_DELAY = 2.0

WARN_80_MESSAGE = "Heads up, I'm at 80 percent of today's budget."
CAP_MESSAGE = "I've hit today's budget cap — raise it in the dashboard if you need me."
MONTHLY_CAP_MESSAGE = (
    "I've hit this month's budget cap — raise it in the dashboard if you need me."
)
CONFIRM_PROMPT = (
    "I need your approval — check the dashboard to allow or deny this."
)
BUSY_MESSAGE = "I'm still working on your last request — try again in a moment."


def request_interrupt() -> None:
    """Stop the current utterance and abandon the in-flight pipeline cycle."""
    _interrupt.set()
    stop_speech()
    from tools import confirm as tool_confirm
    tool_confirm.cancel_pending()
    logger.info("⏹️  Stop requested — halting speech and resetting.")


def interrupt_requested() -> bool:
    return _interrupt.is_set()


def _clear_interrupt() -> None:
    _interrupt.clear()


_warn_state: dict[str, Any] = {"date": None}


def _ensure_wake_model(wake_word: str) -> None:
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
        raise RuntimeError(f"❌  Wake model missing after download: {onnx_path}")
    logger.info("✅  Wake word model ready: %s", os.path.basename(onnx_path))


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
                if len(scores) < WAKE_CONSECUTIVE_HITS:
                    continue
                if all(scores[-i] > WAKE_THRESHOLD for i in range(1, WAKE_CONSECUTIVE_HITS + 1)):
                    logger.info("🎙️  Wake word '%s' detected (score=%.2f)", name, scores[-1])
                    _reset_oww(oww_model)
                    # Capture from this frame forward — do NOT replay pre-roll
                    # (that included the wake phrase and made VAD end too early).
                    capture_queue.put(data)
                    capturing.set()
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
    def _run() -> None:
        try:
            import openwakeword.model  # noqa: F401
        except ImportError:
            logger.warning("⚠️  openwakeword not installed — wake word disabled.")
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


def _record_from_queue(
    capture_queue: "queue.Queue[bytes]",
    *,
    silence_ms: int = 1400,
    min_capture_ms: int = 2500,
) -> bytes:
    vad = webrtcvad.Vad(2)
    frames: list[bytes] = []
    silent_frames = 0
    speech_started = False
    max_frames = int(MAX_RECORD_SECONDS * 1000 / FRAME_DURATION_MS)
    post_speech_silence_frames = max(10, int(silence_ms / FRAME_DURATION_MS))
    min_capture_frames = max(15, int(min_capture_ms / FRAME_DURATION_MS))

    logger.info("🎙️  Listening…")
    for i in range(max_frames):
        if _interrupt.is_set():
            logger.info("⏹️  Stop during listening.")
            return b""

        try:
            data = capture_queue.get(timeout=_QUEUE_POLL_SEC)
        except queue.Empty:
            if speech_started:
                continue
            if i >= WAIT_FOR_SPEECH_FRAMES:
                logger.debug("🎙️  Capture timed out waiting for speech.")
                break
            continue

        is_speech = vad.is_speech(data, AUDIO_RATE)
        if is_speech:
            speech_started = True
            silent_frames = 0
            frames.append(data)
        elif speech_started:
            silent_frames += 1
            frames.append(data)
            if i >= min_capture_frames and silent_frames > post_speech_silence_frames:
                logger.debug(
                    "🎙️  Ending capture after %.1fs (%.0fms trailing silence).",
                    (i + 1) * FRAME_DURATION_MS / 1000,
                    silent_frames * FRAME_DURATION_MS,
                )
                break
        else:
            frames.append(data)
            if len(frames) > PRE_ROLL_FRAMES:
                frames.pop(0)

    if not speech_started:
        return b""
    return b"".join(frames)


def strip_wake_phrase(text: str, wake_word: str) -> str:
    """Remove a leading wake phrase from a Whisper transcript.

    openWakeWord fires before the user's question, so Whisper often includes
    the trigger ("hey Jarvis, …") in the transcript. Strip it so Claude sees
    only the intent and logs stay readable.
    """
    if not text or not wake_word:
        return text.strip()

    parts = wake_word.replace("_", " ").split()
    if not parts:
        return text.strip()

    between = r"[\s,.\-!?':;\u2014\u2013]+"
    core = between.join(re.escape(part) for part in parts)
    pattern = rf"^\s*{core}[\s,.\-!?':;\u2014\u2013]*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned


def _transcribe(audio_bytes: bytes, cfg: Config) -> str:
    import mlx_whisper  # type: ignore[import]
    import numpy as np

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    repo = f"mlx-community/whisper-{cfg.whisper_model}-mlx"
    result = mlx_whisper.transcribe(audio_np, path_or_hf_repo=repo)
    raw: str = result.get("text", "").strip()
    text = strip_wake_phrase(raw, cfg.wake_word)
    if raw != text:
        logger.debug("📝 Raw transcript (pre-strip): %r", raw)
    logger.info("📝 Heard: %r", text)
    return text


def _build_system_prompt(cfg: Config) -> str:
    variables_block = build_variables_block()
    notes_block = get_recent_notes(cfg.memory_inject_last_n_notes)
    return (
        "You are Jarvis, a fast personal AI assistant. You are direct, honest, and never "
        "flatter. You flag uncertainty rather than guessing. You have access to tools — use "
        "them when the task requires it, not otherwise. Keep spoken responses concise (under "
        "40 words for simple questions). Recent message history may appear before the latest "
        "user turn — use it for follow-ups. You know the following about the user:\n"
        f"{variables_block}\n\nRecent notes:\n{notes_block}"
    )


def _create_claude_message(client: anthropic.Anthropic, **kwargs: Any) -> Any:
    """Run a Claude HTTP call off the pipeline thread (interruptible wait)."""
    return client.messages.create(**kwargs)


def _emit_pipeline_state(
    name: str,
    on_state: Callable[[str], None] | None,
) -> None:
    events.set_pipeline_state(name)
    if on_state:
        on_state(name)


def _call_claude(
    text: str,
    cfg: Config,
    history: list[dict[str, Any]] | None = None,
    on_state: Callable[[str], None] | None = None,
) -> tuple[str, str, float]:
    client = anthropic.Anthropic(
        api_key=cfg.anthropic_api_key,
        timeout=CLAUDE_HTTP_TIMEOUT_SEC,
    )
    model = cfg.claude_model_fast if cfg.route_to_fast_model(text) else cfg.claude_model_smart
    logger.info("🧠 Routing to %s", model)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": text})
    system_prompt = _build_system_prompt(cfg)
    total_cost = 0.0

    for _round_idx in range(5):
        if _interrupt.is_set():
            logger.info("⏹️  Claude loop aborted (interrupt).")
            return "", model, total_cost

        future: Future[Any] = _claude_executor.submit(
            _create_claude_message,
            client,
            model=model,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        while not future.done():
            if _interrupt.is_set():
                logger.info("⏹️  Stop during Claude — abandoning in-flight request.")
                return "", model, total_cost
            time.sleep(0.25)

        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Claude API error: %s", exc, exc_info=True)
            if _interrupt.is_set():
                return "", model, total_cost
            return "Sorry, I couldn't reach my brain. Please try again.", model, total_cost

        if _interrupt.is_set():
            logger.info("⏹️  Claude loop aborted after response (interrupt).")
            return "", model, total_cost

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
            if _interrupt.is_set():
                logger.info("⏹️  Tool dispatch skipped (interrupt).")
                return reply_text.strip() or "Stopped.", model, total_cost
            logger.info("🔧 Tool: %s(%s)", tu["name"], tu["input"])
            needs_confirm = (
                cfg.confirm_before_execute and tu["name"] in CONFIRM_REQUIRED_TOOLS
            )
            if needs_confirm:
                _emit_pipeline_state("WAITING_CONFIRM", on_state)
                if not _interrupt.is_set():
                    logger.info("🔔 Awaiting dashboard approval for %s", tu["name"])
                    speak(CONFIRM_PROMPT, voice_id=cfg.cartesia_voice_id)
            if _interrupt.is_set():
                logger.info("⏹️  Tool confirm skipped (interrupt).")
                return reply_text.strip() or "Stopped.", model, total_cost
            result = dispatch_tool(
                tu["name"],
                tu["input"],
                confirm=cfg.confirm_before_execute,
                confirm_timeout_sec=cfg.confirm_timeout_sec,
                cancel_check=interrupt_requested,
            )
            if needs_confirm and not _interrupt.is_set():
                _emit_pipeline_state("THINKING", on_state)
            logger.info("   → %s", result[:120])
            if _interrupt.is_set():
                logger.info("⏹️  Cycle aborted during tool confirm.")
                return reply_text.strip() or "Stopped.", model, total_cost
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

    return "I ran into an issue completing that. Please try again.", model, total_cost


def _should_warn_80() -> bool:
    today = date.today().isoformat()
    if _warn_state["date"] == today:
        return False
    _warn_state["date"] = today
    return True


def budget_level(cfg: Config) -> str:
    spend_today = costs.get_spend("today")
    spend_month = costs.get_spend("month")
    if cfg.daily_budget_usd > 0 and spend_today >= cfg.daily_budget_usd:
        return "capped"
    if cfg.monthly_budget_usd > 0 and spend_month >= cfg.monthly_budget_usd:
        return "capped"
    if cfg.daily_budget_usd > 0 and spend_today >= 0.8 * cfg.daily_budget_usd:
        return "warn"
    if cfg.monthly_budget_usd > 0 and spend_month >= 0.8 * cfg.monthly_budget_usd:
        return "warn"
    return "normal"


def _should_store_in_history(reply: str) -> bool:
    """Skip interrupted or placeholder replies so follow-ups stay clean."""
    if _interrupt.is_set():
        return False
    cleaned = (reply or "").strip()
    if not cleaned:
        return False
    if cleaned in {"Stopped.", "Stopped"}:
        return False
    return True


def process_query(
    text: str,
    cfg: Config,
    on_state: Callable[[str], None] | None = None,
) -> dict:
    if not _query_lock.acquire(blocking=False):
        logger.warning("⏳ Query rejected — another request is in flight.")
        return {
            "reply": BUSY_MESSAGE,
            "warning": None,
            "capped": False,
            "busy": True,
            "model": "(busy)",
            "latency_ms": 0,
            "cost": 0.0,
        }

    try:
        spend_today = costs.get_spend("today")
        spend_month = costs.get_spend("month")
        if cfg.daily_budget_usd > 0 and spend_today >= cfg.daily_budget_usd:
            logger.warning("🛑 Daily budget cap reached ($%.2f) — skipping API call.", spend_today)
            events.record_conversation(text, CAP_MESSAGE, "(capped)", 0, 0.0)
            return {"reply": CAP_MESSAGE, "warning": None, "capped": True,
                    "model": "(capped)", "latency_ms": 0, "cost": 0.0, "busy": False}

        if cfg.monthly_budget_usd > 0 and spend_month >= cfg.monthly_budget_usd:
            logger.warning("🛑 Monthly budget cap reached ($%.2f) — skipping API call.", spend_month)
            events.record_conversation(text, MONTHLY_CAP_MESSAGE, "(capped)", 0, 0.0)
            return {"reply": MONTHLY_CAP_MESSAGE, "warning": None, "capped": True,
                    "model": "(capped)", "latency_ms": 0, "cost": 0.0, "busy": False}

        warning = None
        if cfg.daily_budget_usd > 0 and spend_today >= 0.8 * cfg.daily_budget_usd and _should_warn_80():
            warning = WARN_80_MESSAGE
            logger.warning("⚠️  80%% of daily budget used ($%.2f).", spend_today)

        t0 = time.time()
        history = conversation.build_messages(
            cfg.conversation_history_turns,
            cfg.conversation_history_max_chars,
        )
        reply, model, cost = _call_claude(text, cfg, history=history, on_state=on_state)
        latency_ms = int((time.time() - t0) * 1000)
        if _should_store_in_history(reply):
            conversation.add_turn(text, reply)
        events.record_conversation(text, reply or "(interrupted)", model, latency_ms, cost)
        logger.info("💰 Call cost $%.4f (%dms) — %s", cost, latency_ms, model)
        return {"reply": reply, "warning": warning, "capped": False, "busy": False,
                "model": model, "latency_ms": latency_ms, "cost": cost}
    finally:
        _query_lock.release()


def run_pipeline(
    cfg: Config,
    state_callback: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
    is_muted: Callable[[], bool] | None = None,
    budget_callback: Callable[[str], None] | None = None,
) -> None:
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
        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
    )

    try:
        while not (stop_event and stop_event.is_set()):
            try:
                cfg = Config.load()

                if cfg.wake_word != current_wake_word:
                    logger.info("🔁 Wake word changed to %r — rebuilding listener.", cfg.wake_word)
                    audio_stop.set()
                    if audio_thread is not None:
                        audio_thread.join(timeout=5.0)
                    _ensure_wake_model(cfg.wake_word)
                    current_wake_word = cfg.wake_word
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
                    )

                if audio_thread is not None and not audio_thread.is_alive():
                    logger.error("⚠️  Audio thread is dead — restarting it.")
                    audio_stop.set()
                    audio_thread.join(timeout=5.0)
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
                    )

                if is_muted is not None:
                    events.set_muted(is_muted())
                push_budget_level(cfg)
                set_state("IDLE")

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
                    capturing.clear()
                    _drain_queue(capture_queue)
                    continue

                set_state("LISTENING")
                if not capturing.is_set():
                    capturing.set()
                audio_bytes = _record_from_queue(
                    capture_queue,
                    silence_ms=cfg.vad_silence_ms,
                    min_capture_ms=cfg.vad_min_capture_ms,
                )

                paused.set()
                capturing.clear()
                _drain_queue(capture_queue)

                if _interrupt.is_set():
                    logger.info("⏹️  Cycle aborted after listening.")
                    set_state("IDLE")
                    continue

                if len(audio_bytes) < FRAME_SIZE * SAMPLE_WIDTH * 3:
                    logger.info("⚠️  No speech captured — ignoring.")
                    continue

                set_state("THINKING")
                try:
                    text = _transcribe(audio_bytes, cfg)
                except Exception as exc:  # noqa: BLE001
                    logger.error("⚠️  Transcription failed: %s", exc, exc_info=True)
                    continue

                if _interrupt.is_set():
                    set_state("IDLE")
                    continue

                if not text:
                    logger.info("🤔 Nothing intelligible heard — back to listening.")
                    continue

                try:
                    result = process_query(text, cfg, on_state=set_state)
                except Exception as exc:  # noqa: BLE001
                    logger.error("⚠️  Query failed: %s", exc, exc_info=True)
                    result = {"reply": "Sorry, I couldn't reach my brain. Please check your API key.",
                              "warning": None, "capped": False}

                if _interrupt.is_set():
                    logger.info("⏹️  Cycle aborted — skipping speech.")
                    set_state("IDLE")
                    continue

                push_budget_level(cfg)
                spoken = result["reply"]
                if result.get("warning"):
                    spoken = result["warning"] + " " + spoken

                logger.info("💬 Reply: %s", result["reply"])
                set_state("SPEAKING")
                speak(spoken, voice_id=cfg.cartesia_voice_id)

                if _interrupt.is_set():
                    logger.info("⏹️  Speech interrupted.")
                    set_state("IDLE")

            except Exception as exc:  # noqa: BLE001
                logger.error("⚠️  Pipeline cycle failed: %s", exc, exc_info=True)
            finally:
                capturing.clear()
                paused.clear()
                wake_event.clear()
                _drain_queue(capture_queue)
                _clear_interrupt()

    finally:
        audio_stop.set()
