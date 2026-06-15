"""Weather via Open-Meteo (no API key)."""

from __future__ import annotations

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 8

_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 95: "thunderstorm",
}


def get_weather(location: str) -> str:
    try:
        import requests
    except ImportError as exc:
        return f"Weather lookup failed: {exc}"
    loc = (location or "").strip()
    if not loc:
        return "Location is required."
    try:
        results = None
        for candidate in dict.fromkeys([loc, loc.split(",")[0].strip()]):
            geo = requests.get(GEOCODE_URL, params={"name": candidate, "count": 1}, timeout=REQUEST_TIMEOUT)
            geo.raise_for_status()
            results = geo.json().get("results")
            if results:
                break
        if not results:
            return f"Could not find a location matching {loc!r}."
        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        label = ", ".join(filter(None, [place.get("name"), place.get("admin1"), place.get("country")]))
        fc = requests.get(
            FORECAST_URL,
            params={
                "latitude": lat, "longitude": lon, "current_weather": "true",
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "temperature_unit": "fahrenheit", "windspeed_unit": "mph", "timezone": "auto",
            },
            timeout=REQUEST_TIMEOUT,
        )
        fc.raise_for_status()
        body = fc.json()
        current = body.get("current_weather")
        if not current:
            return f"No current weather for {label}."
        condition = _WEATHER_CODES.get(current.get("weathercode"), "unknown")
        lines = [
            f"{label}: {current['temperature']}°F, {condition}, wind {current['windspeed']} mph.",
            "3-day forecast:",
        ]
        daily = body.get("daily", {})
        dates = daily.get("time", [])[:3]
        maxs = daily.get("temperature_2m_max", [])[:3]
        mins = daily.get("temperature_2m_min", [])[:3]
        codes = daily.get("weathercode", [])[:3]
        for i, d in enumerate(dates):
            desc = _WEATHER_CODES.get(codes[i] if i < len(codes) else 0, "unknown")
            lines.append(f"  {d}: {mins[i]}–{maxs[i]}°F, {desc}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Weather lookup failed: {exc}"
