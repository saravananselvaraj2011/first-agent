"""The Claude tool-calling loop shared by every agent in this app.

`run_agent` is deliberately generic: it takes a system prompt, a list of tool schemas
and a mapping of tool name -> Python callable, and drives the request/tool/respond loop
until Claude returns plain text. `trip_agents.py` builds the individual agents on top
of it; nothing here knows about flights, weather, or FastAPI.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

MODEL = "claude-opus-5"
MAX_TOKENS = 8000
MAX_TURNS = 6


@dataclass
class AgentResult:
    """What an agent produced: its final prose, plus the raw tool output it saw."""

    name: str
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    error: str | None = None

    def first_result(self, tool_name: str) -> Any | None:
        """The result of the first successful call to `tool_name`, if there was one."""
        for call in self.tool_calls:
            if call["name"] == tool_name and not call["is_error"]:
                return call["result"]
        return None


async def run_agent(
    *,
    name: str,
    client: anthropic.AsyncAnthropic,
    system: str,
    user_message: str,
    tools: list[dict],
    tool_impls: dict[str, Callable[..., Any]],
    effort: str = "low",
    max_turns: int = MAX_TURNS,
) -> AgentResult:
    """Run one agent to completion and return its text plus every tool result."""
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tool_calls: list[dict] = []

    for _ in range(max_turns):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=messages,
            **({"tools": tools} if tools else {}),
        )

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            return AgentResult(name=name, text=text.strip(), tool_calls=tool_calls)

        # Thinking and tool_use blocks have to go back unchanged, so append the
        # whole content list rather than just the text.
        messages.append({"role": "assistant", "content": response.content})

        requests = [block for block in response.content if block.type == "tool_use"]
        results = await asyncio.gather(
            *(_run_tool(block, tool_impls) for block in requests)
        )

        tool_results = []
        for block, (payload, is_error) in zip(requests, results):
            tool_calls.append(
                {
                    "name": block.name,
                    "input": block.input,
                    "result": payload,
                    "is_error": is_error,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(payload, default=str),
                    "is_error": is_error,
                }
            )

        # All tool_result blocks for one turn must arrive in a single user message.
        messages.append({"role": "user", "content": tool_results})

    return AgentResult(
        name=name,
        text="",
        tool_calls=tool_calls,
        error=f"The {name} agent did not finish within {max_turns} turns.",
    )


async def _run_tool(block: Any, tool_impls: dict[str, Callable[..., Any]]) -> tuple[Any, bool]:
    """Execute one tool_use block. Returns (payload, is_error).

    Tool failures come back to Claude as tool results rather than exceptions, so it can
    react to them (ask about a spelling, try the other city, explain what's missing).
    """
    impl = tool_impls.get(block.name)
    if impl is None:
        return {"error": f"Unknown tool '{block.name}'"}, True

    try:
        # The tools are blocking `requests` calls; keep the event loop free so the
        # agents really do run side by side.
        return await asyncio.to_thread(impl, **block.input), False
    except Exception as exc:  # surfaced to the model, not raised
        return {"error": f"{type(exc).__name__}: {exc}"}, True
