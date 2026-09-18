import pytest

import flight_tool
from flight_tool import FlightSearchError, search_flights

DEPART = "2027-03-10"
RETURN = "2027-03-17"


def prices(result):
    return [offer["price"] for offer in result["offers"]]


class TestValidation:
    def test_missing_cities(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="required"):
            search_flights("", "Paris", DEPART)
        with pytest.raises(FlightSearchError, match="required"):
            search_flights("London", "  ", DEPART)

    def test_same_city(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="same city"):
            search_flights("London", "london", DEPART)

    def test_bad_travel_date(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="Travel date"):
            search_flights("London", "Paris", "10 March")

    def test_bad_return_date(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="Return date"):
            search_flights("London", "Paris", DEPART, "soon")

    def test_return_before_travel(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="before the travel date"):
            search_flights("London", "Paris", DEPART, "2027-03-01")

    def test_unknown_city(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="Could not find"):
            search_flights("London", "Atlantis", DEPART)

    def test_cities_too_close_for_a_flight(self, fake_geocode):
        with pytest.raises(FlightSearchError, match="km apart"):
            search_flights("Paris", "Versailles", DEPART)


class TestRanking:
    def test_offers_sorted_cheapest_first(self, fake_geocode):
        result = search_flights("Chennai", "Tokyo", DEPART)
        assert prices(result) == sorted(prices(result))

    def test_ranks_are_sequential_from_one(self, fake_geocode):
        result = search_flights("Chennai", "Tokyo", DEPART)
        assert [o["rank"] for o in result["offers"]] == list(range(1, len(result["offers"]) + 1))
        assert result["offers"][0]["price"] == min(prices(result))

    def test_round_trip_sorted_too(self, fake_geocode):
        result = search_flights("Chennai", "Tokyo", DEPART, RETURN)
        assert prices(result) == sorted(prices(result))

    def test_at_most_max_offers(self, fake_geocode):
        assert len(search_flights("London", "Tokyo", DEPART)["offers"]) <= flight_tool.MAX_OFFERS


class TestTripShape:
    def test_one_way_has_no_inbound_leg(self, fake_geocode):
        result = search_flights("London", "Paris", DEPART)
        assert result["trip_type"] == "one_way"
        assert result["return_date"] is None
        assert all(o["inbound"] is None for o in result["offers"])

    def test_round_trip_has_inbound_leg_on_return_date(self, fake_geocode):
        result = search_flights("London", "Paris", DEPART, RETURN)
        assert result["trip_type"] == "round_trip"
        for offer in result["offers"]:
            assert offer["outbound"]["date"] == DEPART
            assert offer["inbound"]["date"] == RETURN
            assert offer["inbound"]["from"] == offer["outbound"]["to"]

    def test_round_trip_costs_more_than_one_way_on_average(self, fake_geocode):
        one_way = search_flights("London", "Tokyo", DEPART)
        round_trip = search_flights("London", "Tokyo", DEPART, RETURN)
        assert min(prices(round_trip)) > min(prices(one_way))

    def test_total_stops_is_sum_of_legs(self, fake_geocode):
        for offer in search_flights("Chennai", "Tokyo", DEPART, RETURN)["offers"]:
            assert offer["total_stops"] == offer["outbound"]["stops"] + offer["inbound"]["stops"]


class TestEstimatedBackend:
    def test_is_labelled_as_estimated(self, fake_geocode):
        result = search_flights("London", "Paris", DEPART)
        assert result["source"] == "estimated"
        assert "Estimated" in result["disclaimer"]

    def test_deterministic_for_the_same_search(self, fake_geocode):
        assert search_flights("London", "Tokyo", DEPART, RETURN) == search_flights("London", "Tokyo", DEPART, RETURN)

    def test_different_dates_give_different_offers(self, fake_geocode):
        assert prices(search_flights("London", "Tokyo", DEPART)) != prices(search_flights("London", "Tokyo", "2027-04-10"))

    def test_longer_routes_cost_more(self, fake_geocode):
        short = min(prices(search_flights("London", "Paris", DEPART)))
        long_haul = min(prices(search_flights("London", "Tokyo", DEPART)))
        assert long_haul > short

    def test_budget_carriers_do_not_fly_intercontinental(self, fake_geocode):
        budget = {"Ryanair", "easyJet", "Wizz Air", "AirAsia"}
        airlines = {o["airline"] for o in search_flights("London", "Tokyo", DEPART)["offers"]}
        assert not airlines & budget

    def test_passengers_multiply_price(self, fake_geocode):
        solo = search_flights("London", "Paris", DEPART, adults=1)
        pair = search_flights("London", "Paris", DEPART, adults=2)
        assert min(prices(pair)) == pytest.approx(min(prices(solo)) * 2, rel=0.01)

    def test_leg_fields_are_well_formed(self, fake_geocode):
        leg = search_flights("London", "Paris", DEPART)["offers"][0]["outbound"]
        assert {"from", "to", "date", "depart", "arrive", "duration", "stops", "airline", "flight_number"} <= leg.keys()
        assert len(leg["depart"]) == 5 and leg["depart"][2] == ":"


