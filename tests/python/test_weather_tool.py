import datetime as dt

import pytest
import requests

import weather_tool
from weather_tool import WeatherLookupError, _warnings_for, get_daily_weather

TODAY = dt.date.today()


def iso(days_from_today: int) -> str:
    return (TODAY + dt.timedelta(days=days_from_today)).isoformat()


def kinds(warnings):
    return {w["type"] for w in warnings}


# ------------------------------------------------------------------ warnings rules


class TestWarnings:
    def test_calm_day_has_no_warnings(self):
        day = {"weather_code": 1, "precipitation_sum": 0, "temperature_2m_max": 20, "temperature_2m_min": 10}
        assert _warnings_for(day) == []

    def test_thunderstorm_is_high_severity(self):
        warnings = _warnings_for({"weather_code": 95})
        assert kinds(warnings) == {"thunderstorm"}
        assert warnings[0]["severity"] == "high"

    def test_freezing_rain_is_high_severity(self):
        assert _warnings_for({"weather_code": 66})[0]["severity"] == "high"

    def test_fog_is_moderate(self):
        warnings = _warnings_for({"weather_code": 45})
        assert (warnings[0]["type"], warnings[0]["severity"]) == ("fog", "moderate")

    @pytest.mark.parametrize(
        "rain,expected",
        [(35, "high"), (30, "high"), (12, "moderate"), (10, "moderate")],
    )
    def test_rain_thresholds(self, rain, expected):
        warnings = _warnings_for({"precipitation_sum": rain})
        assert warnings[0]["severity"] == expected

    def test_light_rain_is_not_warned(self):
        assert _warnings_for({"precipitation_sum": 3}) == []

    def test_high_rain_probability_gives_a_low_warning(self):
        warnings = _warnings_for({"precipitation_sum": 2, "precipitation_probability_max": 85})
        assert (warnings[0]["type"], warnings[0]["severity"]) == ("rain", "low")

    def test_rain_probability_absent_for_seasonal_data(self):
        assert _warnings_for({"precipitation_sum": 2, "precipitation_probability_max": None}) == []

    @pytest.mark.parametrize(
        "snow,expected",
        [(8, "high"), (5, "high"), (2, "moderate"), (0.5, "moderate"), (0.2, "low")],
    )
    def test_snow_thresholds(self, snow, expected):
        assert _warnings_for({"snowfall_sum": snow})[0]["severity"] == expected

    def test_no_snow_no_warning(self):
        assert _warnings_for({"snowfall_sum": 0}) == []

    def test_small_snow_message_is_not_rounded_to_zero(self):
        message = _warnings_for({"snowfall_sum": 0.3})[0]["message"]
        assert "0.3" in message and "(0 cm)" not in message

    @pytest.mark.parametrize(
        "gusts,wind,expected",
        [(100, 0, "high"), (70, 0, "moderate"), (10, 50, "low")],
    )
    def test_wind_thresholds(self, gusts, wind, expected):
        warnings = _warnings_for({"wind_gusts_10m_max": gusts, "wind_speed_10m_max": wind})
        assert warnings[0]["severity"] == expected

    def test_heat(self):
        assert _warnings_for({"temperature_2m_max": 40})[0]["severity"] == "high"
        assert _warnings_for({"temperature_2m_max": 34})[0]["severity"] == "moderate"
        assert _warnings_for({"temperature_2m_max": 30}) == []

    def test_cold(self):
        assert _warnings_for({"temperature_2m_min": -15})[0]["severity"] == "high"
        assert _warnings_for({"temperature_2m_min": -2})[0]["severity"] == "moderate"
        assert _warnings_for({"temperature_2m_min": 4}) == []

    def test_missing_fields_do_not_crash(self):
        assert _warnings_for({}) == []

    def test_multiple_hazards_are_all_reported(self):
        day = {"weather_code": 95, "precipitation_sum": 40, "wind_gusts_10m_max": 95}
        assert kinds(_warnings_for(day)) == {"thunderstorm", "rain", "wind"}


# --------------------------------------------------------------- date helpers


class TestDateHelpers:
    def test_parse_date_ok(self):
        assert weather_tool._parse_date("2026-12-20") == dt.date(2026, 12, 20)

    @pytest.mark.parametrize("bad", ["oct 10", "2026-13-01", "", None, "20/12/2026"])
    def test_parse_date_rejects_garbage(self, bad):
        with pytest.raises(WeatherLookupError):
            weather_tool._parse_date(bad)

    def test_leap_day_maps_to_28th_in_non_leap_year(self):
        assert weather_tool._same_day_other_year(dt.date(2028, 2, 29), 2025) == dt.date(2025, 2, 28)

    def test_normal_day_keeps_month_and_day(self):
        assert weather_tool._same_day_other_year(dt.date(2026, 12, 20), 2024) == dt.date(2024, 12, 20)


