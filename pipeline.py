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

import costs
from adapters.audio_io import (
    FRAME_DURATION_MS,
    FRAME_SIZE,
    SAMPLE_WIDTH,
    barge_energy_threshold as _barge_energy_threshold,
    is_speech_energy as _is_speech_energy,
    record_from_queue as _record_from_queue,
    start_audio_thread as _start_audio_thread,
)
import conversation
import events
from config import Config
from memory.knowledge import get_recent_notes
from memory.learn import record_exchange
from memory.semantic import build_recall_context
from memory.variables import build_variables_block
from tools.registry import CONFIRM_REQUIRED_TOOLS, dispatch_tool, get_tool_definitions, phone_tool_allowed
from tts.cartesia import speak, speak_stream, stop_speech
from voice.speech_state import (
    BARGEIN_GRACE_SEC,
    BargeInGate,
    SpeechPhase,
    WAKE_DETECTION_OFF_STATES,
    transition,
)

logger = logging.getLogger("jarvis.pipeline")

_interrupt = threading.Event()
_claude_future_lock = threading.Lock()
_active_claude_future: Future[Any] | None = None
# Set by the global hotkey handler to trigger an immediate listening turn.
# Checked at the top of each pipeline idle loop iteration so it survives
# across the finally-block clear of wake_event.
_hotkey_pending = threading.Event()
_query_lock = threading.Lock()
_hotwords_cache: dict[str, Any] = {"ts": 0.0, "value": ""}
# Claude calls run on this pool and stream their response; on Stop the streaming
# helper returns early and closes the socket, which halts generation (and billing)
# rather than letting the request finish in the background. See _create_claude_message.
_claude_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-claude")
_QUEUE_POLL_SEC = 0.05
CLAUDE_HTTP_TIMEOUT_SEC = 30.0
# Upper bound a voice turn can occupy the orchestrator (query + tool confirm wait
# + TTS). Generous: the confirm gate alone can hold for confirm_timeout_sec.
VOICE_JOB_TIMEOUT_SEC = 180.0

POST_SPEECH_SILENCE_FRAMES = 25  # fallback if config not passed
WAIT_FOR_SPEECH_FRAMES = int(6000 / FRAME_DURATION_MS)
FOLLOWUP_WAIT_FRAMES = int(5000 / FRAME_DURATION_MS)
ANSWER_WAIT_FRAMES = int(12000 / FRAME_DURATION_MS)
HOTWORDS_TTL_SECONDS = 600

