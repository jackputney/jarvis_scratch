"""Interrupt / stop smoke tests (UI Stop button path only)."""

import pipeline
from tts import cartesia


def test_request_interrupt_sets_flag():
    pipeline._clear_interrupt()
    cartesia._cancel.clear()
    pipeline.request_interrupt()
    assert pipeline.interrupt_requested()
    assert cartesia._cancel.is_set()


def test_clear_interrupt():
    pipeline.request_interrupt()
    pipeline._clear_interrupt()
    assert not pipeline.interrupt_requested()
    assert not cartesia._cancel.is_set()
