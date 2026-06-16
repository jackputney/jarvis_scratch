"""tools/time_date.py — Current time and date tool."""

from __future__ import annotations

import time as _time
from datetime import datetime


def get_current_time(timezone: str = "") -> str:
    """Return the current date, time, day of week, and timezone.

    If timezone is empty, uses the system local timezone.
    """
    if timezone.strip():
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(timezone.strip()))
            tz_name = timezone.strip()
        except Exception:
            now = datetime.now()
            tz_name = _time.tzname[_time.daylight] if _time.daylight else _time.tzname[0]
    else:
        now = datetime.now()
        tz_name = _time.tzname[_time.daylight] if _time.daylight else _time.tzname[0]

    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    return (
        f"Current date: {date_str}\n"
        f"Current time: {time_str}\n"
        f"Timezone: {tz_name}\n"
        f"Unix timestamp: {int(now.timestamp())}"
    )
