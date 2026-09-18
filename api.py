"""FastAPI backend exposing the multi-agent trip planner to the React frontend."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trip_agents import flight_data_source, plan_trip

load_dotenv()

app = FastAPI(title="Trip Planner Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TripRequest(BaseModel):
    origin: str
    destination: str
    depart_date: str
    return_date: str | None = None


class TripResponse(BaseModel):
    summary: str
    flights: dict[str, Any] | None = None
    flights_error: str | None = None
    weather: list[dict[str, Any]] = []
    weather_error: str | None = None
    agents: list[dict[str, Any]] = []
    flight_source: str


def _valid_date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{label} must be a date in YYYY-MM-DD format."
        ) from exc


@app.get("/api/config")
def config() -> dict:
    """Lets the UI say up front whether fares are real or estimated."""
    return {"flight_source": flight_data_source()}


@app.post("/api/trip", response_model=TripResponse)
async def trip(request: TripRequest) -> TripResponse:
    origin = request.origin.strip()
    destination = request.destination.strip()
    return_date = (request.return_date or "").strip() or None

    if not origin or not destination:
        raise HTTPException(status_code=400, detail="Enter both a start and a destination city.")
    if origin.lower() == destination.lower():
        raise HTTPException(
            status_code=400, detail="The start and destination cities are the same."
        )

    depart = _valid_date(request.depart_date, "Travel date")
    if depart < dt.date.today():
        raise HTTPException(status_code=400, detail="The travel date is in the past.")

    if return_date:
        if _valid_date(return_date, "Return date") < depart:
            raise HTTPException(
                status_code=400, detail="The return date is before the travel date."
            )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500, detail="ANTHROPIC_API_KEY is not set on the server."
        )

    try:
        result = await plan_trip(
            origin=origin,
            destination=destination,
            depart_date=request.depart_date,
            return_date=return_date,
            api_key=api_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Something went wrong: {exc}") from exc

    return TripResponse(**result, flight_source=flight_data_source())
