"""Weather lookup tools backed by the free Open-Meteo API (no API key required)."""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo's free daily forecast only reaches ~2 weeks out (and rejects a date range
# that runs past the end of it). Travel dates are often further away than that, so
# anything beyond the horizon falls back to an average of the same calendar date over
# the last few years ("seasonal normals").
FORECAST_HORIZON_DAYS = 14
SEASONAL_LOOKBACK_YEARS = 3

FORECAST_DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,snowfall_sum"
)
ARCHIVE_DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "wind_speed_10m_max,wind_gusts_10m_max,snowfall_sum"
)

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

THUNDERSTORM_CODES = {95, 96, 99}
FREEZING_CODES = {56, 57, 66, 67}

SEVERITY_ORDER = {"none": 0, "low": 1, "moderate": 2, "high": 3}


class WeatherLookupError(Exception):
    """Raised when a city can't be geocoded or the forecast can't be fetched."""


@lru_cache(maxsize=256)
def geocode_city(city: str) -> dict:
    """Resolve a city name to a location dict (name, country, latitude, longitude).

    Cached, because both the weather agent and the flight fallback ask for the same
    handful of cities on every request.
    """
    response = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results")
    if not results:
        raise WeatherLookupError(f"Could not find a location named '{city}'.")

    location = results[0]
    return {
        "name": location.get("name", city),
        "country": location.get("country", ""),
        "country_code": location.get("country_code", ""),
        "admin1": location.get("admin1", ""),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
    }


def get_weather(city: str) -> dict:
    """Look up the *current* weather for a city name.

    Returns a dict with city, country, temperature_c, feels_like_c, humidity,
    wind_speed_kmh, and condition. Raises WeatherLookupError on failure.
    """
    location = geocode_city(city)

    forecast_resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
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

    return {
        "city": location["name"],
        "country": location["country"],
        "admin1": location["admin1"],
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "condition": WEATHER_CODES.get(current.get("weather_code"), "Unknown"),
    }


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WeatherLookupError(f"'{value}' is not a valid date. Use YYYY-MM-DD.") from exc


def _fetch_daily(
    url: str, location: dict, start: dt.date, end: dt.date, fields: str
) -> dict:
    response = requests.get(
        url,
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": fields,
            "timezone": "auto",
        },
        timeout=15,
    )
    response.raise_for_status()
    daily = response.json().get("daily")
    if not daily or not daily.get("time"):
        raise WeatherLookupError("No daily weather data returned.")
    return daily


def _same_day_other_year(date: dt.date, year: int) -> dt.date:
    try:
        return date.replace(year=year)
    except ValueError:  # 29 Feb in a non-leap year
        return date.replace(year=year, day=28)


def _seasonal_normals(location: dict, date: dt.date) -> dict:
    """Average the same calendar date over the last few years, as a stand-in forecast."""
    # The archive lags a few days behind today, so start from the last complete year.
    latest_year = dt.date.today().year - 1
    samples: list[dict] = []

    for year in range(latest_year, latest_year - SEASONAL_LOOKBACK_YEARS, -1):
        day = _same_day_other_year(date, year)
        try:
            daily = _fetch_daily(ARCHIVE_URL, location, day, day, ARCHIVE_DAILY_FIELDS)
        except (requests.RequestException, WeatherLookupError):
            continue
        samples.append({key: values[0] for key, values in daily.items() if key != "time"})

    if not samples:
        raise WeatherLookupError(
            "That date is too far out for a forecast and no historical data is available."
        )

    def average(field: str):
        values = [s.get(field) for s in samples if s.get(field) is not None]
        return round(sum(values) / len(values), 1) if values else None

    codes = [s.get("weather_code") for s in samples if s.get("weather_code") is not None]

    return {
        "weather_code": max(set(codes), key=codes.count) if codes else None,
        "temperature_2m_max": average("temperature_2m_max"),
        "temperature_2m_min": average("temperature_2m_min"),
        "precipitation_sum": average("precipitation_sum"),
        "precipitation_probability_max": None,
        "wind_speed_10m_max": average("wind_speed_10m_max"),
        "wind_gusts_10m_max": average("wind_gusts_10m_max"),
        "snowfall_sum": average("snowfall_sum"),
        "_years": len(samples),
    }


