"""Cron scheduler for plugin triggers."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from orchestrator.types import Command, CommandSource

logger = logging.getLogger(__name__)


class PluginScheduler:
    def __init__(self, orchestrator) -> None:
        self._orchestrator = orchestrator
        self._timers: list[threading.Timer] = []
        self._running = True
        self._lock = threading.Lock()

    def register_plugins(self, plugins: list[dict]) -> int:
        count = 0
        for plugin in plugins:
            trigger = plugin.get("trigger", {})
            if trigger.get("type") != "cron" or not plugin.get("enabled", True):
                continue
            if not (trigger.get("schedule") or "").strip():
                continue
            self._schedule_next(plugin)
            count += 1
            logger.info("Scheduled plugin '%s': %s", plugin.get("name"), trigger.get("schedule"))
        return count

    def _schedule_next(self, plugin: dict) -> None:
        delay = _seconds_until_next(plugin["trigger"]["schedule"])
        if delay is None:
            logger.warning("Cannot parse cron for %s", plugin.get("name"))
            return
        timer = threading.Timer(delay, lambda p=plugin: self._fire(p))
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()

    def _fire(self, plugin: dict) -> None:
        if not self._running:
            return
        logger.info("Cron firing plugin '%s'", plugin.get("name"))
        prompt = (plugin.get("prompt") or "").strip()
        if prompt:
            self._orchestrator.submit(
                Command(text=prompt, source=CommandSource.SCHEDULE, speak=True),
            )
        if self._running:
            self._schedule_next(plugin)

    def shutdown(self) -> None:
        self._running = False
        with self._lock:
            for timer in self._timers:
                timer.cancel()
            self._timers.clear()

    def _parse_interval(self, cron_expr: str) -> int | None:
        """Parse basic cron expressions — seconds until next fire."""
        return _seconds_until_next(cron_expr)


def _seconds_until_next(cron_expr: str) -> int | None:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None
    minute_part, hour_part = parts[0], parts[1]
    now = datetime.now()
    if minute_part.startswith("*/") and hour_part == "*":
        try:
            return max(1, int(minute_part[2:]) * 60)
        except ValueError:
            return None
    if hour_part.startswith("*/"):
        try:
            return max(1, int(hour_part[2:]) * 3600)
        except ValueError:
            return None
    try:
        target = now.replace(hour=int(hour_part), minute=int(minute_part), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1, int((target - now).total_seconds()))
    except (ValueError, OverflowError):
        return None
