"""Weather lookup tool backed by the free Open-Meteo API (no API key required)."""

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> human-readable description
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherLookupError(Exception):
    """Raised when a city can't be geocoded or the forecast can't be fetched."""


def get_weather(city: str) -> dict:
    """Look up the current weather for a city name.

    Returns a dict with city, country, temperature_c, feels_like_c, humidity,
    wind_speed_kmh, and condition. Raises WeatherLookupError on failure.
    """
    geo_resp = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    geo_resp.raise_for_status()
    geo_results = geo_resp.json().get("results")
    if not geo_results:
        raise WeatherLookupError(f"Could not find a location named '{city}'.")

    location = geo_results[0]
    latitude = location["latitude"]
    longitude = location["longitude"]

    forecast_resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "weather_code,wind_speed_10m",
            "timezone": "auto",
        },
        timeout=10,
    )
    forecast_resp.raise_for_status()
    current = forecast_resp.json().get("current")
    if not current:
        raise WeatherLookupError(f"No forecast data returned for '{city}'.")

    weather_code = current.get("weather_code")

    return {
        "city": location.get("name", city),
        "country": location.get("country", ""),
        "admin1": location.get("admin1", ""),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "condition": WEATHER_CODES.get(weather_code, "Unknown"),
    }
