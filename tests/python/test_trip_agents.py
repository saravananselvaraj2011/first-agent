"""Tests for the three-agent orchestration, with run_agent replaced by a stub."""

import asyncio
import time

import trip_agents
from agent import AgentResult


def call(tool, result, is_error=False):
    return {"name": tool, "input": {}, "result": result, "is_error": is_error}


FLIGHTS = {"offers": [{"rank": 1, "price": 100}], "disclaimer": "est"}
DAY = {"date": "2027-03-10", "severity": "moderate", "warnings": []}


def install_stub(monkeypatch, *, delay=0.0, overrides=None):
    """Stub run_agent; records call order and start/end times per agent."""
    log = {"starts": {}, "ends": {}, "messages": {}}
    overrides = overrides or {}

    async def fake(**kwargs):
        name = kwargs["name"]
        log["starts"][name] = time.perf_counter()
        log["messages"][name] = kwargs["user_message"]
        if name in ("flights", "weather"):
            await asyncio.sleep(delay)
        log["ends"][name] = time.perf_counter()
        if name in overrides:
            return overrides[name]
        if name == "flights":
            return AgentResult("flights", "Cheapest is X.", [call("search_flights", FLIGHTS)])
        if name == "weather":
            return AgentResult("weather", "Rain expected.", [call("get_daily_weather", DAY)])
        return AgentResult("planner", "Book X; pack a coat.")

    monkeypatch.setattr(trip_agents, "run_agent", fake)
    monkeypatch.setattr(trip_agents.anthropic, "AsyncAnthropic", lambda api_key=None: object())
    return log


def plan(**kwargs):
    args = dict(origin="London", destination="Paris", depart_date="2027-03-10", return_date=None, api_key="k")
    return asyncio.run(trip_agents.plan_trip(**{**args, **kwargs}))


def test_flight_and_weather_agents_run_in_parallel(monkeypatch):
    log = install_stub(monkeypatch, delay=0.3)
    started = time.perf_counter()
    plan()
    elapsed = time.perf_counter() - started
    assert elapsed < 0.55, f"sequential would take ~0.6s, took {elapsed:.2f}s"
    # Each started before the other finished.
    assert log["starts"]["weather"] < log["ends"]["flights"]
    assert log["starts"]["flights"] < log["ends"]["weather"]


def test_planner_runs_after_both_specialists(monkeypatch):
    log = install_stub(monkeypatch, delay=0.05)
    plan()
    assert log["starts"]["planner"] >= max(log["ends"]["flights"], log["ends"]["weather"])


def test_planner_receives_both_reports(monkeypatch):
    log = install_stub(monkeypatch)
    plan()
    assert "Cheapest is X." in log["messages"]["planner"]
    assert "Rain expected." in log["messages"]["planner"]


def test_response_shape(monkeypatch):
    install_stub(monkeypatch)
    out = plan()
    assert out["summary"] == "Book X; pack a coat."
    assert out["flights"] == FLIGHTS
    assert out["weather"] == [DAY]
    assert out["flights_error"] is None and out["weather_error"] is None
    assert [a["name"] for a in out["agents"]] == ["flights", "weather"]


def test_one_way_trip_is_described_as_one_way(monkeypatch):
    log = install_stub(monkeypatch)
    plan(return_date=None)
    assert "one way" in log["messages"]["flights"]


def test_round_trip_mentions_return_date(monkeypatch):
    log = install_stub(monkeypatch)
    plan(return_date="2027-03-17")
    assert "returning 2027-03-17" in log["messages"]["flights"]
    assert "2027-03-17" in log["messages"]["weather"]


def test_weather_lookups_for_both_dates_are_collected(monkeypatch):
    two_days = AgentResult(
        "weather", "ok",
        [call("get_daily_weather", {**DAY, "date": "2027-03-10"}), call("get_daily_weather", {**DAY, "date": "2027-03-17"})],
    )
    install_stub(monkeypatch, overrides={"weather": two_days})
    assert [d["date"] for d in plan(return_date="2027-03-17")["weather"]] == ["2027-03-10", "2027-03-17"]


def test_flight_tool_error_is_surfaced_and_weather_still_returned(monkeypatch):
    failed = AgentResult("flights", "Search failed.", [call("search_flights", {"error": "FlightSearchError: nope"}, True)])
    install_stub(monkeypatch, overrides={"flights": failed})
    out = plan()
    assert out["flights"] is None
    assert out["flights_error"] == "FlightSearchError: nope"
    assert out["weather"] == [DAY]
    assert out["weather_error"] is None


def test_weather_tool_error_is_surfaced_and_flights_still_returned(monkeypatch):
    failed = AgentResult("weather", "Lookup failed.", [call("get_daily_weather", {"error": "WeatherLookupError: x"}, True)])
    install_stub(monkeypatch, overrides={"weather": failed})
    out = plan()
    assert out["weather"] == []
    assert out["weather_error"] == "WeatherLookupError: x"
    assert out["flights"] == FLIGHTS


def test_agent_that_ran_out_of_turns_reports_its_error(monkeypatch):
    stuck = AgentResult("flights", "", [], error="The flights agent did not finish within 6 turns.")
    install_stub(monkeypatch, overrides={"flights": stuck})
    assert "did not finish" in plan()["flights_error"]


def test_summary_falls_back_to_specialist_text_if_planner_is_empty(monkeypatch):
    install_stub(monkeypatch, overrides={"planner": AgentResult("planner", "")})
    summary = plan()["summary"]
    assert "Cheapest is X." in summary and "Rain expected." in summary


def test_flight_payload_ignores_empty_offer_lists():
    empty = AgentResult("flights", "", [call("search_flights", {"offers": []})])
    assert trip_agents._flight_payload(empty) is None


def test_tool_schemas_require_the_right_fields():
    assert trip_agents.SEARCH_FLIGHTS_TOOL["input_schema"]["required"] == ["origin", "destination", "depart_date"]
    assert "return_date" not in trip_agents.SEARCH_FLIGHTS_TOOL["input_schema"]["required"]
    assert trip_agents.GET_DAILY_WEATHER_TOOL["input_schema"]["required"] == ["city", "date"]
