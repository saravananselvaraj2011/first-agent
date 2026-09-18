# first-agent

A small multi-agent Claude app that plans a trip: you give it a start city, a
destination, a travel date and an optional return date, and it comes back with flights
sorted cheapest-first plus a weather warning for the destination on that date.

Three Claude agents are involved. A **flight agent** and a **weather agent** run in
parallel, each with its own tool, and a **planner agent** waits for both and writes the
combined briefing.

- Weather comes from the free [Open-Meteo](https://open-meteo.com/) API — no key needed.
- Flights come from the [Amadeus Self-Service](https://developers.amadeus.com) API when
  `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` are set. **Without those credentials the
  fares are estimated**, not real: they are derived deterministically from the real
  great-circle distance between the two cities, and are labelled as estimates in the API
  response and in the UI. There is no key-free flight API the way Open-Meteo is key-free
  for weather.

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

Open the printed Vite URL (usually http://localhost:5173), fill in the two cities and
the dates, and submit.

## Files

- `api.py` — FastAPI backend: `POST /api/trip`, `GET /api/config`
- `trip_agents.py` — the flight, weather and planner agents, and the parallel run
- `agent.py` — the generic Claude tool-calling loop the agents share
- `flight_tool.py` — `search_flights(...)`, Amadeus or estimated, cheapest first
- `weather_tool.py` — `get_daily_weather(city, date)` with traveller warnings
- `frontend/` — React (Vite) UI

## Checking the tools without the LLM

```bash
python -c "from flight_tool import search_flights; print(search_flights('London','Paris','2026-12-20'))"
python -c "from weather_tool import get_daily_weather; print(get_daily_weather('Reykjavik','2026-12-20'))"
```
