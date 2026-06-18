"""Google Calendar tools for Jarvis."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html import unescape

from tools.google_auth import get_google_service

_ZOOM_HTTP_RE = re.compile(
    r"https?://(?:[\w.-]+\.)?zoom\.us/j/(?P<id>\d+)(?:\?(?:[^\s\"'<>]*&)?pwd=(?P<pwd>[^&\s\"'<>]+))?",
    re.IGNORECASE,
)
_ZOOM_MTG_RE = re.compile(r"zoommtg://[^\s\"'<>]+", re.IGNORECASE)


def get_calendar_service():
    return get_google_service("calendar", "v3")


def _http_zoom_to_mtg(url: str) -> str | None:
    match = _ZOOM_HTTP_RE.search(url)
    if not match:
        return None
    host_match = re.search(r"https?://([\w.-]+\.zoom\.us)/", url, re.IGNORECASE)
    host = host_match.group(1) if host_match else "zoom.us"
    confno = match.group("id")
    pwd = match.group("pwd") or ""
    uri = f"zoommtg://{host}/join?confno={confno}"
    if pwd:
        uri += f"&pwd={pwd}"
    return uri


def _extract_zoom_link(event: dict) -> str | None:
    conference = event.get("conferenceData") or {}
    for entry in conference.get("entryPoints") or []:
        uri = (entry.get("uri") or "").strip()
        if not uri:
            continue
        if uri.lower().startswith("zoommtg://"):
            return uri
        if "zoom.us" in uri.lower():
            converted = _http_zoom_to_mtg(uri)
            if converted:
                return converted

    for field in (event.get("location") or "", event.get("description") or ""):
        text = unescape(re.sub(r"<[^>]+>", " ", field or ""))
        mtg = _ZOOM_MTG_RE.search(text)
        if mtg:
            return mtg.group(0)
        converted = _http_zoom_to_mtg(text)
        if converted:
            return converted
    return None


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=1)


def _format_time_label(raw: str) -> str:
    if not raw or "T" not in raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return raw


def _structure_event(event: dict) -> dict:
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    start_dt = start_raw.get("dateTime")
    start_date = start_raw.get("date")
    all_day = bool(start_date and not start_dt)
    start_iso = start_dt or start_date or ""
    end_iso = end_raw.get("dateTime") or end_raw.get("date") or ""

    time_label = "All day"
    end_time_label = ""
    duration_minutes = None
    timeline_start = None

    if not all_day and start_dt:
        try:
            dt_start = datetime.fromisoformat(start_dt)
            time_label = dt_start.strftime("%I:%M %p").lstrip("0")
            timeline_start = dt_start.hour * 60 + dt_start.minute
            end_dt_raw = end_raw.get("dateTime")
            if end_dt_raw:
                dt_end = datetime.fromisoformat(end_dt_raw)
                end_time_label = dt_end.strftime("%I:%M %p").lstrip("0")
                duration_minutes = max(15, int((dt_end - dt_start).total_seconds() // 60))
        except ValueError:
            time_label = _format_time_label(start_dt) or "—"

    return {
        "id": event.get("id", ""),
        "title": event.get("summary") or "(no title)",
        "start": start_iso,
        "end": end_iso,
        "all_day": all_day,
        "time_label": time_label,
        "end_time_label": end_time_label,
        "duration_minutes": duration_minutes,
        "timeline_start": timeline_start,
        "location": event.get("location") or "",
        "zoom_link": _extract_zoom_link(event),
    }


def fetch_calendar_day(date_str: str) -> dict:
    """Return structured calendar events for one local day (YYYY-MM-DD)."""
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    start, end = _day_bounds(day)
    service = get_calendar_service()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )
    items = result.get("items", [])
    events = [_structure_event(ev) for ev in items]
    return {
        "date": date_str,
        "label": start.strftime("%A %d %B %Y"),
        "events": events,
    }


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
    today = datetime.now().astimezone().date().isoformat()
    day = fetch_calendar_day(today)
    items = day["events"]
    if not items:
        return "Your calendar is clear for today."

    spoken: list[str] = []
    for i, ev in enumerate(items, 1):
        summary = ev.get("title", "Untitled event")
        time_part = ev.get("time_label") or ""
        if ev.get("all_day"):
            time_part = "all day"
        location = ev.get("location")
        line = f"{i}. {summary}"
        if time_part:
            line += f" at {time_part}"
        if location:
            line += f", {location}"
        spoken.append(line)
    return "Today's schedule: " + "; ".join(spoken) + "."
