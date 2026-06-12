"""Google Calendar tools for Jarvis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tools.google_auth import get_google_service


def get_calendar_service():
    return get_google_service("calendar", "v3")


def _format_event(event: dict) -> str:
    summary = event.get("summary", "(no title)")
    start = event.get("start", {})
    when = start.get("dateTime") or start.get("date") or "unknown time"
    location = event.get("location") or ""
    attendees = event.get("attendees") or []
    attendee_str = ", ".join(
        a.get("email", "") for a in attendees if a.get("email")
    )
    parts = [f"- {summary} @ {when}"]
    if location:
        parts.append(f"  location: {location}")
    if attendee_str:
        parts.append(f"  attendees: {attendee_str}")
    return "\n".join(parts)


def get_calendar_events(days: int = 7) -> str:
    """Return upcoming calendar events for the next N days."""
    days = max(1, min(int(days), 30))
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )
    items = result.get("items", [])
    if not items:
        return f"No upcoming events in the next {days} day(s)."
    lines = [f"Upcoming events (next {days} day(s)):"]
    lines.extend(_format_event(ev) for ev in items)
    return "\n".join(lines)


def get_todays_schedule() -> str:
    """Return today's events formatted for speaking aloud."""
    service = get_calendar_service()
    local_now = datetime.now().astimezone()
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=30,
        )
        .execute()
    )
    items = result.get("items", [])
    if not items:
        return "Your calendar is clear for today."

    spoken: list[str] = []
    for i, ev in enumerate(items, 1):
        summary = ev.get("summary", "Untitled event")
        start_raw = ev.get("start", {})
        when = start_raw.get("dateTime") or start_raw.get("date") or ""
        time_part = ""
        if "T" in when:
            try:
                dt = datetime.fromisoformat(when)
                time_part = dt.strftime("%I:%M %p").lstrip("0")
            except ValueError:
                time_part = when
        elif when:
            time_part = "all day"
        location = ev.get("location")
        line = f"{i}. {summary}"
        if time_part:
            line += f" at {time_part}"
        if location:
            line += f", {location}"
        spoken.append(line)
    return "Today's schedule: " + "; ".join(spoken) + "."
