"""Wake-phrase stripping from Whisper transcripts."""

import pytest

from pipeline import strip_wake_phrase


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hey, Jarvis, listen.", "listen."),
        ("Hey Jarvis what's 977 times 3?", "what's 977 times 3?"),
        ("hey jarvis", ""),
        ("HEY JARVIS — tell me a joke.", "tell me a joke."),
        ("I need help with the math equation.", "I need help with the math equation."),
        ("6 times 8.", "6 times 8."),
        ("Thank you.", "Thank you."),
        ("", ""),
    ],
)
def test_strip_hey_jarvis_prefix(raw: str, expected: str) -> None:
    assert strip_wake_phrase(raw, "hey_jarvis") == expected


def test_strip_respects_custom_wake_word() -> None:
    assert strip_wake_phrase("Okay computer set a timer", "okay_computer") == "set a timer"


def test_strip_no_op_when_wake_word_empty() -> None:
    assert strip_wake_phrase("Hey Jarvis hi", "") == "Hey Jarvis hi"