_SYSTEM_PROMPT_TEMPLATE = """\
You are Jarvis — a local AI assistant running on {platform} for {developer_name}. \
You have direct access to their computer, Google account, GitHub, Slack, and memory.

## How you speak
You are spoken aloud via text-to-speech. Keep replies short and conversational — \
1 to 3 sentences unless more detail is explicitly needed. No markdown. No bullet points. \
No headers. No asterisks. Plain sentences only. No filler phrases. Never say "Certainly!", \
"Great question!", "Of course!", "Sure thing!", or "Absolutely!". Just answer. Be direct. \
If you did something, say so. If you can't, say why in one sentence. Numbers and times \
spoken naturally: "three thirty PM" not "15:30". For email, {developer_name} gives the \
recipient and the gist — infer a short subject, draft the body yourself, and call \
send_email immediately. Never read the subject or body aloud. Never ask permission to \
send. Say only a brief confirmation after sending, e.g. "Sent."

## How you act
Call tools immediately. Never ask the user for permission to use a tool that is clearly \
needed. Never guess the time or date — always call get_current_time. Never tell the user \
an app is not installed without calling open_app first. If a task needs the smarter model, \
call escalate first before attempting it yourself. For multi-step tasks, start immediately \
and confirm checkpoints by speaking — do not ask upfront for every detail. When \
{developer_name} shares durable facts (preferences, relationships, routines, goals), \
persist them with remember(), set_variable(), or write_note() so future turns stay \
personalised.

## Who you are working for
Name: {developer_name}. Platform: {platform} ({platform_detail}). Timezone: {timezone}. \
Role: Software developer at Nuvolum. Projects: Jarvis (this system), Quantum PRM mobile, \
Nuvolum paid media dashboard.

## Your capabilities by platform

Always available: web search, weather, time and date, Google Calendar, Gmail, Google \
Contacts, Google Drive, Google Sheets, memory notes and variables, semantic recall, \
GitHub read and write access to jackputney/jarvis_scratch, Slack read and post, file find \
and open, file download, pitch deck generation, self-improvement (Jarvis Thinks).

macOS only: Music control via Music.app, device control (volume, brightness, dark/light \
mode, WiFi, DND, battery, screen saver, lock screen), media finder via Spotlight and \
Photos and Podcasts, launch at login via LaunchAgent.

Windows only: media control keys (play/pause/skip any app), clipboard read/write, system \
info (CPU, RAM, disk, processes), active window detection.

On Windows, call open_app immediately to launch any installed program — never refuse or \
say you cannot open arbitrary Windows applications. On macOS, when the user asks to open \
or launch a desktop app, call open_app without guessing whether it is installed.

## GitHub
You have read and write access to exactly one GitHub repo: jackputney/jarvis_scratch. \
This is Jarvis's own codebase. Call get_own_issues, read_own_file, get_own_commits, \
create_own_branch, create_own_file, create_own_pr etc. immediately — never ask which repo. \
For any other repo, use search_github_issues or get_github_repo_summary with the full \
owner/name.

## Memory
You have persistent memory across sessions. Use remember() for durable facts about \
{developer_name}. Use write_note() for structured notes. Use search_memory() when context \
from past conversations would help. Always check memory before asking the user to repeat \
themselves.

## Self-improvement
You monitor your own performance. When you make mistakes, they are logged and reflected \
upon. Check Jarvis Thinks in the dashboard for suggestions about your own behaviour. If \
asked about your performance metrics, call get_own_issues() and reference the \
self-improvement data.

## How you think
You are running on Claude — one of the most capable AI systems ever built. Do not \
undersell yourself. When faced with a complex problem, think it through fully before \
responding. Use your complete reasoning capacity on every non-trivial request.

When you encounter a hard problem:
- Break it down into components before acting
- Consider multiple approaches and pick the best one
- Anticipate what {developer_name} will need next, not just what they asked for
- If something will take multiple steps, narrate your plan briefly before starting

You are not a simple voice assistant. You are an intelligent agent with memory, tools, \
and the ability to modify your own codebase. Act like it.

## When you hit a wall
If you cannot do something {developer_name} asks for, do not just say "I can't do that." \
Instead:

1. Explain exactly WHY you can't do it — is it a missing tool, missing API key, missing \
permission, or a technical limitation?

2. Suggest how to fix it. Be specific:
   - "I don't have a tool for that yet. You could build one by adding a function to \
tools/ that calls the [X] API — want me to write the code?"
   - "I need a [X] API key in your .env to do this. Get one at [URL] and I can use it \
immediately."
   - "This needs write access to [X]. If you grant it, I can handle this automatically \
going forward."
   - "This would work better as a background task. Once the session architecture is wired \
up, I could run this automatically while you do other things."

3. If the fix requires new code, offer to write it:
   - Use create_own_issue() to log it as a GitHub issue
   - Use create_own_file() to propose the implementation
   - Use create_own_branch() to start the work

You have read and write access to your own codebase. When you identify a gap in your \
capabilities, you can begin closing it immediately — not just report it.

## Your development awareness
You know your own architecture:
- You are built in sprints. Current: Sprint 9.
- Your core is pipeline.py → orchestrator → tools/
- New capabilities are added by creating a file in tools/ and registering it in \
tools/registry.py
- You can read any file in your own codebase with read_own_file()
- You can propose changes via create_own_issue() and create_own_pr()
- Your self-improvement engine is in improvement/ — it monitors your performance and \
generates suggestions

When {developer_name} says "can you do X", before saying no — check if X could be \
implemented as a tool. If yes, say: "I can't do that yet, but I could. Want me to build it?"

## Voice UX rules
If the user interrupts you (barge-in), stop immediately and listen. After finishing a \
reply, listen for a follow-up before returning to wake-word mode. Confirm high-risk \
actions by speaking what you are about to do before the dashboard modal appears. If a tool \
fails, say so briefly and offer one alternative.\
"""

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
    global _active_claude_future
    with _claude_future_lock:
        fut = _active_claude_future
    if fut is not None and not fut.done():
        fut.cancel()
    from tools import confirm as tool_confirm

    tool_confirm.cancel_pending()
    logger.info("⏹️  Stop requested — halting speech and resetting.")