# ----------------------------------------------------------------- get_daily_weather

FORECAST_DAY = {
    "weather_code": 0, "temperature_2m_max": 22.0, "temperature_2m_min": 14.0,
    "precipitation_sum": 0.0, "precipitation_probability_max": 10,
    "wind_speed_10m_max": 12.0, "wind_gusts_10m_max": 25.0, "snowfall_sum": 0.0,
}


def _daily(day):
    return {"time": ["x"], **{k: [v] for k, v in day.items()}}


class TestGetDailyWeather:
    def test_near_date_uses_forecast(self, fake_geocode, monkeypatch):
        monkeypatch.setattr(weather_tool, "_fetch_daily", lambda *a, **k: _daily(FORECAST_DAY))
        result = get_daily_weather("London", iso(3))
        assert result["source"] == "forecast"
        assert result["note"] is None
        assert result["condition"] == "Clear sky"
        assert result["severity"] == "none"
        assert result["warnings"] == []

    def test_far_date_uses_seasonal_normals_without_calling_forecast(self, fake_geocode, monkeypatch):
        def boom(url, *a, **k):
            assert url == weather_tool.ARCHIVE_URL, "forecast endpoint must not be used this far out"
            return _daily(FORECAST_DAY)

        monkeypatch.setattr(weather_tool, "_fetch_daily", boom)
        result = get_daily_weather("London", iso(120))
        assert result["source"] == "seasonal_normals"
        assert "not a forecast" in result["note"]

    def test_forecast_failure_falls_back_to_seasonal(self, fake_geocode, monkeypatch):
        def flaky(url, *a, **k):
            if url == weather_tool.FORECAST_URL:
                raise requests.HTTPError("400 Bad Request")
            return _daily(FORECAST_DAY)

        monkeypatch.setattr(weather_tool, "_fetch_daily", flaky)
        result = get_daily_weather("London", iso(14))
        assert result["source"] == "seasonal_normals"

    def test_seasonal_normals_average_the_years(self, fake_geocode, monkeypatch):
        temps = iter([10.0, 20.0, 30.0])

        def archive(url, *a, **k):
            return _daily({**FORECAST_DAY, "temperature_2m_max": next(temps)})

        monkeypatch.setattr(weather_tool, "_fetch_daily", archive)
        result = get_daily_weather("London", iso(200))
        assert result["temp_max_c"] == 20.0

    def test_seasonal_normals_survive_one_failed_year(self, fake_geocode, monkeypatch):
        calls = {"n": 0}

        def archive(url, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.ConnectionError("down")
            return _daily(FORECAST_DAY)

        monkeypatch.setattr(weather_tool, "_fetch_daily", archive)
        result = get_daily_weather("London", iso(200))
        assert result["source"] == "seasonal_normals"
        assert "2 year" in result["note"]

    def test_seasonal_normals_all_years_failing_raises(self, fake_geocode, monkeypatch):
        def dead(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(weather_tool, "_fetch_daily", dead)
        with pytest.raises(WeatherLookupError):
            get_daily_weather("London", iso(200))

    def test_severity_is_the_worst_warning(self, fake_geocode, monkeypatch):
        stormy = {**FORECAST_DAY, "weather_code": 95, "precipitation_sum": 12}
        monkeypatch.setattr(weather_tool, "_fetch_daily", lambda *a, **k: _daily(stormy))
        result = get_daily_weather("London", iso(2))
        assert result["severity"] == "high"
        assert {"thunderstorm", "rain"} <= kinds(result["warnings"])

    def test_unknown_city_raises(self, fake_geocode):
        with pytest.raises(WeatherLookupError, match="Could not find"):
            get_daily_weather("Atlantis", iso(2))

    def test_bad_date_raises(self, fake_geocode):
        with pytest.raises(WeatherLookupError, match="not a valid date"):
            get_daily_weather("London", "next tuesday")

    def test_result_shape(self, fake_geocode, monkeypatch):
        monkeypatch.setattr(weather_tool, "_fetch_daily", lambda *a, **k: _daily(FORECAST_DAY))
        result = get_daily_weather("London", iso(1))
        assert {"city", "country", "date", "source", "condition", "severity", "warnings",
                "temp_max_c", "temp_min_c", "wind_gust_kmh", "precipitation_mm"} <= result.keys()
        assert result["city"] == "London"
        assert result["date"] == iso(1)
