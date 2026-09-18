# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-agent Claude trip planner, served through a FastAPI backend and a React (Vite)
frontend. Given a start city, a destination, a travel date and an optional return date,
it returns flight offers sorted cheapest-first and a weather warning for the destination
on the travel date. `ANTHROPIC_API_KEY` is required to run the agents.

Three agents are involved: a **flight agent** and a **weather agent** run in parallel
(`asyncio.gather`), each with its own tool, and a **planner agent** combines their two
reports into the final briefing.

## Commands

```bash
pip install -r requirements.txt      # install backend dependencies
cp .env.example .env                 # then edit .env and set ANTHROPIC_API_KEY
python -m uvicorn api:app --reload   # run the backend API on http://localhost:8000

cd frontend
npm install                          # install frontend dependencies
npm run dev                          # run the Vite dev server on http://localhost:5173
```

Run the backend and frontend in separate terminals; the Vite dev server proxies `/api`
requests to `http://localhost:8000` (see `frontend/vite.config.js`).

No linter is configured. `npm run build` makes a production frontend bundle.

## Tests

Python and UI tests live in separate folders and never touch the network or the
Anthropic API (Claude is replaced by a scripted fake, geocoding/weather/flights are
stubbed), so they are free and deterministic.

```bash
pip install pytest httpx             # test-only Python deps
python -m pytest                     # Python tests in tests/python/ (config: pytest.ini)

cd frontend
npm test                             # UI tests in frontend/tests/ (Vitest + Testing Library, jsdom)
```

- `tests/python/` — weather warning rules and forecast/seasonal fallback, flight ranking
  and Amadeus parsing, the tool-use loop, parallel agent orchestration, API validation.
- `frontend/tests/` — form labels and validation, request payload, result rendering
  (cheapest-first list, severity-coloured weather cards), partial failures, error states.

To sanity-check the two tools alone, without the LLM, API, or UI:

```bash
python -c "from flight_tool import search_flights; print(search_flights('London','Paris','2026-12-20'))"
python -c "from weather_tool import get_daily_weather; print(get_daily_weather('Reykjavik','2026-12-20'))"
```

## Flight data

There is no key-free flight API the way Open-Meteo is key-free for weather.
`flight_tool.py` calls the Amadeus Self-Service API when `AMADEUS_CLIENT_ID` and
`AMADEUS_CLIENT_SECRET` are set, and otherwise returns **estimated** offers: prices and
schedules generated deterministically (seeded on the search itself) from the real
great-circle distance between the two cities. Estimated results carry
`source: "estimated"` and a `disclaimer`, surfaced in the UI — keep that labelling
intact if you touch this code, so estimates are never mistaken for bookable fares.

## Architecture

Backend (Python) and frontend (React) are separate processes talking over HTTP.

- **`weather_tool.py`** — `geocode_city(city)`, `get_weather(city)` (current
  conditions), and `get_daily_weather(city, date)`, which returns the outlook for one
  date plus derived traveller `warnings` and an overall `severity`. Dates inside
  Open-Meteo's ~2-week forecast window use the daily forecast; anything beyond it (or a
  forecast request the API rejects) falls back to an average of the same calendar date
  over the last few years, flagged as `source: "seasonal_normals"`. Raises
  `WeatherLookupError` on an unresolvable city.
- **`flight_tool.py`** — `search_flights(origin, destination, depart_date, return_date)`.
  Returns a dict whose `offers` list is sorted by ascending price, each offer holding an
  `outbound` leg and an `inbound` leg (or `None` for a one-way). See "Flight data" above.
  Raises `FlightSearchError`.
- **`agent.py`** — `run_agent(...)`, the generic async Claude tool-use loop every agent
  shares: it sends the message with the given tool schemas, runs any requested tools
  concurrently via `asyncio.to_thread` (the tools are blocking `requests` calls), feeds
  the results back as `tool_result` blocks, and loops until Claude returns plain text.
  Tool exceptions become tool results with `is_error`, not raised exceptions, so the
  model can react to them. Returns an `AgentResult` carrying both the final text and
  every raw tool result, which is what the API renders as structured data. The model id
  is pinned in `MODEL`.
- **`trip_agents.py`** — the tool schemas and system prompts for the three agents, plus
  `plan_trip(...)`, which runs the flight and weather agents in parallel and then the
  planner. Knows nothing about FastAPI.
- **`api.py`** — FastAPI app exposing `POST /api/trip` (body: `origin`, `destination`,
  `depart_date`, optional `return_date`; response: `summary`, `flights`, `weather`,
  per-agent reports and errors) and `GET /api/config` (whether fares are real or
  estimated). Validates the cities and dates, loads `ANTHROPIC_API_KEY` via
  `python-dotenv`, and maps failures to HTTP errors. CORS is enabled for the Vite dev
  origins (`localhost:5173`).
- **`frontend/`** — Vite + React UI. `src/App.jsx` holds the two-city + two-date form and
  renders the briefing, a weather card per date (colour-coded by severity) and the
  ranked flight list. No other state or routing.

`weather_tool.py` and `flight_tool.py` have no dependency on the agent or API layers and
can be tested standalone; `flight_tool.py` imports `geocode_city` from `weather_tool.py`
for its distance estimate. `agent.py` and `trip_agents.py` have no FastAPI dependency and
could be driven from a CLI or tests without the API layer.
