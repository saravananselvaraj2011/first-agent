"""Flight search tool.

Uses the Amadeus Self-Service flight-offers API when `AMADEUS_CLIENT_ID` and
`AMADEUS_CLIENT_SECRET` are set. There is no key-free flight API the way Open-Meteo is
key-free for weather, so without those credentials the tool falls back to *estimated*
offers: plausible, deterministic prices and schedules derived from the real great-circle
distance between the two cities. Estimated results are labelled as such all the way
through to the UI so they are never mistaken for bookable fares.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import random
import re
import time

import requests

from weather_tool import WeatherLookupError, geocode_city

AMADEUS_BASE_URL = os.environ.get("AMADEUS_BASE_URL", "https://test.api.amadeus.com")
MAX_OFFERS = 8

# Carriers used by the estimator: code, name, price multiplier, and the longest route
# the carrier plausibly flies. Low-cost carriers come out cheaper but drop off the list
# on long haul, so a budget airline never shows up on an intercontinental route.
ESTIMATED_CARRIERS = [
    ("FR", "Ryanair", 0.62, 3000),
    ("U2", "easyJet", 0.68, 3500),
    ("W6", "Wizz Air", 0.66, 4000),
    ("AK", "AirAsia", 0.64, 4500),
    ("6E", "IndiGo", 0.70, 6000),
    ("AI", "Air India", 0.95, 16000),
    ("TK", "Turkish Airlines", 1.02, 16000),
    ("EK", "Emirates", 1.18, 16000),
    ("QR", "Qatar Airways", 1.15, 16000),
    ("LH", "Lufthansa", 1.10, 16000),
    ("AF", "Air France", 1.08, 16000),
    ("BA", "British Airways", 1.12, 16000),
    ("AA", "American Airlines", 1.05, 16000),
    ("SQ", "Singapore Airlines", 1.20, 16000),
]


class FlightSearchError(Exception):
    """Raised when a flight search can't be completed."""


# --------------------------------------------------------------------------- helpers


def _parse_date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise FlightSearchError(f"{label} '{value}' is not a valid date. Use YYYY-MM-DD.") from exc


