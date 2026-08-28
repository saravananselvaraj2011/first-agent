"""Streamlit UI: type a city, ask the Claude weather agent about it."""

import os

import streamlit as st
from dotenv import load_dotenv

from agent import ask_weather_agent

load_dotenv()

st.set_page_config(page_title="Weather Agent", page_icon="⛅")
st.title("⛅ Weather Agent")
st.caption("Enter a city and Claude will call a weather tool to look it up.")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    st.warning(
        "No ANTHROPIC_API_KEY found. Set it in a .env file or as an environment "
        "variable before asking the agent."
    )

with st.form("weather_form"):
    city = st.text_input("City", placeholder="e.g. Tokyo")
    submitted = st.form_submit_button("Get weather")

if submitted:
    if not city.strip():
        st.error("Please enter a city name.")
    elif not api_key:
        st.error("Cannot call the agent without ANTHROPIC_API_KEY set.")
    else:
        with st.spinner(f"Asking the agent about {city}..."):
            try:
                reply = ask_weather_agent(f"What's the weather like in {city}?", api_key=api_key)
                st.success(reply)
            except Exception as exc:  # noqa: BLE001 - surface any API/tool error to the UI
                st.error(f"Something went wrong: {exc}")