class TestHelpers:
    def test_haversine_london_paris(self):
        assert flight_tool._haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(344, abs=5)

    def test_haversine_zero_distance(self):
        assert flight_tool._haversine_km(10, 10, 10, 10) == 0

    @pytest.mark.parametrize("value,minutes", [("PT2H30M", 150), ("PT45M", 45), ("PT3H", 180), ("P1DT2H", 1560), ("", 0), ("junk", 0)])
    def test_iso_duration(self, value, minutes):
        assert flight_tool._parse_iso_duration(value) == minutes

    def test_format_minutes(self):
        assert flight_tool._format_minutes(65) == "1h 05m"
        assert flight_tool._format_minutes(600) == "10h 00m"


class TestAmadeusBackend:
    OFFER = {
        "price": {"grandTotal": "250.40", "currency": "USD"},
        "itineraries": [
            {"duration": "PT1H15M", "segments": [
                {"carrierCode": "BA", "number": "304", "departure": {"iataCode": "LHR", "at": "2027-03-10T08:00:00"},
                 "arrival": {"iataCode": "CDG", "at": "2027-03-10T10:15:00"}}]},
            {"duration": "PT2H", "segments": [
                {"carrierCode": "BA", "number": "305", "departure": {"iataCode": "CDG", "at": "2027-03-17T12:00:00"},
                 "arrival": {"iataCode": "AMS", "at": "2027-03-17T13:00:00"}},
                {"carrierCode": "KL", "number": "1", "departure": {"iataCode": "AMS", "at": "2027-03-17T14:00:00"},
                 "arrival": {"iataCode": "LHR", "at": "2027-03-17T14:30:00"}}]},
        ],
    }

    def _payload(self, *offers):
        return {"data": list(offers), "dictionaries": {"carriers": {"BA": "BRITISH AIRWAYS", "KL": "KLM"}}}

    def _install(self, monkeypatch, payload, status=200):
        monkeypatch.setenv("AMADEUS_CLIENT_ID", "id")
        monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "secret")
        monkeypatch.setattr(flight_tool, "_amadeus_city_code", lambda city: city[:3].upper())
        monkeypatch.setattr(flight_tool, "_amadeus_token", lambda: "tok")

        class Response:
            status_code = status

            def json(self):
                return payload

        monkeypatch.setattr(flight_tool.requests, "get", lambda *a, **k: Response())

    def test_configured_flag(self, monkeypatch):
        assert not flight_tool.amadeus_configured()
        monkeypatch.setenv("AMADEUS_CLIENT_ID", "x")
        assert not flight_tool.amadeus_configured()
        monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "y")
        assert flight_tool.amadeus_configured()

    def test_parses_and_sorts_real_offers(self, monkeypatch):
        cheap = {**self.OFFER, "price": {"grandTotal": "99.00", "currency": "USD"}}
        self._install(monkeypatch, self._payload(self.OFFER, cheap))
        result = search_flights("London", "Paris", DEPART, RETURN)
        assert result["source"] == "amadeus"
        assert result["disclaimer"] is None
        assert prices(result) == [99.0, 250.4]
        top = result["offers"][1]
        assert top["airline"] == "British Airways"
        assert top["outbound"]["flight_number"] == "BA304"
        assert top["outbound"]["stops"] == 0
        assert top["inbound"]["stops"] == 1
        assert top["total_stops"] == 1
        assert top["outbound"]["duration"] == "1h 15m"

    def test_no_results_is_an_error(self, monkeypatch):
        self._install(monkeypatch, self._payload())
        with pytest.raises(FlightSearchError, match="No flights found"):
            search_flights("London", "Paris", DEPART)

    def test_api_error_is_reported(self, monkeypatch):
        self._install(monkeypatch, {"errors": [{"detail": "date in the past"}]}, status=400)
        with pytest.raises(FlightSearchError, match="400.*date in the past"):
            search_flights("London", "Paris", DEPART)
