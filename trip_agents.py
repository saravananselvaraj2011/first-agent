"""The three agents behind a trip lookup.

A flight agent and a weather agent run **in parallel** (`asyncio.gather`) over the same
trip, each with its own tool and its own system prompt. A third agent - the planner -
waits for both and writes the combined briefing. Splitting them this way keeps each
agent's context small and halves the wall-clock time, since the two tool lookups are
independent.
"""

from __future__ import annotations

import asyncio

import anthropic

from agent import AgentResult, run_agent
from flight_tool import FlightSearchError, amadeus_configured, search_flights
from weather_tool import get_daily_weather

SEARCH_FLIGHTS_TOOL = {
    "name": "search_flights",
    "description": (
        "Search for flights between two cities on a given date, returning offers sorted "
        "cheapest first. Pass return_date only for a round trip."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Departure city, e.g. 'London'."},
            "destination": {"type": "string", "description": "Arrival city, e.g. 'Paris'."},
            "depart_date": {"type": "string", "description": "Travel date as YYYY-MM-DD."},
            "return_date": {
                "type": "string",
                "description": "Optional return date as YYYY-MM-DD. Omit for a one-way trip.",
            },
        },
        "required": ["origin", "destination", "depart_date"],
        "additionalProperties": False,
    },
}

GET_DAILY_WEATHER_TOOL = {
    "name": "get_daily_weather",
    "description": (
        "Get the weather outlook for a city on a specific date, including any traveller "
        "warnings (storms, heavy rain, snow, wind, heat, cold, fog)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "The city to check, e.g. 'Tokyo'."},
            "date": {"type": "string", "description": "The date to check as YYYY-MM-DD."},
        },
        "required": ["city", "date"],
        "additionalProperties": False,
    },
}

FLIGHT_SYSTEM = (
    "You are a flight search agent. Call the search_flights tool exactly once with the "
    "trip the user describes, then summarise the results in at most four short sentences: "
    "lead with the cheapest option (airline, price, stops, duration), mention how it "
    "compares with the next cheapest, and note anything a traveller would care about such "
    "as a long layover or a very early departure. Do not invent flights or prices - only "
    "report what the tool returned. If the tool reports an error, say plainly what went "
    "wrong and what the user should change. If the results are marked as estimated, say so "
    "in one clause."
)

WEATHER_SYSTEM = (
    "You are a travel weather agent. Use the get_daily_weather tool to check the "
    "destination city on the travel date, and also on the return date when one is given. "
    "Then write at most three short sentences for the traveller: the expected conditions, "
    "then any warnings and what they mean in practice (delays, what to pack). If there are "
    "no warnings, say conditions look fine. If the data is seasonal rather than a real "
    "forecast, say so. Do not invent conditions - only report what the tool returned."
)

PLANNER_SYSTEM = (
    "You are a trip planner writing a short briefing from two specialist reports - one on "
    "flights, one on weather. Write 2-4 sentences in plain prose, no headings and no "
    "bullet points: recommend the cheapest sensible flight, then tie in the destination "
    "weather warning and its practical consequence. Only use facts from the two reports. "
    "If one report failed, write the briefing from the other and say in one clause what is "
    "missing."
)


def _trip_description(
    origin: str, destination: str, depart_date: str, return_date: str | None
) -> str:
    trip = f"from {origin} to {destination}, departing {depart_date}"
    trip += f", returning {return_date}" if return_date else " (one way, no return date)"
    return trip


async def plan_trip(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Run the flight and weather agents in parallel, then have the planner combine them."""
    client = anthropic.AsyncAnthropic(api_key=api_key)
    trip = _trip_description(origin, destination, depart_date, return_date)

    flight_task = run_agent(
        name="flights",
        client=client,
        system=FLIGHT_SYSTEM,
        user_message=f"Find flights {trip}. Show the cheapest options first.",
        tools=[SEARCH_FLIGHTS_TOOL],
        tool_impls={"search_flights": search_flights},
    )
    weather_task = run_agent(
        name="weather",
        client=client,
        system=WEATHER_SYSTEM,
        user_message=(
            f"I am travelling {trip}. What is the weather outlook in {destination}, and is "
            "there anything I should be warned about?"
        ),
        tools=[GET_DAILY_WEATHER_TOOL],
        tool_impls={"get_daily_weather": get_daily_weather},
    )

    # The two agents are independent, so they run side by side.
    flights, weather = await asyncio.gather(flight_task, weather_task)

    summary = await _write_briefing(client, trip, flights, weather)

    return {
        "summary": summary,
        "flights": _flight_payload(flights),
        "flights_error": _agent_error(flights, "search_flights"),
        "weather": _weather_payload(weather),
        "weather_error": _agent_error(weather, "get_daily_weather"),
        "agents": [
            {"name": result.name, "text": result.text, "error": result.error}
            for result in (flights, weather)
        ],
    }


async def _write_briefing(
    client: anthropic.AsyncAnthropic, trip: str, flights: AgentResult, weather: AgentResult
) -> str:
    """The planner agent: no tools, just the two specialist reports."""
    report = (
        f"Trip: {trip}\n\n"
        f"Flight agent report:\n{flights.text or flights.error or 'No flight report.'}\n\n"
        f"Weather agent report:\n{weather.text or weather.error or 'No weather report.'}"
    )
    result = await run_agent(
        name="planner",
        client=client,
        system=PLANNER_SYSTEM,
        user_message=report,
        tools=[],
        tool_impls={},
        max_turns=1,
    )
    return result.text or f"{flights.text}\n\n{weather.text}".strip()


def _flight_payload(result: AgentResult) -> dict | None:
    payload = result.first_result("search_flights")
    return payload if isinstance(payload, dict) and payload.get("offers") else None


def _weather_payload(result: AgentResult) -> list[dict]:
    """Every successful weather lookup, in the order the agent made them."""
    return [
        call["result"]
        for call in result.tool_calls
        if call["name"] == "get_daily_weather"
        and not call["is_error"]
        and isinstance(call["result"], dict)
    ]


def _agent_error(result: AgentResult, tool_name: str) -> str | None:
    """The first tool error the agent hit, if it never got a usable result."""
    if result.error:
        return result.error
    for call in result.tool_calls:
        if call["name"] == tool_name and call["is_error"]:
            error = call["result"]
            return error.get("error") if isinstance(error, dict) else str(error)
    return None


def flight_data_source() -> str:
    """Whether real fares are configured, for the UI to label results honestly."""
    return "amadeus" if amadeus_configured() else "estimated"


__all__ = ["plan_trip", "flight_data_source", "FlightSearchError"]
