"""Tests for adapters.wake_metrics — wake-word accuracy tracking."""

from __future__ import annotations

import pytest

from adapters.wake_metrics import (
    get_false_positive_candidates,
    get_wake_stats,
    log_wake_event,
)


class TestLogWakeEvent:
    def test_inserts_row(self, temp_env):
        log_wake_event("hey_jarvis", 0.92, accepted=True)
        stats = get_wake_stats(hours=1)
        assert stats["total_detections"] == 1
        assert stats["accepted_count"] == 1

    def test_rejected_event(self, temp_env):
        log_wake_event("hey_jarvis", 0.15, accepted=False, source="test")
        stats = get_wake_stats(hours=1)
        assert stats["rejected_count"] == 1
        assert stats["accepted_count"] == 0


class TestGetWakeStats:
    def test_empty_db(self, temp_env):
        stats = get_wake_stats(hours=24)
        assert stats["total_detections"] == 0
        assert stats["accepted_count"] == 0
        assert stats["rejected_count"] == 0
        assert stats["avg_confidence_accepted"] is None
        assert stats["avg_confidence_rejected"] is None

    def test_mixed_events(self, temp_env):
        log_wake_event("hey_jarvis", 0.90, accepted=True)
        log_wake_event("hey_jarvis", 0.85, accepted=True)
        log_wake_event("hey_jarvis", 0.20, accepted=False)

        stats = get_wake_stats(hours=1)
        assert stats["total_detections"] == 3
        assert stats["accepted_count"] == 2
        assert stats["rejected_count"] == 1
        assert stats["avg_confidence_accepted"] == pytest.approx(0.875)
        assert stats["avg_confidence_rejected"] == pytest.approx(0.20)


class TestGetFalsePositiveCandidates:
    def test_empty_db(self, temp_env):
        assert get_false_positive_candidates(hours=24) == []

    def test_returns_low_confidence_accepted(self, temp_env):
        log_wake_event("hey_jarvis", 0.25, accepted=True)   # below 0.3
        log_wake_event("hey_jarvis", 0.90, accepted=True)   # above 0.3
        log_wake_event("hey_jarvis", 0.10, accepted=False)  # rejected, ignored

        results = get_false_positive_candidates(hours=1, min_confidence=0.3)
        assert len(results) == 1
        assert results[0]["confidence"] == pytest.approx(0.25)
        assert results[0]["detected_word"] == "hey_jarvis"

    def test_custom_threshold(self, temp_env):
        log_wake_event("hey_jarvis", 0.45, accepted=True)
        log_wake_event("hey_jarvis", 0.55, accepted=True)

        results = get_false_positive_candidates(hours=1, min_confidence=0.5)
        assert len(results) == 1
        assert results[0]["confidence"] == pytest.approx(0.45)
