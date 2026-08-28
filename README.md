# first-agent

A small Claude agent that looks up the current weather for a city you type into a Streamlit UI.

The agent uses Claude's tool-calling to invoke a `get_weather` tool backed by the free
[Open-Meteo](https://open-meteo.com/) API (no API key needed for weather data).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY
```

## Run

```bash
streamlit run app.py
```

Enter a city name in the UI and submit — the agent calls the weather tool and replies
with a short summary.

## Files

- `app.py` — Streamlit UI
- `agent.py` — Claude tool-calling loop
- `weather_tool.py` — `get_weather(city)`, backed by Open-Meteo's geocoding + forecast APIs
