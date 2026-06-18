"""Dashboard calendar day view — mocked Google Calendar API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dashboard.app import create_app

_SAMPLE_EVENT = {
    "id": "ev1",
    "summary": "Standup",
    "start": {"dateTime": "2026-06-11T09:00:00-07:00"},
    "end": {"dateTime": "2026-06-11T09:30:00-07:00"},
    "location": "https://zoom.us/j/123456789?pwd=secret",
}


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_extract_zoom_link_from_location():
    from tools.google_calendar import _extract_zoom_link

    link = _extract_zoom_link(_SAMPLE_EVENT)
    assert link is not None
    assert link.startswith("zoommtg://")
    assert "123456789" in link
    assert "pwd=secret" in link


def test_extract_zoom_link_from_conference_data():
    from tools.google_calendar import _extract_zoom_link

    event = {
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "video", "uri": "https://us02web.zoom.us/j/999888777?pwd=abc"},
            ]
        }
    }
    link = _extract_zoom_link(event)
    assert link == "zoommtg://us02web.zoom.us/join?confno=999888777&pwd=abc"


def test_fetch_calendar_day_structured():
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {"items": [_SAMPLE_EVENT]}
    with patch("tools.google_calendar.get_calendar_service", return_value=mock_service):
        from tools.google_calendar import fetch_calendar_day

        day = fetch_calendar_day("2026-06-11")
    assert day["date"] == "2026-06-11"
    assert len(day["events"]) == 1
    ev = day["events"][0]
    assert ev["title"] == "Standup"
    assert ev["time_label"]
    assert ev["zoom_link"].startswith("zoommtg://")
    assert ev["location"].startswith("https://zoom.us")


def test_fetch_calendar_day_all_day_event():
    mock_service = MagicMock()
    mock_service.events().list().execute.return_value = {
        "items": [
            {
                "id": "allday1",
                "summary": "Holiday",
                "start": {"date": "2026-06-11"},
                "end": {"date": "2026-06-12"},
            }
        ]
    }
    with patch("tools.google_calendar.get_calendar_service", return_value=mock_service):
        from tools.google_calendar import fetch_calendar_day

        day = fetch_calendar_day("2026-06-11")
    assert day["events"][0]["all_day"] is True
    assert day["events"][0]["time_label"] == "All day"


def test_api_calendar_day(client):
    sample = {
        "date": "2026-06-11",
        "label": "Thursday 11 June 2026",
        "events": [
            {
                "id": "ev1",
                "title": "Standup",
                "all_day": False,
                "time_label": "9:00 AM",
                "end_time_label": "9:30 AM",
                "location": "Zoom",
                "zoom_link": "zoommtg://zoom.us/join?confno=123",
            }
        ],
    }
    with patch("tools.google_calendar.fetch_calendar_day", return_value=sample):
        resp = client.get("/api/calendar/day?date=2026-06-11")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["events"][0]["title"] == "Standup"
    assert data["events"][0]["zoom_link"].startswith("zoommtg://")


def test_api_calendar_day_invalid_date(client):
    resp = client.get("/api/calendar/day?date=not-a-date")
    assert resp.status_code == 400


def test_api_calendar_day_handles_error(client):
    with patch("tools.google_calendar.fetch_calendar_day", side_effect=Exception("No auth")):
        resp = client.get("/api/calendar/day?date=2026-06-11")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert "No auth" in data["error"]


def test_api_calendar_day_defaults_to_today(client):
    with patch("tools.google_calendar.fetch_calendar_day", return_value={"date": "x", "label": "Today", "events": []}) as mock_fetch:
        resp = client.get("/api/calendar/day")
    assert resp.status_code == 200
    mock_fetch.assert_called_once()
    assert len(mock_fetch.call_args[0][0]) == 10


def test_get_todays_schedule_uses_fetch_calendar_day():
    with patch(
        "tools.google_calendar.fetch_calendar_day",
        return_value={
            "date": "2026-06-11",
            "label": "Thursday 11 June 2026",
            "events": [
                {
                    "title": "Standup",
                    "time_label": "9:00 AM",
                    "all_day": False,
                    "location": "Zoom",
                }
            ],
        },
    ):
        from tools.google_calendar import get_todays_schedule

        out = get_todays_schedule()
    assert "Standup" in out
    assert "9:00 AM" in out


def test_index_includes_calendar_nav(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b'data-view="calendar"' in r.data
    assert b"Calendar</span>" in r.data
