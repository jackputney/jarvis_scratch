"""Speech turn state machine helpers for the voice pipeline (Phase 2).

States: IDLE → LISTENING → THINKING → SPEAKING → FOLLOWUP_WINDOW → IDLE
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("jarvis.voice")

# Grace after TTS starts before VAD barge-in arms (avoids echo / wake residue).
# NOTE (Jack): raised 0.8→1.5 to reduce self-trigger from speaker bleed without AEC.
BARGEIN_GRACE_SEC = 1.5

# Pipeline states where openWakeWord predict must stay off (echo guard).
WAKE_DETECTION_OFF_STATES = frozenset(
    {"LISTENING", "SPEAKING", "THINKING", "WAITING_CONFIRM", "FOLLOWUP_WINDOW"}
)


class SpeechPhase(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    FOLLOWUP_WINDOW = "FOLLOWUP_WINDOW"
    WAITING_CONFIRM = "WAITING_CONFIRM"


@dataclass
class BargeInGate:
    """Shared VAD barge-in state between the audio thread and pipeline loop."""

    armed: threading.Event = field(default_factory=threading.Event)
    triggered: threading.Event = field(default_factory=threading.Event)
    speech_frames: int = 0

    def reset(self) -> None:
        self.armed.clear()
        self.triggered.clear()
        self.speech_frames = 0


def transition(set_state: Callable[[str], None], phase: SpeechPhase, *, reason: str = "") -> None:
    """Apply a pipeline state with an optional structured reason suffix."""
    if reason:
        logger.info("STATE: → %s (%s)", phase.value, reason)
    set_state(phase.value)
