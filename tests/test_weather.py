"""Weather tool — Open-Meteo, mocked HTTP."""

from unittest.mock import MagicMock, patch

from tools.registry import READ_ONLY_TOOLS, TOOL_DISPATCH
from tools.weather import get_weather


def test_weather_tool_registered():
    assert "get_weather" in TOOL_DISPATCH
    assert "get_weather" in READ_ONLY_TOOLS


def test_weather_tool_parses_response():
    geo = {"results": [{"name": "London", "admin1": "England", "country": "UK",
                        "latitude": 51.5, "longitude": -0.12}]}
    forecast = {
        "current_weather": {"temperature": 62, "weathercode": 0, "windspeed": 8},
        "daily": {
            "time": ["2026-06-15", "2026-06-16", "2026-06-17"],
            "temperature_2m_max": [65, 66, 64],
            "temperature_2m_min": [50, 51, 49],
            "weathercode": [0, 1, 2],
        },
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = [geo, forecast]

    with patch("requests.get", return_value=mock_resp):
        result = get_weather("London")
    assert "London" in result
    assert "62°F" in result
    assert "3-day forecast" in result
