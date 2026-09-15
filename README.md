# first-agent

A small Claude agent that looks up the current weather for a city, with a FastAPI
backend and a React (Vite) frontend.

The agent uses Claude's tool-calling to invoke a `get_weather` tool backed by the free
[Open-Meteo](https://open-meteo.com/) API (no API key needed for weather data).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY

cd frontend
npm install
```

## Run

In one terminal, start the backend API:

```bash
python -m uvicorn api:app --reload
```

In another terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open the printed Vite URL (usually http://localhost:5173), enter a city name, and
submit — the agent calls the weather tool and replies with a short summary.

## Files

- `api.py` — FastAPI backend exposing `POST /api/weather`
- `agent.py` — Claude tool-calling loop
- `weather_tool.py` — `get_weather(city)`, backed by Open-Meteo's geocoding + forecast APIs
- `frontend/` — React (Vite) UI
