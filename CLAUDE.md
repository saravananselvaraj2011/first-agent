# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A minimal Claude tool-calling agent that looks up current weather for a city, served
through a FastAPI backend and a React (Vite) frontend. The agent uses Claude's tool-use
loop to invoke a `get_weather` tool backed by the free Open-Meteo API (no API key needed
for weather data itself, but `ANTHROPIC_API_KEY` is required to run the agent).

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

No test suite, linter, or build step is configured beyond `npm run build` for a
production frontend bundle.

To sanity-check the weather lookup alone, without the LLM, API, or UI:

```bash
python -c "from weather_tool import get_weather; print(get_weather('London'))"
```

## Architecture

Backend (Python) and frontend (React) are separate processes talking over HTTP.

- **`weather_tool.py`** — `get_weather(city)`. Two-step Open-Meteo call: geocode the
  city name to lat/lon, then fetch current conditions. Raises `WeatherLookupError` on
  an unresolvable city; this is caught in `agent.py` and turned into a tool result the
  model can react to (e.g. ask the user to check spelling), not an exception.
- **`agent.py`** — `ask_weather_agent(user_message, api_key)`. Owns the Claude
  tool-use loop: sends the message with the `get_weather` tool schema, and if
  `stop_reason == "tool_use"`, runs the tool via `_run_tool` and feeds the result back
  as a `tool_result` message, looping until Claude returns plain text. Model id is
  pinned in the `MODEL` constant.
- **`api.py`** — FastAPI app exposing `POST /api/weather` (body: `{"city": "..."}`,
  response: `{"reply": "..."}`). Loads `ANTHROPIC_API_KEY` from the environment (via
  `python-dotenv` loading `.env`), builds the user prompt, calls `ask_weather_agent`,
  and maps failures (missing API key, empty city, agent/tool errors) to HTTP error
  responses. CORS is enabled for the Vite dev origins (`localhost:5173`).
- **`frontend/`** — Vite + React UI. `src/App.jsx` holds a form with a city input;
  on submit it `fetch`es `POST /api/weather` and renders the reply or error. No other
  state or routing.

`weather_tool.py` has no dependency on `agent.py`/`api.py` and can be tested or reused
standalone. `agent.py` has no FastAPI dependency and could be driven from a CLI or
tests without the API layer.
