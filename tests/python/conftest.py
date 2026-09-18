"""Shared fixtures. No test in this folder touches the network or the Anthropic API."""

import sys
from pathlib import Path

import pytest

# Make the project root importable (api.py, flight_tool.py, ... live there).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def no_amadeus(monkeypatch):
    """Default every test to the estimated-fares backend, whatever is in the real .env."""
    monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMADEUS_CLIENT_SECRET", raising=False)


@pytest.fixture
def fake_geocode(monkeypatch):
    """Replace geocoding with a small fixed table so distances are predictable."""
    import flight_tool
    import weather_tool

    cities = {
        "london": {"name": "London", "country": "UK", "country_code": "GB", "admin1": "", "latitude": 51.5074, "longitude": -0.1278},
        "paris": {"name": "Paris", "country": "France", "country_code": "FR", "admin1": "", "latitude": 48.8566, "longitude": 2.3522},
        "tokyo": {"name": "Tokyo", "country": "Japan", "country_code": "JP", "admin1": "", "latitude": 35.6895, "longitude": 139.6917},
        "chennai": {"name": "Chennai", "country": "India", "country_code": "IN", "admin1": "", "latitude": 13.0827, "longitude": 80.2707},
        "versailles": {"name": "Versailles", "country": "France", "country_code": "FR", "admin1": "", "latitude": 48.8049, "longitude": 2.1204},
    }

    def fake(city):
        try:
            return cities[city.strip().lower()]
        except KeyError:
            raise weather_tool.WeatherLookupError(f"Could not find a location named '{city}'.")

    monkeypatch.setattr(weather_tool, "geocode_city", fake)
    monkeypatch.setattr(flight_tool, "geocode_city", fake)
    return fake
