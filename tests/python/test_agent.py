"""Tests for the generic tool-use loop, driven by a scripted fake Claude client."""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import agent
from agent import AgentResult, run_agent


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(id_, name, **input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def reply(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class FakeClient:
    """Returns scripted responses in order and records every request it received."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        # Snapshot the message list; the loop keeps mutating it.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


def run(client, tool_impls=None, tools=None, **kwargs):
    return asyncio.run(
        run_agent(
            name="t",
            client=client,
            system="sys",
            user_message="hi",
            tools=tools if tools is not None else [{"name": "echo"}],
            tool_impls=tool_impls or {},
            **kwargs,
        )
    )


class TestPlainReply:
    def test_returns_text_without_calling_tools(self):
        result = run(FakeClient(reply(text("hello "), text("world"))))
        assert result.text == "hello world"
        assert result.tool_calls == []
        assert result.error is None

    def test_text_is_stripped(self):
        assert run(FakeClient(reply(text("  padded \n")))).text == "padded"

    def test_ignores_non_text_blocks(self):
        thinking = SimpleNamespace(type="thinking", thinking="...")
        assert run(FakeClient(reply(thinking, text("answer")))).text == "answer"

    def test_request_carries_model_system_and_effort(self):
        client = FakeClient(reply(text("ok")))
        run(client, effort="medium")
        sent = client.requests[0]
        assert sent["model"] == agent.MODEL
        assert sent["system"] == "sys"
        assert sent["output_config"] == {"effort": "medium"}
        assert sent["thinking"] == {"type": "adaptive"}

    def test_no_tools_key_when_tool_list_is_empty(self):
        client = FakeClient(reply(text("ok")))
        run(client, tools=[])
        assert "tools" not in client.requests[0]


class TestToolLoop:
    def test_runs_tool_then_returns_final_text(self):
        client = FakeClient(
            reply(tool_use("a", "echo", value="x"), stop="tool_use"),
            reply(text("done")),
        )
        result = run(client, {"echo": lambda value: {"echoed": value}})
        assert result.text == "done"
        assert result.tool_calls == [
            {"name": "echo", "input": {"value": "x"}, "result": {"echoed": "x"}, "is_error": False}
        ]

    def test_tool_result_is_sent_back_as_tool_result_block(self):
        client = FakeClient(
            reply(tool_use("abc", "echo", value="x"), stop="tool_use"),
            reply(text("done")),
        )
        run(client, {"echo": lambda value: {"echoed": value}})
        second = client.requests[1]["messages"]
        assert second[-1]["role"] == "user"
        block = second[-1]["content"][0]
        assert block["type"] == "tool_result" and block["tool_use_id"] == "abc"
        assert json.loads(block["content"]) == {"echoed": "x"}
        assert block["is_error"] is False
        # The assistant turn (with the tool_use) precedes it, unchanged.
        assert second[-2]["role"] == "assistant"

    def test_multiple_tool_calls_return_in_a_single_user_message(self):
        client = FakeClient(
            reply(tool_use("1", "echo", value="a"), tool_use("2", "echo", value="b"), stop="tool_use"),
            reply(text("done")),
        )
        run(client, {"echo": lambda value: value})
        last = client.requests[1]["messages"][-1]
        assert [b["tool_use_id"] for b in last["content"]] == ["1", "2"]

    def test_tool_exception_becomes_error_result_not_a_crash(self):
        def boom(value):
            raise ValueError("bad city")

        client = FakeClient(reply(tool_use("1", "echo", value="x"), stop="tool_use"), reply(text("sorry")))
        result = run(client, {"echo": boom})
        assert result.text == "sorry"
        assert result.tool_calls[0]["is_error"] is True
        assert "ValueError: bad city" in result.tool_calls[0]["result"]["error"]
        sent = client.requests[1]["messages"][-1]["content"][0]
        assert sent["is_error"] is True

    def test_unknown_tool_is_reported_as_error(self):
        client = FakeClient(reply(tool_use("1", "nope"), stop="tool_use"), reply(text("ok")))
        result = run(client, {})
        assert result.tool_calls[0]["is_error"] is True
        assert "Unknown tool" in result.tool_calls[0]["result"]["error"]

    def test_gives_up_after_max_turns(self):
        looping = [reply(tool_use(str(i), "echo", value="x"), stop="tool_use") for i in range(10)]
        result = run(FakeClient(*looping), {"echo": lambda value: value}, max_turns=3)
        assert result.text == ""
        assert "did not finish within 3 turns" in result.error
        assert len(result.tool_calls) == 3

    def test_parallel_tool_calls_actually_run_concurrently(self):
        seen = set()

        def slow(value):
            seen.add(threading.current_thread().name)
            time.sleep(0.3)
            return value

        client = FakeClient(
            reply(tool_use("1", "echo", value="a"), tool_use("2", "echo", value="b"), stop="tool_use"),
            reply(text("done")),
        )
        started = time.perf_counter()
        run(client, {"echo": slow})
        assert time.perf_counter() - started < 0.55, "two 0.3s tools should overlap"


class TestAgentResult:
    def test_first_result_skips_errors(self):
        result = AgentResult(
            name="x",
            text="",
            tool_calls=[
                {"name": "t", "input": {}, "result": {"error": "boom"}, "is_error": True},
                {"name": "t", "input": {}, "result": {"ok": 1}, "is_error": False},
            ],
        )
        assert result.first_result("t") == {"ok": 1}

    def test_first_result_none_when_absent(self):
        assert AgentResult(name="x", text="").first_result("t") is None