def _warnings_for(day: dict) -> list[dict]:
    """Turn a day's numbers into traveller-facing warnings."""
    warnings: list[dict] = []

    def add(kind: str, severity: str, message: str) -> None:
        warnings.append({"type": kind, "severity": severity, "message": message})

    code = day.get("weather_code")
    rain = day.get("precipitation_sum") or 0
    rain_chance = day.get("precipitation_probability_max")
    gusts = day.get("wind_gusts_10m_max") or 0
    wind = day.get("wind_speed_10m_max") or 0
    snow = day.get("snowfall_sum") or 0
    temp_max = day.get("temperature_2m_max")
    temp_min = day.get("temperature_2m_min")

    if code in THUNDERSTORM_CODES:
        add("thunderstorm", "high", "Thunderstorms expected - flight delays are likely.")
    if code in FREEZING_CODES:
        add("freezing_rain", "high", "Freezing rain expected - expect de-icing delays.")
    if code in (45, 48):
        add("fog", "moderate", "Fog expected - low visibility can delay departures.")

    if rain >= 30:
        add("rain", "high", f"Very heavy rain expected ({rain:.0f} mm).")
    elif rain >= 10:
        add("rain", "moderate", f"Heavy rain expected ({rain:.0f} mm).")
    elif rain_chance is not None and rain_chance >= 70:
        add("rain", "low", f"{rain_chance:.0f}% chance of rain - pack a jacket.")

    if snow >= 5:
        add("snow", "high", f"Heavy snowfall expected ({snow:.0f} cm).")
    elif snow >= 0.5:
        add("snow", "moderate", f"Snowfall expected ({snow:.1f} cm).")
    elif snow > 0:
        add("snow", "low", f"A little snow possible ({snow:.1f} cm).")

    if gusts >= 90:
        add("wind", "high", f"Damaging wind gusts up to {gusts:.0f} km/h.")
    elif gusts >= 60:
        add("wind", "moderate", f"Strong wind gusts up to {gusts:.0f} km/h.")
    elif wind >= 45:
        add("wind", "low", f"Windy, up to {wind:.0f} km/h.")

    if temp_max is not None:
        if temp_max >= 38:
            add("heat", "high", f"Extreme heat, up to {temp_max:.0f}C.")
        elif temp_max >= 33:
            add("heat", "moderate", f"Very warm, up to {temp_max:.0f}C.")

    if temp_min is not None:
        if temp_min <= -10:
            add("cold", "high", f"Extreme cold, down to {temp_min:.0f}C.")
        elif temp_min <= 0:
            add("cold", "moderate", f"Freezing conditions, down to {temp_min:.0f}C.")

    return warnings


def get_daily_weather(city: str, date: str) -> dict:
    """Weather outlook for a city on a specific date, with traveller warnings.

    Uses the daily forecast when the date is inside Open-Meteo's ~16-day horizon, and
    falls back to an average of recent years for dates beyond it.
    """
    target = _parse_date(date)
    location = geocode_city(city)
    days_out = (target - dt.date.today()).days

    day = None
    if -1 <= days_out <= FORECAST_HORIZON_DAYS:
        try:
            daily = _fetch_daily(FORECAST_URL, location, target, target, FORECAST_DAILY_FIELDS)
            day = {key: values[0] for key, values in daily.items() if key != "time"}
            source = "forecast"
            note = None
        except (requests.RequestException, WeatherLookupError):
            # The exact end of the forecast window moves around; fall through to
            # seasonal normals rather than failing the whole lookup.
            day = None

    if day is None:
        day = _seasonal_normals(location, target)
        years = day.pop("_years")
        source = "seasonal_normals"
        note = (
            f"{date} is outside the forecast window, so these are averages of the same "
            f"date over the last {years} year(s), not a forecast."
        )

    warnings = _warnings_for(day)
    severity = max(
        (w["severity"] for w in warnings),
        key=lambda s: SEVERITY_ORDER[s],
        default="none",
    )

    return {
        "city": location["name"],
        "country": location["country"],
        "date": date,
        "source": source,
        "note": note,
        "condition": WEATHER_CODES.get(day.get("weather_code"), "Unknown"),
        "temp_max_c": day.get("temperature_2m_max"),
        "temp_min_c": day.get("temperature_2m_min"),
        "precipitation_mm": day.get("precipitation_sum"),
        "precipitation_probability_pct": day.get("precipitation_probability_max"),
        "wind_max_kmh": day.get("wind_speed_10m_max"),
        "wind_gust_kmh": day.get("wind_gusts_10m_max"),
        "snowfall_cm": day.get("snowfall_sum"),
        "severity": severity,
        "warnings": warnings,
    }
