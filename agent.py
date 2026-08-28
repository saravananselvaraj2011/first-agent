"""A small Claude tool-calling agent that answers weather questions for a city."""

import json
import os

import anthropic

from weather_tool import WeatherLookupError, get_weather

MODEL = "claude-sonnet-5"

WEATHER_TOOL = {
    "name": "get_weather",
    "description": (
        "Get the current weather (temperature, feels-like, humidity, wind, "
        "condition) for a given city name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "The city to get the weather for, e.g. 'Paris' or 'San Francisco, CA'.",
            }
        },
        "required": ["city"],
    },
}

SYSTEM_PROMPT = (
    "You are a helpful weather assistant. When the user asks about the weather "
    "for a city, use the get_weather tool to look it up, then answer in a short, "
    "friendly summary. If the tool reports the city couldn't be found, tell the "
    "user clearly and ask them to check the spelling."
)


def _run_tool(name: str, tool_input: dict) -> dict:
    if name != "get_weather":
        return {"error": f"Unknown tool '{name}'"}
    try:
        return get_weather(tool_input["city"])
    except WeatherLookupError as exc:
        return {"error": str(exc)}


def ask_weather_agent(user_message: str, api_key: str | None = None) -> str:
    """Send a message to the agent and return its final text reply.

    The agent may call the get_weather tool one or more times before
    producing a final answer.
    """
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[WEATHER_TOOL],
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return "".join(
                block.text for block in response.content if block.type == "text"
            )

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _run_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})
