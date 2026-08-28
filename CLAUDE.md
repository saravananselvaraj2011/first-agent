# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A minimal Claude tool-calling agent that looks up current weather for a city entered
through a Streamlit UI. The agent uses Claude's tool-use loop to invoke a `get_weather`
tool backed by the free Open-Meteo API (no API key needed for weather data itself, but
`ANTHROPIC_API_KEY` is required to run the agent).

## Commands

```bash
pip install -r requirements.txt      # install dependencies
cp .env.example .env                 # then edit .env and set ANTHROPIC_API_KEY
python -m streamlit run app.py       # run the app (use python -m; `streamlit` may not be on PATH)
```

No test suite, linter, or build step is configured.

To sanity-check the weather lookup alone, without the LLM or UI:

```bash
python -c "from weather_tool import get_weather; print(get_weather('London'))"
```

## Architecture

Three-module pipeline, each with a single responsibility:

- **`weather_tool.py`** — `get_weather(city)`. Two-step Open-Meteo call: geocode the
  city name to lat/lon, then fetch current conditions. Raises `WeatherLookupError` on
  an unresolvable city; this is caught in `agent.py` and turned into a tool result the
  model can react to (e.g. ask the user to check spelling), not an exception.
- **`agent.py`** — `ask_weather_agent(user_message, api_key)`. Owns the Claude
  tool-use loop: sends the message with the `get_weather` tool schema, and if
  `stop_reason == "tool_use"`, runs the tool via `_run_tool` and feeds the result back
  as a `tool_result` message, looping until Claude returns plain text. Model id is
  pinned in the `MODEL` constant.
- **`app.py`** — Streamlit form UI. Reads `ANTHROPIC_API_KEY` from the environment
  (via `python-dotenv` loading `.env`), warns if missing, and calls
  `ask_weather_agent` on submit.

`weather_tool.py` has no dependency on `agent.py`/`app.py` and can be tested or reused
standalone. `agent.py` has no Streamlit dependency and could be driven from a CLI or
tests without the UI.