def _format_minutes(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    return f"{hours}h {mins:02d}m"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


# ------------------------------------------------------------------- amadeus backend

_token_cache: dict = {"value": None, "expires_at": 0.0}


def amadeus_configured() -> bool:
    return bool(os.environ.get("AMADEUS_CLIENT_ID") and os.environ.get("AMADEUS_CLIENT_SECRET"))


def _amadeus_token() -> str:
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]

    response = requests.post(
        f"{AMADEUS_BASE_URL}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AMADEUS_CLIENT_ID"],
            "client_secret": os.environ["AMADEUS_CLIENT_SECRET"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if response.status_code != 200:
        raise FlightSearchError(f"Amadeus authentication failed ({response.status_code}).")

    payload = response.json()
    _token_cache["value"] = payload["access_token"]
    # Refresh a minute early so a request never races the expiry.
    _token_cache["expires_at"] = time.time() + payload.get("expires_in", 1799) - 60
    return _token_cache["value"]


def _amadeus_city_code(city: str) -> str:
    response = requests.get(
        f"{AMADEUS_BASE_URL}/v1/reference-data/locations",
        params={"subType": "CITY,AIRPORT", "keyword": city, "page[limit]": 5},
        headers={"Authorization": f"Bearer {_amadeus_token()}"},
        timeout=15,
    )
    if response.status_code != 200:
        raise FlightSearchError(f"Could not look up an airport code for '{city}'.")

    data = response.json().get("data") or []
    if not data:
        raise FlightSearchError(f"No airport or city code found for '{city}'.")
    return data[0]["iataCode"]


def _parse_iso_duration(value: str) -> int:
    """'PT12H35M' -> minutes."""
    match = re.match(r"^P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?$", value or "")
    if not match:
        return 0
    days, hours, minutes = (int(part) if part else 0 for part in match.groups())
    return days * 1440 + hours * 60 + minutes


def _amadeus_leg(itinerary: dict, carriers: dict) -> dict:
    segments = itinerary["segments"]
    first, last = segments[0], segments[-1]
    carrier_code = first["carrierCode"]
    departure = first["departure"]["at"]
    arrival = last["arrival"]["at"]
    return {
        "from": first["departure"]["iataCode"],
        "to": last["arrival"]["iataCode"],
        "date": departure[:10],
        "depart": departure[11:16],
        "arrive": arrival[11:16],
        "duration": _format_minutes(_parse_iso_duration(itinerary.get("duration", ""))),
        "stops": len(segments) - 1,
        "airline": carriers.get(carrier_code, carrier_code).title(),
        "flight_number": f"{carrier_code}{first['number']}",
    }


def _search_amadeus(
    origin: str, destination: str, depart_date: str, return_date: str | None, adults: int
) -> list[dict]:
    params = {
        "originLocationCode": _amadeus_city_code(origin),
        "destinationLocationCode": _amadeus_city_code(destination),
        "departureDate": depart_date,
        "adults": adults,
        "currencyCode": "USD",
        "max": MAX_OFFERS,
    }
    if return_date:
        params["returnDate"] = return_date

    response = requests.get(
        f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers",
        params=params,
        headers={"Authorization": f"Bearer {_amadeus_token()}"},
        timeout=25,
    )
    if response.status_code != 200:
        detail = ""
        try:
            errors = response.json().get("errors") or []
            detail = f" {errors[0].get('detail', '')}" if errors else ""
        except ValueError:
            pass
        raise FlightSearchError(f"Amadeus flight search failed ({response.status_code}).{detail}")

    payload = response.json()
    carriers = (payload.get("dictionaries") or {}).get("carriers", {})

    offers = []
    for index, offer in enumerate(payload.get("data") or [], start=1):
        itineraries = offer.get("itineraries") or []
        if not itineraries:
            continue
        outbound = _amadeus_leg(itineraries[0], carriers)
        inbound = _amadeus_leg(itineraries[1], carriers) if len(itineraries) > 1 else None
        offers.append(
            {
                "id": str(index),
                "price": round(float(offer["price"]["grandTotal"]), 2),
                "currency": offer["price"].get("currency", "USD"),
                "airline": outbound["airline"],
                "outbound": outbound,
                "inbound": inbound,
                "total_stops": outbound["stops"] + (inbound["stops"] if inbound else 0),
            }
        )
    return offers


# ----------------------------------------------------------------- estimated backend


def _estimated_leg(
    rng: random.Random,
    from_code: str,
    to_code: str,
    date: str,
    distance_km: float,
    carrier_code: str,
    airline: str,
    stops: int,
) -> dict:
    cruise_minutes = distance_km / 800 * 60 + 40
    layover_minutes = stops * rng.randint(55, 180)
    total_minutes = int(cruise_minutes + layover_minutes)

    depart = dt.datetime.combine(
        dt.date.fromisoformat(date), dt.time(rng.randint(5, 21), rng.choice([0, 10, 25, 40, 55]))
    )
    arrive = depart + dt.timedelta(minutes=total_minutes)

    return {
        "from": from_code,
        "to": to_code,
        "date": date,
        "depart": depart.strftime("%H:%M"),
        "arrive": arrive.strftime("%H:%M")
        + ("" if arrive.date() == depart.date() else f" (+{(arrive.date() - depart.date()).days}d)"),
        "duration": _format_minutes(total_minutes),
        "stops": stops,
        "airline": airline,
        "flight_number": f"{carrier_code}{rng.randint(100, 9899)}",
    }


def _pseudo_code(city: str) -> str:
    """A stable three-letter stand-in code for a city, for display only."""
    letters = [char for char in city.upper() if char.isalpha()]
    code = "".join(letters[:3])
    return code.ljust(3, "X")


def _search_estimated(
    origin: str, destination: str, depart_date: str, return_date: str | None, adults: int
) -> list[dict]:
    try:
        start = geocode_city(origin)
        end = geocode_city(destination)
    except WeatherLookupError as exc:
        raise FlightSearchError(str(exc)) from exc

    distance = _haversine_km(
        start["latitude"], start["longitude"], end["latitude"], end["longitude"]
    )
    if distance < 80:
        raise FlightSearchError(
            f"'{origin}' and '{destination}' are only {distance:.0f} km apart - "
            "there are no flights between them."
        )

    # Seeded on the search itself, so the same search always returns the same offers.
    rng = random.Random(f"{origin.lower()}|{destination.lower()}|{depart_date}|{return_date}")

    from_code = _pseudo_code(start["name"])
    to_code = _pseudo_code(end["name"])
    base_price = 38 + distance * 0.085

    eligible = [c for c in ESTIMATED_CARRIERS if distance <= c[3]] or ESTIMATED_CARRIERS
    carriers = rng.sample(eligible, k=min(6, len(eligible)))
    offers = []

    for index, (carrier_code, airline, multiplier, _range_km) in enumerate(carriers, start=1):
        # Long hauls rarely run non-stop on budget carriers.
        max_stops = 0 if distance < 1200 else (1 if distance < 6500 else 2)
        stops = rng.randint(0, max_stops)
        # Each stop knocks something off the fare; fewer stops cost more.
        price = base_price * multiplier * (1 - 0.11 * stops) * rng.uniform(0.88, 1.16)

        outbound = _estimated_leg(
            rng, from_code, to_code, depart_date, distance, carrier_code, airline, stops
        )
        inbound = None
        if return_date:
            return_stops = rng.randint(0, max_stops)
            inbound = _estimated_leg(
                rng, to_code, from_code, return_date, distance, carrier_code, airline, return_stops
            )
            # Return fares are cheaper than two one-ways.
            price *= 1.82

        offers.append(
            {
                "id": str(index),
                "price": round(price * adults, 2),
                "currency": "USD",
                "airline": airline,
                "outbound": outbound,
                "inbound": inbound,
                "total_stops": outbound["stops"] + (inbound["stops"] if inbound else 0),
            }
        )

    return offers


# ------------------------------------------------------------------------ public API


def search_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None = None,
    adults: int = 1,
) -> dict:
    """Search flights between two cities, cheapest first.

    Returns a dict with the search parameters, a `source` of "amadeus" or "estimated",
    and an `offers` list sorted by ascending total price.
    """
    origin = (origin or "").strip()
    destination = (destination or "").strip()
    if not origin or not destination:
        raise FlightSearchError("Both an origin and a destination city are required.")
    if origin.lower() == destination.lower():
        raise FlightSearchError("Origin and destination are the same city.")

    depart = _parse_date(depart_date, "Travel date")
    returning = _parse_date(return_date, "Return date") if return_date else None
    if returning and returning < depart:
        raise FlightSearchError("The return date is before the travel date.")

    if amadeus_configured():
        source = "amadeus"
        offers = _search_amadeus(origin, destination, depart_date, return_date, adults)
        if not offers:
            raise FlightSearchError(
                f"No flights found from {origin} to {destination} on {depart_date}."
            )
    else:
        source = "estimated"
        offers = _search_estimated(origin, destination, depart_date, return_date, adults)

    offers.sort(key=lambda offer: offer["price"])
    for rank, offer in enumerate(offers, start=1):
        offer["rank"] = rank

    return {
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date,
        "return_date": return_date,
        "trip_type": "round_trip" if return_date else "one_way",
        "adults": adults,
        "currency": offers[0]["currency"],
        "source": source,
        "disclaimer": (
            None
            if source == "amadeus"
            else "Estimated fares (no flight API key configured) - illustrative, not bookable."
        ),
        "offers": offers[:MAX_OFFERS],
    }
