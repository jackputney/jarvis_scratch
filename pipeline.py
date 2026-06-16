"""
pipeline.py — The Jarvis voice pipeline.

Single clean loop:
  wake word detected → record audio → VAD trim → Whisper STT →
  budget check → route → Claude (with tools) → log cost → TTS → back to listening

ONE microphone stream is shared by the whole app (see _audio_loop): a single
audio thread reads the mic and either feeds wake detection, routes frames into a
capture queue for the recorder, or drains them (echo guard during think/speak).

Stop/interrupt is handled via request_interrupt() (UI Stop button, Escape,
dashboard) which halts TTS and abandons the current cycle.

Verbal barge-in (say the wake word over a reply to cut it off and ask again) is
handled in _wait_for_job_with_bargein(): wake detection is armed only once the
reply is actually playing (state SPEAKING), never during think/speak setup, so
the wake utterance that started the turn can't re-fire and cause a false
cut-off. Gated by cfg.barge_in_enabled.
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

try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore[assignment]  # optional — sounddevice is the preferred backend

try:
    import webrtcvad
except ImportError:
    webrtcvad = None  # type: ignore[assignment,misc]

import costs
import conversation
import events
from config import Config
from memory.knowledge import get_recent_notes
from memory.learn import record_exchange
from memory.semantic import build_recall_context
from memory.variables import build_variables_block
from tools.registry import CONFIRM_REQUIRED_TOOLS, TOOL_DEFINITIONS, dispatch_tool
from tts.cartesia import speak, speak_stream, stop_speech

logger = logging.getLogger("jarvis.pipeline")

_interrupt = threading.Event()
_query_lock = threading.Lock()
_fw_model = None
_fw_model_name: str | None = None
_hotwords_cache: dict[str, Any] = {"ts": 0.0, "value": ""}
# Claude calls run on this pool and stream their response; on Stop the streaming
# helper returns early and closes the socket, which halts generation (and billing)
# rather than letting the request finish in the background. See _create_claude_message.
_claude_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-claude")
_QUEUE_POLL_SEC = 0.25
CLAUDE_HTTP_TIMEOUT_SEC = 30.0
# Upper bound a voice turn can occupy the orchestrator (query + tool confirm wait
# + TTS). Generous: the confirm gate alone can hold for confirm_timeout_sec.
VOICE_JOB_TIMEOUT_SEC = 180.0

AUDIO_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(AUDIO_RATE * FRAME_DURATION_MS / 1000)
CHANNELS = 1
PA_FORMAT = pyaudio.paInt16 if pyaudio is not None else None
SAMPLE_WIDTH = 2
MAX_RECORD_SECONDS = 20
POST_SPEECH_SILENCE_FRAMES = 25  # fallback if config not passed
WAIT_FOR_SPEECH_FRAMES = int(6000 / FRAME_DURATION_MS)
FOLLOWUP_WAIT_FRAMES = int(6000 / FRAME_DURATION_MS)
ANSWER_WAIT_FRAMES = int(12000 / FRAME_DURATION_MS)
PRE_ROLL_FRAMES = 8
WAKE_THRESHOLD = 0.55
WAKE_CONSECUTIVE_HITS = 2
AUDIO_THREAD_RESTART_DELAY = 2.0
ENERGY_VAD_THRESHOLD = 250
HOTWORDS_TTL_SECONDS = 600

STATIC_SYSTEM_INSTRUCTIONS = (
    "You are Jarvis, a fast personal AI assistant. You are direct, honest, and never "
    "flatter. You flag uncertainty rather than guessing. You have access to tools — use "
    "them when the task requires it, not otherwise. Keep spoken responses concise (under "
    "40 words for simple questions). Recent message history may appear before the latest "
    "user turn — use it for follow-ups. When the user shares durable personal facts "
    "(preferences, relationships, routines, goals), persist them with remember, "
    "set_variable, or write_note so future turns stay personalised.\n\n"
    "## When to escalate\n"
    "You start on the fast model. If a request needs careful multi-step reasoning, "
    "planning, analysis, coding, or nuanced writing, call the escalate tool FIRST and "
    "stop — the smart model takes over with full context. Handle simple lookups, "
    "chit-chat, and single tool actions yourself without escalating.\n\n"
    "## Time and date\n"
    "For time or date questions, always call get_current_time — never guess or use "
    "training data for the current time."
)

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


# Map user-facing wake_word config values to openwakeword pretrained model ids.
WAKE_WORD_MODELS: dict[str, str] = {
    "hey jarvis": "hey_jarvis",
    "alexa": "alexa",
}


def resolve_wake_model(wake_word: str) -> str:
    """Resolve config wake_word to an openwakeword model id."""
    key = (wake_word or "hey_jarvis").lower().replace("_", " ").strip()
    if key in WAKE_WORD_MODELS:
        return WAKE_WORD_MODELS[key]
    try:
        from openwakeword import MODELS

        if wake_word in MODELS:
            return wake_word
    except ImportError:
        pass
    return WAKE_WORD_MODELS.get("hey jarvis", "hey_jarvis")


def prepare_wake_word_model(wake_word: str) -> None:
    """Ensure the wake word ONNX model is present (may download on first run)."""
    _ensure_wake_model(resolve_wake_model(wake_word))


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


def _is_speech_energy(data: bytes) -> bool:
    """Lightweight energy-based speech detector — fallback when webrtcvad is absent."""
    import numpy as np

    audio = np.frombuffer(data, dtype=np.int16)
    if audio.size == 0:
        return False
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    return rms > ENERGY_VAD_THRESHOLD


def _read_audio_frame(stream: Any, *, use_sounddevice: bool) -> bytes:
    if use_sounddevice:
        data, _overflowed = stream.read(FRAME_SIZE)
        import numpy as np

        return np.asarray(data, dtype=np.int16).reshape(-1).tobytes()
    return stream.read(FRAME_SIZE, exception_on_overflow=False)


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
    use_sounddevice = False
    sd_stream = None
    pa = None
    pa_stream = None

    try:
        import sounddevice as sd

        sd_stream = sd.InputStream(
            samplerate=AUDIO_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=FRAME_SIZE,
        )
        sd_stream.start()
        use_sounddevice = True
        logger.info("🎤 Audio input: sounddevice")
    except Exception as exc:  # noqa: BLE001
        if pyaudio is None:
            raise RuntimeError(
                "No audio backend available: sounddevice failed to open and PyAudio "
                "isn't installed."
            ) from exc
        logger.info("🎤 Audio input: PyAudio (sounddevice unavailable: %s)", exc)
        pa = pyaudio.PyAudio()
        pa_stream = pa.open(
            rate=AUDIO_RATE,
            channels=CHANNELS,
            format=PA_FORMAT,
            input=True,
            frames_per_buffer=FRAME_SIZE,
        )

    stream = sd_stream if use_sounddevice else pa_stream
    logger.info("👂 Wake word listener active — say '%s' to activate", wake_word)

    was_inactive = False
    try:
        while not audio_stop.is_set():
            data = _read_audio_frame(stream, use_sounddevice=use_sounddevice)

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
                    capture_queue.put(data)
                    capturing.set()
                    wake_event.set()
                    break
    finally:
        if use_sounddevice and sd_stream is not None:
            sd_stream.stop()
            sd_stream.close()
        elif pa_stream is not None:
            pa_stream.stop_stream()
            pa_stream.close()
        if pa is not None:
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
    wait_for_speech_frames: int = WAIT_FOR_SPEECH_FRAMES,
    *,
    silence_ms: int = 1400,
    min_capture_ms: int = 2500,
) -> bytes:
    vad = webrtcvad.Vad(2) if webrtcvad else None
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
            if i >= wait_for_speech_frames:
                logger.debug("🎙️  Capture timed out waiting for speech.")
                break
            continue

        is_speech = vad.is_speech(data, AUDIO_RATE) if vad else _is_speech_energy(data)
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


def _stt_hotwords() -> str:
    """Contact names for faster-whisper hotword biasing (cached 10 min)."""
    now = time.time()
    if now - _hotwords_cache["ts"] < HOTWORDS_TTL_SECONDS:
        return _hotwords_cache["value"]

    _hotwords_cache["ts"] = now
    try:
        from tools.google_contacts import get_contact_names

        names = get_contact_names()
    except Exception:  # noqa: BLE001
        names = []
    _hotwords_cache["value"] = ", ".join(names)
    if names:
        logger.info("🎯 STT biased toward %d contact names", len(names))
    return _hotwords_cache["value"]


def warm_stt_caches() -> None:
    """Pre-fetch contact hotwords so the first transcription skips Google latency."""
    threading.Thread(target=_stt_hotwords, daemon=True, name="jarvis-hotwords").start()


def _transcribe(audio_bytes: bytes, cfg: Config) -> str:
    import numpy as np

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    model_name = cfg.effective_stt_model()

    if cfg.stt_backend == "faster":
        global _fw_model, _fw_model_name
        from faster_whisper import WhisperModel

        if _fw_model is None or _fw_model_name != model_name:
            _fw_model = WhisperModel(model_name, compute_type="int8")
            _fw_model_name = model_name
        hotwords = _stt_hotwords() or None
        segments, _info = _fw_model.transcribe(
            audio_np,
            beam_size=5,
            language="en",
            vad_filter=True,
            hotwords=hotwords,
        )
        raw = " ".join(s.text for s in segments).strip()
    else:
        import mlx_whisper  # type: ignore[import]

        repo = f"mlx-community/whisper-{model_name}-mlx"
        result = mlx_whisper.transcribe(audio_np, path_or_hf_repo=repo)
        raw = result.get("text", "").strip()

    text = strip_wake_phrase(raw, cfg.wake_word)
    if raw != text:
        logger.debug("📝 Raw transcript (pre-strip): %r", raw)
    logger.info("📝 Heard: %r", text)
    return text


def _capture_and_transcribe(
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    cfg: Config,
    set_state: Callable[[str], None],
    *,
    wait_for_speech_frames: int = WAIT_FOR_SPEECH_FRAMES,
) -> str | None:
    """Record one utterance and transcribe it. Returns None if nothing was heard."""
    set_state("LISTENING")
    _drain_queue(capture_queue)
    capturing.set()
    audio_bytes = _record_from_queue(
        capture_queue,
        wait_for_speech_frames,
        silence_ms=cfg.vad_silence_ms,
        min_capture_ms=cfg.vad_min_capture_ms,
    )

    paused.set()
    capturing.clear()
    _drain_queue(capture_queue)

    if _interrupt.is_set():
        logger.info("⏹️  Stop during listening.")
        return None

    if len(audio_bytes) < FRAME_SIZE * SAMPLE_WIDTH * 3:
        logger.info("⚠️  No speech captured.")
        return None

    set_state("THINKING")
    try:
        text = _transcribe(audio_bytes, cfg)
    except Exception as exc:  # noqa: BLE001
        logger.error("⚠️  Transcription failed: %s", exc, exc_info=True)
        return None

    if not text:
        logger.info("🤔 Nothing intelligible heard.")
        return None
    return text


def warmup_stt(cfg: Config) -> None:
    """Pre-load STT model and contact hotwords."""
    warm_stt_caches()
    if cfg.stt_backend == "faster":
        global _fw_model, _fw_model_name
        from faster_whisper import WhisperModel

        name = cfg.effective_stt_model()
        if _fw_model is None or _fw_model_name != name:
            logger.info("🎧 Warming faster-whisper model %r…", name)
            _fw_model = WhisperModel(name, compute_type="int8")
            _fw_model_name = name
    else:
        logger.info("🎧 STT backend mlx — model loads on first transcription.")


def _build_system_blocks(cfg: Config, query_text: str = "") -> list[dict[str, Any]]:
    """System prompt split into a cacheable static block and dynamic user context."""
    variables_block = build_variables_block()
    if cfg.memory_semantic_recall and query_text.strip():
        notes_block = build_recall_context(query_text, cfg)
    else:
        notes_block = get_recent_notes(cfg.memory_inject_last_n_notes)
    return [
        {
            "type": "text",
            "cache_control": {"type": "ephemeral"},
            "text": STATIC_SYSTEM_INSTRUCTIONS,
        },
        {
            "type": "text",
            "text": f"You know the following about the user:\n{variables_block}\n\n"
            f"Relevant memories:\n{notes_block}",
        },
    ]


def _build_system_prompt(cfg: Config, query_text: str = "") -> str:
    """Flat system prompt for callers that do not use block caching."""
    blocks = _build_system_blocks(cfg, query_text)
    return blocks[0]["text"] + "\n\n" + blocks[1]["text"]


class _SentenceEmitter:
    """Split streamed text deltas into speakable sentence chunks."""

    _BOUNDARY = re.compile(r"[.!?…\n]")
    _SOFT_CAP = 180

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._buf = ""

    def feed(self, delta: str) -> None:
        self._buf += delta
        while True:
            match = self._BOUNDARY.search(self._buf)
            if match:
                end = match.end()
                chunk = self._buf[:end].strip()
                self._buf = self._buf[end:].lstrip()
                if chunk:
                    self._emit(chunk)
                continue
            if len(self._buf) >= self._SOFT_CAP:
                cut = self._buf.rfind(" ", 0, self._SOFT_CAP)
                if cut <= 0:
                    break
                chunk = self._buf[:cut].strip()
                self._buf = self._buf[cut:].lstrip()
                if chunk:
                    self._emit(chunk)
                continue
            break

    def flush(self) -> None:
        chunk = self._buf.strip()
        self._buf = ""
        if chunk:
            self._emit(chunk)


def _create_claude_message(
    client: anthropic.Anthropic,
    *,
    on_sentence: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Stream a Claude message; optional sentence-boundary callback while generating."""
    try:
        stream_cm = client.messages.stream(**kwargs)
    except (AttributeError, TypeError):
        return client.messages.create(**kwargs)

    emitter = _SentenceEmitter(on_sentence) if on_sentence else None

    with stream_cm as stream:
        for delta in stream.text_stream:
            if _interrupt.is_set():
                return None
            if emitter is not None:
                emitter.feed(delta)
        if _interrupt.is_set():
            return None
        final = stream.get_final_message()

    if emitter is not None:
        emitter.flush()
    return final


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
    on_sentence: Callable[[str], None] | None = None,
) -> tuple[str, str, float, bool]:
    from llm import get_llm_client

    client = get_llm_client(cfg, timeout=CLAUDE_HTTP_TIMEOUT_SEC)
    model = cfg.claude_model_fast
    logger.info("🧠 Starting on %s (escalate tool → %s)", model, cfg.claude_model_smart)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": text})
    system_blocks = _build_system_blocks(cfg, query_text=text)
    total_cost = 0.0
    stream_spoken = False

    def _emit_sentence(sentence: str) -> None:
        nonlocal stream_spoken
        if _interrupt.is_set() or not on_sentence:
            return
        stream_spoken = True
        on_sentence(sentence)

    sentence_cb = _emit_sentence if on_sentence else None

    for _round_idx in range(5):
        if _interrupt.is_set():
            logger.info("⏹️  Claude loop aborted (interrupt).")
            return "", model, total_cost, stream_spoken

        future: Future[Any] = _claude_executor.submit(
            _create_claude_message,
            client,
            on_sentence=sentence_cb,
            model=model,
            max_tokens=1024,
            system=system_blocks,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        while not future.done():
            if _interrupt.is_set():
                logger.info("⏹️  Stop during Claude — abandoning in-flight request.")
                return "", model, total_cost, stream_spoken
            time.sleep(0.25)

        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001
            logger.error("⚠️  Claude API error: %s", exc, exc_info=True)
            if _interrupt.is_set():
                return "", model, total_cost, stream_spoken
            return "Sorry, I couldn't reach my brain. Please try again.", model, total_cost, stream_spoken

        if response is None:
            logger.info("⏹️  Claude stream cancelled — no tokens charged past cut-off.")
            return "", model, total_cost, stream_spoken

        if _interrupt.is_set():
            logger.info("⏹️  Claude loop aborted after response (interrupt).")
            return "", model, total_cost, stream_spoken

        total_cost += costs.log_usage(model, getattr(response, "usage", None), text)

        reply_text = ""
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                reply_text += block.text
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

        if model == cfg.claude_model_fast and any(tu["name"] == "escalate" for tu in tool_uses):
            logger.info("⬆️  Escalating to %s for this turn.", cfg.claude_model_smart)
            model = cfg.claude_model_smart

        if not tool_uses:
            return reply_text.strip(), model, total_cost, stream_spoken

        messages.append({"role": "assistant", "content": response.content})
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            if _interrupt.is_set():
                logger.info("⏹️  Tool dispatch skipped (interrupt).")
                return reply_text.strip() or "Stopped.", model, total_cost, stream_spoken
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
                return reply_text.strip() or "Stopped.", model, total_cost, stream_spoken
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
                return reply_text.strip() or "Stopped.", model, total_cost, stream_spoken
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

    return "I ran into an issue completing that. Please try again.", model, total_cost, stream_spoken


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
    speak: bool = False,
    on_sentence: Callable[[str], None] | None = None,
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

        if warning and on_sentence and not _interrupt.is_set():
            on_sentence(warning)

        t0 = time.time()
        history = conversation.build_messages(
            cfg.conversation_history_turns,
            cfg.conversation_history_max_chars,
        )
        reply, model, cost, stream_spoken = _call_claude(
            text, cfg, history=history, on_state=on_state, on_sentence=on_sentence,
        )
        latency_ms = int((time.time() - t0) * 1000)
        if _should_store_in_history(reply):
            conversation.add_turn(text, reply)
            record_exchange(text, reply, cfg)
        cleaned_reply = (reply or "").strip()
        if cleaned_reply:
            events.record_conversation(text, cleaned_reply, model, latency_ms, cost)
        logger.info("💰 Call cost $%.4f (%dms) — %s", cost, latency_ms, model)
        return {"reply": reply, "warning": warning, "capped": False, "busy": False,
                "model": model, "latency_ms": latency_ms, "cost": cost,
                "stream_spoken": stream_spoken}
    finally:
        _query_lock.release()


def _wait_for_job_with_bargein(
    orchestrator: Any,
    job_id: str,
    cfg: Config,
    wake_event: threading.Event,
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    timeout: float = VOICE_JOB_TIMEOUT_SEC,
) -> tuple[Any, bool]:
    """Wait for a voice job to finish, allowing a wake-word barge-in.

    Returns ``(job, barged)``. While the reply is still being generated
    (THINKING) wake detection stays paused so the wake utterance that started
    this turn can't re-fire and interrupt the reply "by nothing". Once audio
    starts playing (state SPEAKING) we discard any residual wake hit and re-arm
    detection; if the user says the wake word over the reply we cancel the turn
    — stopping speech through the same interrupt path as the Stop button — and
    return ``barged=True`` so the caller can immediately capture the new request.

    When barge-in or the wake word is disabled this degrades to a plain
    blocking wait.
    """
    bargein = cfg.barge_in_enabled and cfg.wake_word_enabled
    armed = False
    deadline = time.monotonic() + timeout
    while True:
        job = orchestrator.wait(job_id, timeout=0.1)
        if job is None or job.done_event.is_set() or time.monotonic() > deadline:
            return job, False
        if not bargein:
            continue
        state = events.get_state().get("pipeline_state")
        if not armed and state == "SPEAKING":
            armed = True
            wake_event.clear()
            capturing.clear()
            _drain_queue(capture_queue)
            paused.clear()  # enable wake detection during the spoken reply
        if armed and wake_event.is_set():
            logger.info("🎙️  Barge-in — stopping reply to listen.")
            orchestrator.cancel_current()
            return job, True


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

    from orchestrator.runtime import get_orchestrator
    from orchestrator.types import Command, CommandSource

    orchestrator = get_orchestrator()
    orchestrator.set_state_callback(state_callback)

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

    current_wake_word = resolve_wake_model(cfg.wake_word)
    _ensure_wake_model(current_wake_word)
    audio_thread = _start_audio_thread(
        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
    )

    try:
        while not (stop_event and stop_event.is_set()):
            try:
                cfg = Config.load()

                resolved = resolve_wake_model(cfg.wake_word)
                if resolved != current_wake_word:
                    logger.info("🔁 Wake word changed to %r — rebuilding listener.", cfg.wake_word)
                    audio_stop.set()
                    if audio_thread is not None:
                        audio_thread.join(timeout=5.0)
                    _ensure_wake_model(resolved)
                    current_wake_word = resolved
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

                text = _capture_and_transcribe(
                    capture_queue, capturing, paused, cfg, set_state,
                )
                if text is None:
                    continue

                # Process the wake-triggered query, then keep listening for
                # follow-ups without repeating the wake word.
                while text is not None:
                    if _interrupt.is_set():
                        logger.info("⏹️  Cycle aborted.")
                        set_state("IDLE")
                        break

                    sub = orchestrator.submit(
                        Command(text=text, source=CommandSource.VOICE, speak=True)
                    )
                    if not sub.accepted:
                        logger.warning("⏳ Queue full — voice command rejected.")
                        speak(BUSY_MESSAGE, voice_id=cfg.cartesia_voice_id)
                        set_state("IDLE")
                        break

                    job, barged = _wait_for_job_with_bargein(
                        orchestrator, sub.job_id, cfg,
                        wake_event, capture_queue, capturing, paused,
                    )
                    push_budget_level(cfg)
                    if job is not None and job.reply:
                        logger.info("💬 Reply: %s", job.reply)

                    if barged:
                        # The user said the wake word over the reply: speech is
                        # already stopping. Clear the interrupt so this isn't
                        # treated as a full abort, then capture the new request
                        # right away (the audio thread is already listening).
                        _clear_interrupt()
                        wake_event.clear()
                        text = _capture_and_transcribe(
                            capture_queue, capturing, paused, cfg, set_state,
                        )
                        continue

                    if _interrupt.is_set():
                        logger.info("⏹️  Cycle aborted.")
                        set_state("IDLE")
                        break

                    if job is not None and job.capped:
                        break

                    awaiting_answer = bool(job and job.reply and job.reply.rstrip().endswith("?"))
                    wait_frames = ANSWER_WAIT_FRAMES if awaiting_answer else FOLLOWUP_WAIT_FRAMES
                    time.sleep(0.4)
                    paused.clear()
                    logger.info(
                        "👂 %s…",
                        "Waiting for your answer" if awaiting_answer else "Listening for follow-up",
                    )
                    text = _capture_and_transcribe(
                        capture_queue,
                        capturing,
                        paused,
                        cfg,
                        set_state,
                        wait_for_speech_frames=wait_frames,
                    )
                    if text is None and awaiting_answer and not _interrupt.is_set():
                        logger.info("👂 Still listening for your answer…")
                        paused.clear()
                        text = _capture_and_transcribe(
                            capture_queue,
                            capturing,
                            paused,
                            cfg,
                            set_state,
                            wait_for_speech_frames=wait_frames,
                        )
                    if text is None:
                        break

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
