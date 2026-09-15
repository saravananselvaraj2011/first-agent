"""FastAPI backend exposing the Claude weather agent to the React frontend."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import ask_weather_agent

load_dotenv()

app = FastAPI(title="Weather Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class WeatherRequest(BaseModel):
    city: str


class WeatherResponse(BaseModel):
    reply: str


@app.post("/api/weather", response_model=WeatherResponse)
def weather(request: WeatherRequest) -> WeatherResponse:
    city = request.city.strip()
    if not city:
        raise HTTPException(status_code=400, detail="Please enter a city name.")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500, detail="ANTHROPIC_API_KEY is not set on the server."
        )

    try:
        reply = ask_weather_agent(f"What's the weather like in {city}?", api_key=api_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Something went wrong: {exc}") from exc

    return WeatherResponse(reply=reply)
