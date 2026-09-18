"""HTTP-level tests for the FastAPI app. plan_trip is stubbed, so no LLM is involved."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

import api

client = TestClient(api.app)

FUTURE = (dt.date.today() + dt.timedelta(days=30)).isoformat()
LATER = (dt.date.today() + dt.timedelta(days=37)).isoformat()
PAST = (dt.date.today() - dt.timedelta(days=3)).isoformat()

GOOD_RESULT = {
    "summary": "Book the cheap one.",
    "flights": {"offers": [{"rank": 1}]},
    "flights_error": None,
    "weather": [{"date": FUTURE, "severity": "none"}],
    "weather_error": None,
    "agents": [{"name": "flights", "text": "t", "error": None}],
}


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture
def stub_plan(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return GOOD_RESULT

    monkeypatch.setattr(api, "plan_trip", fake)
    return calls


def post(**body):
    payload = {"origin": "London", "destination": "Paris", "depart_date": FUTURE, **body}
    return client.post("/api/trip", json=payload)


class TestConfig:
    def test_reports_estimated_without_amadeus_keys(self):
        assert client.get("/api/config").json() == {"flight_source": "estimated"}

    def test_reports_amadeus_when_configured(self, monkeypatch):
        monkeypatch.setenv("AMADEUS_CLIENT_ID", "a")
        monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "b")
        assert client.get("/api/config").json() == {"flight_source": "amadeus"}


class TestValidation:
    @pytest.mark.parametrize("field", ["origin", "destination"])
    def test_blank_city_rejected(self, stub_plan, field):
        response = post(**{field: "   "})
        assert response.status_code == 400
        assert "both a start and a destination" in response.json()["detail"]
        assert stub_plan == []

    def test_same_city_rejected_case_insensitively(self, stub_plan):
        response = post(origin="Paris", destination=" paris ")
        assert response.status_code == 400
        assert "same" in response.json()["detail"]

    def test_past_travel_date_rejected(self, stub_plan):
        response = post(depart_date=PAST)
        assert response.status_code == 400
        assert "in the past" in response.json()["detail"]

    def test_malformed_travel_date_rejected(self, stub_plan):
        response = post(depart_date="oct 10")
        assert response.status_code == 400
        assert "YYYY-MM-DD" in response.json()["detail"]

    def test_return_before_travel_rejected(self, stub_plan):
        response = post(return_date=PAST)
        assert response.status_code == 400
        assert "before the travel date" in response.json()["detail"]

    def test_malformed_return_date_rejected(self, stub_plan):
        assert post(return_date="later").status_code == 400

    def test_missing_field_is_a_422(self):
        assert client.post("/api/trip", json={"origin": "London"}).status_code == 422

    def test_missing_api_key_is_a_500(self, stub_plan, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        response = post()
        assert response.status_code == 500
        assert "ANTHROPIC_API_KEY" in response.json()["detail"]


class TestSuccess:
    def test_returns_result_and_flight_source(self, stub_plan):
        response = post()
        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == "Book the cheap one."
        assert body["flights"]["offers"][0]["rank"] == 1
        assert body["flight_source"] == "estimated"

    def test_return_date_is_optional(self, stub_plan):
        assert post().status_code == 200
        assert stub_plan[-1]["return_date"] is None

    def test_empty_string_return_date_is_treated_as_none(self, stub_plan):
        assert post(return_date="").status_code == 200
        assert stub_plan[-1]["return_date"] is None

    def test_return_date_is_passed_through(self, stub_plan):
        assert post(return_date=LATER).status_code == 200
        assert stub_plan[-1]["return_date"] == LATER

    def test_cities_are_trimmed(self, stub_plan):
        post(origin="  London ", destination=" Paris  ")
        assert (stub_plan[-1]["origin"], stub_plan[-1]["destination"]) == ("London", "Paris")

    def test_same_day_return_is_allowed(self, stub_plan):
        assert post(return_date=FUTURE).status_code == 200

    def test_api_key_is_forwarded_to_the_agents(self, stub_plan):
        post()
        assert stub_plan[-1]["api_key"] == "test-key"


class TestFailures:
    def test_agent_crash_becomes_a_502(self, monkeypatch):
        async def boom(**kwargs):
            raise RuntimeError("anthropic is down")

        monkeypatch.setattr(api, "plan_trip", boom)
        response = post()
        assert response.status_code == 502
        assert "anthropic is down" in response.json()["detail"]