def request_wake() -> None:
    """Signal the pipeline to start (or restart) a listening turn immediately.

    Safe to call from any thread (hotkey, dashboard, tests).  If Jarvis is
    mid-reply it will be interrupted first; the next idle loop iteration then
    starts recording without waiting for the wake word.
    """
    state_name = events.get_state().get("pipeline_state", "IDLE")
    if state_name in ("THINKING", "SPEAKING", "WAITING_CONFIRM"):
        request_interrupt()
    _hotkey_pending.set()
    logger.info("⌨️  Wake requested externally (state: %s).", state_name)


def interrupt_requested() -> bool:
    return _interrupt.is_set()


def _clear_interrupt() -> None:
    _interrupt.clear()
    # Barge-in / Stop sets _cancel via stop_speech(); must reset before the next turn
    # or speak_stream exits immediately while stream_spoken blocks the fallback path.
    from tts.cartesia import _cancel

    _cancel.clear()


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


def wake_model_from_config(cfg: Config) -> str:
    """OpenWakeWord model id from config (wakeword_model preferred, else wake_word)."""
    model = (getattr(cfg, "wakeword_model", None) or cfg.wake_word or "hey_jarvis").strip()
    return resolve_wake_model(model)


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


def _followup_wait_frames(cfg: Config) -> int:
    sec = max(2, int(getattr(cfg, "followup_listen_sec", 5) or 5))
    return int(sec * 1000 / FRAME_DURATION_MS)


def _conversation_idle_wait_frames(cfg: Config) -> int:
    sec = max(2, int(getattr(cfg, "conversation_idle_timeout_sec", 20) or 20))
    return int(sec * 1000 / FRAME_DURATION_MS)


def _answer_wait_frames(cfg: Config) -> int:
    return max(_followup_wait_frames(cfg), ANSWER_WAIT_FRAMES)


_END_PHRASES = (
    "that's all", "thats all", "that's it", "thats it", "that's everything",
    "that's all for now", "thats all for now",
    "thank you jarvis", "thanks jarvis", "goodbye", "bye jarvis",
    "never mind", "nevermind", "nothing else", "i'm done", "im done", "we're done", "were done",
    "that'll be all",
)

MAX_FOLLOWUP_MISSES = 3


def _is_end_phrase(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!? ")
    return any(t == p or t.endswith(" " + p) for p in _END_PHRASES)


def _reset_audio_for_followup(
    wake_event: threading.Event,
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
) -> None:
    """Clear wake/barge residue so the follow-up mic window opens reliably."""
    wake_event.clear()
    capturing.clear()
    paused.clear()
    _drain_queue(capture_queue)


def _await_followup_utterance(
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    cfg: Config,
    set_state: Callable[[str], None],
    wake_event: threading.Event,
    *,
    last_reply: str | None = None,
    max_misses: int = MAX_FOLLOWUP_MISSES,
) -> str | None:
    """Listen for a follow-up; tolerate consecutive empty STT results before giving up."""
    awaiting_answer = bool((last_reply or "").rstrip().endswith("?"))
    attempts = 2 if awaiting_answer else max_misses
    misses = 0
    while misses < attempts and not _interrupt.is_set():
        _reset_audio_for_followup(wake_event, capture_queue, capturing, paused)
        if misses == 0:
            transition(set_state, SpeechPhase.FOLLOWUP_WINDOW, reason="follow-up")
            if awaiting_answer:
                logger.info("👂 Waiting for your answer…")
            else:
                logger.info("👂 Listening for follow-up…")
        elif awaiting_answer:
            logger.info("👂 Still listening for your answer…")
        else:
            logger.info("👂 Didn't catch that — still listening…")
        wait_frames = _answer_wait_frames(cfg) if awaiting_answer else _followup_wait_frames(cfg)
        text = _capture_and_transcribe(
            capture_queue,
            capturing,
            paused,
            cfg,
            set_state,
            wait_for_speech_frames=wait_frames,
            silence_ms=cfg.followup_vad_silence_ms,
            min_capture_ms=cfg.followup_vad_min_capture_ms,
        )
        if _interrupt.is_set():
            return None
        if text is not None:
            if _is_end_phrase(text):
                speak("Okay.")
                set_state("IDLE")
                return None
            return text
        misses += 1
    set_state("IDLE")
    return None


def wake_detection_paused(
    capturing: threading.Event,
    paused: threading.Event,
    *,
    pipeline_state: str | None = None,
) -> bool:
    """True when the mic thread must not run openWakeWord predict (F5)."""
    if capturing.is_set() or paused.is_set():
        return True
    state = pipeline_state
    if state is None:
        state = events.get_state().get("pipeline_state", "IDLE")
    return state in WAKE_DETECTION_OFF_STATES


def _sync_detection_pause(state: str, paused: threading.Event) -> None:
    """Mirror pipeline state into the detection-pause flag (F5)."""
    if state in WAKE_DETECTION_OFF_STATES:
        paused.set()


def _drain_queue(q: "queue.Queue[bytes]") -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


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
    import time

    import numpy as np

    from adapters.stt import transcribe as stt_transcribe
    from improvement.trace import get_active_trace, stash_stt_metrics

    t0 = time.monotonic()
    confidence: float | None = None
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    raw = stt_transcribe(
        audio_np,
        cfg.effective_stt_model(),
        cfg.stt_backend,
        hotwords=_stt_hotwords() or None,
        device=cfg.stt_device,
        compute_type=cfg.stt_compute_type,
    )

    text = strip_wake_phrase(raw, cfg.wake_word)
    if raw != text:
        logger.debug("📝 Raw transcript (pre-strip): %r", raw)
    logger.info("📝 Heard: %r", text)
    stt_ms = int((time.monotonic() - t0) * 1000)
    stash_stt_metrics(text, confidence=confidence, stt_ms=stt_ms)
    active = get_active_trace()
    if active is not None:
        active.stt_text = text
        active.stt_confidence = confidence
        active.stt_ms = stt_ms
    return text


def _capture_and_transcribe(
    capture_queue: "queue.Queue[bytes]",
    capturing: threading.Event,
    paused: threading.Event,
    cfg: Config,
    set_state: Callable[[str], None],
    *,
    wait_for_speech_frames: int = WAIT_FOR_SPEECH_FRAMES,
    silence_ms: int | None = None,
    min_capture_ms: int | None = None,
    skip_drain: bool = False,
) -> str | None:
    """Record one utterance and transcribe it. Returns None if nothing was heard."""
    transition(set_state, SpeechPhase.LISTENING, reason="capture")
    # Skip drain when wake/barge-in already queued opening frames.
    if not skip_drain and not capturing.is_set():
        _drain_queue(capture_queue)
    capturing.set()
    audio_bytes = _record_from_queue(
        capture_queue,
        wait_for_speech_frames,
        silence_ms=silence_ms if silence_ms is not None else cfg.vad_silence_ms,
        min_capture_ms=min_capture_ms if min_capture_ms is not None else cfg.vad_min_capture_ms,
        interrupt_check=interrupt_requested,
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

    transition(set_state, SpeechPhase.THINKING, reason="transcribe")
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
    """Pre-load STT model, contact hotwords, and Windows Start-menu apps."""
    warm_stt_caches()
    import platform as _platform

    if _platform.system() == "Windows":
        from tools.system import warm_windows_start_apps

        warm_windows_start_apps()

    from adapters.stt import warmup as stt_warmup

    stt_warmup(
        cfg.effective_stt_model(),
        cfg.stt_backend,
        device=cfg.stt_device,
        compute_type=cfg.stt_compute_type,
    )


def _build_system_blocks(cfg: Config, query_text: str = "") -> list[dict[str, Any]]:
    """System prompt split into a cacheable static block and a dynamic memory block.

    Block 1 (cache_control: ephemeral): full system prompt with runtime variables
    filled in (developer_name, platform, timezone). Stable within a session so the
    Anthropic prompt cache hits on every turn.

    Block 2 (no cache): per-query memory variables and semantic recall notes.
    """
    import datetime
    import platform as _plat

    _sys = _plat.system()
    platform_name = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(
        _sys, _sys
    )
    if _sys == "Darwin":
        platform_detail = "Apple Silicon" if _plat.machine() == "arm64" else "Intel Mac"
    elif _sys == "Windows":
        platform_detail = "Windows PC"
    else:
        platform_detail = _sys

    developer_name = (cfg.developer_name or "Jack").strip()

    tz = (cfg.timezone or "").strip()
    if not tz:
        try:
            tz = datetime.datetime.now().astimezone().strftime("%Z")
        except Exception:  # noqa: BLE001
            tz = "UTC"

    static_text = _SYSTEM_PROMPT_TEMPLATE.format(
        developer_name=developer_name,
        platform=platform_name,
        platform_detail=platform_detail,
        timezone=tz,
    )

    logger.debug("🧠 System prompt preview: %.200s", static_text)

    variables_block = build_variables_block()
    if cfg.memory_semantic_recall and query_text.strip():
        notes_block = build_recall_context(query_text, cfg)
    else:
        notes_block = get_recent_notes(cfg.memory_inject_last_n_notes)

    return [
        {
            "type": "text",
            "cache_control": {"type": "ephemeral"},
            "text": static_text,
        },
        {
            "type": "text",
            "text": (
                f"Known facts about {developer_name}:\n{variables_block}\n\n"
                f"Relevant memories:\n{notes_block}"
            ),
        },
    ]


def _build_system_prompt(cfg: Config, query_text: str = "") -> str:
    """Flat system prompt for callers that do not use block caching."""
    blocks = _build_system_blocks(cfg, query_text)
    return blocks[0]["text"] + "\n\n" + blocks[1]["text"]


class _SentenceEmitter:
    """Split streamed text deltas into speakable sentence chunks."""

    _BOUNDARY = re.compile(r"[.!?…\n]")
    _SOFT_CAP = 120

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
    *,
    phone_mode: bool = False,
) -> tuple[str, str, float, bool]:
    from llm import get_llm_client
    from llm.router import models_for, resolve_models

    provider, fast_model, smart_model = resolve_models(text, cfg)
    client = get_llm_client(cfg, timeout=CLAUDE_HTTP_TIMEOUT_SEC, provider=provider)
    model = fast_model
    switched_to_anthropic = False
    logger.info("🧠 Routed to %s — starting on %s (escalate → %s)", provider, model, smart_model)

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
            tools=get_tool_definitions(cfg.developer_mode, cfg.demo_mode),
            messages=messages,
        )
        with _claude_future_lock:
            global _active_claude_future
            _active_claude_future = future
        try:
            while not future.done():
                if _interrupt.is_set():
                    logger.info("⏹️  Stop during Claude — abandoning in-flight request.")
                    future.cancel()
                    return "", model, total_cost, stream_spoken
                time.sleep(0.05)

            try:
                response = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("⚠️  Claude API error: %s", exc, exc_info=True)
                if _interrupt.is_set():
                    return "", model, total_cost, stream_spoken
                if (
                    not switched_to_anthropic
                    and provider != "anthropic"
                    and (cfg.anthropic_api_key or "").strip()
                ):
                    logger.warning(
                        "⚠️  %s failed (%s) — retrying this turn on Anthropic.", provider, exc
                    )
                    on_smart_tier = model == smart_model
                    switched_to_anthropic = True
                    provider = "anthropic"
                    client = get_llm_client(
                        cfg, timeout=CLAUDE_HTTP_TIMEOUT_SEC, provider="anthropic"
                    )
                    fast_model, smart_model = models_for("anthropic", cfg)
                    model = smart_model if on_smart_tier else fast_model
                    continue
                return "Sorry, I couldn't reach my brain. Please try again.", model, total_cost, stream_spoken
        finally:
            with _claude_future_lock:
                if _active_claude_future is future:
                    _active_claude_future = None

        if response is None:
            logger.info("⏹️  Claude stream cancelled — no tokens charged past cut-off.")
            return "", model, total_cost, stream_spoken

        if _interrupt.is_set():
            logger.info("⏹️  Claude loop aborted after response (interrupt).")
            return "", model, total_cost, stream_spoken

        total_cost += costs.log_usage(model, getattr(response, "usage", None), text)
        from improvement.trace import get_active_trace

        active = get_active_trace()
        if active is not None:
            active.apply_usage(getattr(response, "usage", None))

        reply_text = ""
        tool_uses: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                reply_text += block.text
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

        if model == fast_model and any(tu["name"] == "escalate" for tu in tool_uses):
            logger.info("⬆️  Escalating to %s for this turn.", smart_model)
            model = smart_model

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
                not phone_mode
                and cfg.confirm_before_execute
                and tu["name"] in CONFIRM_REQUIRED_TOOLS
            )
            if needs_confirm:
                _emit_pipeline_state("WAITING_CONFIRM", on_state)
                if not _interrupt.is_set() and not on_sentence:
                    logger.info("🔔 Awaiting dashboard approval for %s", tu["name"])
                    speak(CONFIRM_PROMPT)
                elif not _interrupt.is_set():
                    logger.info("🔔 Awaiting dashboard approval for %s (streaming — no TTS prompt)", tu["name"])
            if _interrupt.is_set():
                logger.info("⏹️  Tool confirm skipped (interrupt).")
                return reply_text.strip() or "Stopped.", model, total_cost, stream_spoken
            t_tool = time.monotonic()
            tool_error: str | None = None
            try:
                if phone_mode and not phone_tool_allowed(tu["name"]):
                    result = (
                        f"Tool '{tu['name']}' cannot run during a phone call. "
                        "Offer to transfer the caller to a human."
                    )
                else:
                    result = dispatch_tool(
                        tu["name"],
                        tu["input"],
                        confirm=cfg.confirm_before_execute and not phone_mode,
                        confirm_timeout_sec=cfg.confirm_timeout_sec,
                        cancel_check=interrupt_requested,
                        developer_mode=cfg.developer_mode,
                        phone_mode=phone_mode,
                    )
            except Exception as exc:  # noqa: BLE001
                tool_error = str(exc)
                result = f"Tool error: {exc}"
            tool_ms = int((time.monotonic() - t_tool) * 1000)
            from improvement.trace import get_active_trace, record_tool_call

            active = get_active_trace()
            if active is not None:
                record_tool_call(
                    active.turn_id,
                    tu["name"],
                    tu["input"] if isinstance(tu["input"], dict) else {"input": tu["input"]},
                    result,
                    tool_ms,
                    error=tool_error,
                )
                active.add_tool_ms(tool_ms)
            try:
                from orchestrator.runtime import get_bus
                get_bus().emit("tool.run", name=tu["name"], ok=not bool(tool_error), source="voice")
            except Exception:  # noqa: BLE001
                pass
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
    session_id: str | None = None,
    *,
    phone_mode: bool = False,
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
        if session_id:
            from orchestrator.runtime import get_session_store
            from orchestrator.types import Command, Turn

            session = get_session_store().get(session_id)
            if session is not None:
                history = conversation.build_messages_from_session_turns(
                    session.turns,
                    cfg.conversation_history_turns,
                    cfg.conversation_history_max_chars,
                )
            else:
                history = conversation.build_messages(
                    cfg.conversation_history_turns,
                    cfg.conversation_history_max_chars,
                )
        else:
            history = conversation.build_messages(
                cfg.conversation_history_turns,
                cfg.conversation_history_max_chars,
            )
        reply, model, cost, stream_spoken = _call_claude(
            text, cfg, history=history, on_state=on_state, on_sentence=on_sentence,
            phone_mode=phone_mode,
        )
        latency_ms = int((time.time() - t0) * 1000)
        if _should_store_in_history(reply):
            if session_id:
                from orchestrator.runtime import get_session_store
                from orchestrator.types import Command, Turn

                session = get_session_store().get(session_id)
                if session is not None:
                    session.add_turn(
                        Turn(
                            session_id=session_id,
                            command=Command(text=text, source=session.source, speak=False),
                            reply=(reply or "").strip(),
                            model=model or "",
                            latency_ms=latency_ms,
                            cost=cost,
                        )
                    )
            else:
                conversation.add_turn(text, reply)
            record_exchange(text, reply, cfg)
        cleaned_reply = (reply or "").strip()
        if cleaned_reply:
            events.record_conversation(text, cleaned_reply, model, latency_ms, cost)
        logger.info("💰 Call cost $%.4f (%dms) — %s", cost, latency_ms, model)
        from improvement.trace import get_active_trace

        active = get_active_trace()
        payload = {
            "reply": reply,
            "warning": warning,
            "capped": False,
            "busy": False,
            "model": model,
            "latency_ms": latency_ms,
            "cost": cost,
            "stream_spoken": stream_spoken,
        }
        if active is not None:
            payload["tokens_in"] = active.tokens_in
            payload["tokens_out"] = active.tokens_out
            payload["cache_read_tokens"] = active.cache_read_tokens
            if active.tts_ms is not None:
                payload["tts_ms"] = active.tts_ms
            if active.details.get("tts_provider"):
                payload["tts_provider"] = active.details["tts_provider"]
        return payload
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
    barge_gate: BargeInGate,
    timeout: float = VOICE_JOB_TIMEOUT_SEC,
) -> tuple[Any, bool]:
    """Wait for a voice job, allowing VAD barge-in once TTS is playing.

    Returns ``(job, barged)``. Wake-word detection stays off during the reply
    (echo guard). After ``BARGEIN_GRACE_SEC`` of SPEAKING, VAD barge-in arms:
    sustained user speech stops TTS and returns ``barged=True``.
    """
    barge_gate.reset()
    speaking_since: float | None = None
    deadline = time.monotonic() + timeout
    while True:
        job = orchestrator.wait(job_id, timeout=0.1)
        if job is None or job.done_event.is_set() or time.monotonic() > deadline:
            barge_gate.reset()
            _reset_audio_for_followup(wake_event, capture_queue, capturing, paused)
            return job, False

        if not cfg.barge_in_enabled:
            continue

        state = events.get_state().get("pipeline_state")
        if state == SpeechPhase.SPEAKING.value and speaking_since is None:
            speaking_since = time.monotonic()

        if (
            speaking_since is not None
            and not barge_gate.armed.is_set()
            and time.monotonic() - speaking_since >= BARGEIN_GRACE_SEC
        ):
            barge_gate.armed.set()
            barge_gate.speech_frames = 0
            _drain_queue(capture_queue)
            logger.debug("🎙️  VAD barge-in armed (grace %.0fms elapsed).", BARGEIN_GRACE_SEC * 1000)

        if barge_gate.triggered.is_set():
            logger.info("⏹️  Barge-in — abandoning reply to capture user speech.")
            orchestrator.cancel_current()
            barge_gate.reset()
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
        _sync_detection_pause(name, paused)

    from orchestrator.runtime import get_lane_manager, get_orchestrator, get_session_store
    from orchestrator.types import Command, CommandSource

    orchestrator = get_orchestrator()
    lane_manager = get_lane_manager()
    voice_lane = lane_manager.voice
    session_store = get_session_store()

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
    barge_gate = BargeInGate()

    current_wake_word = wake_model_from_config(cfg)
    _ensure_wake_model(current_wake_word)
    audio_thread = _start_audio_thread(
        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
        barge_gate,
    )

    try:
        while not (stop_event and stop_event.is_set()):
            try:
                cfg = Config.load()

                resolved = wake_model_from_config(cfg)
                if resolved != current_wake_word:
                    logger.info("🔁 Wake model changed to %r — rebuilding listener.", resolved)
                    audio_stop.set()
                    if audio_thread is not None:
                        audio_thread.join(timeout=5.0)
                    _ensure_wake_model(resolved)
                    current_wake_word = resolved
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
                        barge_gate,
                    )

                if audio_thread is not None and not audio_thread.is_alive():
                    logger.error("⚠️  Audio thread is dead — restarting it.")
                    audio_stop.set()
                    audio_thread.join(timeout=5.0)
                    audio_stop = threading.Event()
                    audio_thread = _start_audio_thread(
                        wake_event, capture_queue, capturing, paused, audio_stop, current_wake_word,
                        barge_gate,
                    )

                if is_muted is not None:
                    events.set_muted(is_muted())
                push_budget_level(cfg)
                idle_timeout = max(
                    2, int(getattr(cfg, "conversation_idle_timeout_sec", 20) or 20)
                )
                voice_lane.idle_timeout_sec = float(idle_timeout)
                session_store.close_idle(older_than_sec=idle_timeout)
                set_state("IDLE")

                if not cfg.wake_word_enabled:
                    paused.set()
                    time.sleep(0.5)
                    continue

                paused.clear()
                capturing.clear()
                logger.debug("💤 Waiting for wake word…")

                # Hotkey (or any external trigger) can bypass the wake word wait.
                if _hotkey_pending.is_set():
                    _hotkey_pending.clear()
                    wake_event.clear()  # discard any coincident audio wake
                    logger.info("⌨️  Hotkey wake — skipping wake word.")
                elif not wake_event.wait(timeout=1.0):
                    continue
                else:
                    wake_event.clear()

                if is_muted is not None and is_muted():
                    logger.info(
                        "🔇 Muted — ignoring wake word. Click the orb to unmute."
                    )
                    capturing.clear()
                    _drain_queue(capture_queue)
                    continue

                text = _capture_and_transcribe(
                    capture_queue, capturing, paused, cfg, set_state,
                )
                if text is None:
                    continue

                if _is_end_phrase(text):
                    active = voice_lane.active_session()
                    if active is not None:
                        session_store.close(active.id)
                    speak("Okay.")
                    set_state("IDLE")
                    continue

                # Process the wake-triggered query, then keep the session open
                # for follow-ups via the next wake word (or idle timeout).
                while text is not None:
                    if _interrupt.is_set():
                        logger.info("⏹️  Cycle aborted.")
                        set_state("IDLE")
                        break

                    sub = voice_lane.submit(
                        Command(text=text, source=CommandSource.VOICE, speak=True),
                    )
                    if not sub.accepted:
                        logger.warning("⏳ Queue full — voice command rejected.")
                        speak(BUSY_MESSAGE)
                        set_state("IDLE")
                        break

                    job, barged = _wait_for_job_with_bargein(
                        orchestrator, sub.job_id, cfg,
                        wake_event, capture_queue, capturing, paused, barge_gate,
                    )
                    push_budget_level(cfg)
                    if job is not None and job.reply:
                        logger.info("💬 Reply: %s", job.reply)

                    voice_session_id = job.session_id if job is not None else None

                    if barged:
                        _clear_interrupt()
                        wake_event.clear()
                        transition(set_state, SpeechPhase.LISTENING, reason="barge-in")
                        text = _capture_and_transcribe(
                            capture_queue, capturing, paused, cfg, set_state,
                            skip_drain=True,
                        )
                        if text is None:
                            break
                        continue

                    if _interrupt.is_set():
                        logger.info("⏹️  Cycle aborted.")
                        set_state("IDLE")
                        break

                    if job is not None and job.capped:
                        if voice_session_id:
                            session_store.close(voice_session_id)
                        break

                    if voice_session_id:
                        session_store.mark_idle(voice_session_id)
                    break

            except Exception as exc:  # noqa: BLE001
                logger.error("⚠️  Pipeline cycle failed: %s", exc, exc_info=True)
                logger.info("↩️  Resuming wake-word wait after cycle error.")
            finally:
                capturing.clear()
                paused.clear()
                wake_event.clear()
                _drain_queue(capture_queue)
                _clear_interrupt()

    finally:
        audio_stop.set()
