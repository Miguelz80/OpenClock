from datetime import date

from helpers import make_workout

from openclock.metrics import summarize
from openclock.models import Source
from openclock.periods import week_containing
from openclock.report import (
    format_duration,
    format_pace,
    format_signed_duration,
    summary_to_dict,
    workout_to_dict,
)


def test_format_duration():
    assert format_duration(0) == "0:00:00"
    assert format_duration(2710) == "0:45:10"
    assert format_duration(3725.4) == "1:02:05"
    assert format_duration(None) == "unavailable"


def test_workout_dict_shows_local_time_and_unavailable_metrics():
    w = make_workout(start="2026-11-17T09:30:00+00:00", distance_m=None)
    d = workout_to_dict(w, "America/Sao_Paulo")
    assert d["start_local"] == "2026-11-17T06:30:00-03:00"
    assert d["distance_km"] == "unavailable"
    assert d["unavailable_metrics"] == ["distance"]


def test_summary_dict_units():
    week = week_containing(date(2026, 11, 18), "America/Sao_Paulo")
    s = summarize([make_workout(Source.GARMIN, duration_s=2710, distance_m=8420)], week)
    d = summary_to_dict(s)
    assert d["period"]["first_day"] == "2026-11-16"
    assert d["period"]["last_day"] == "2026-11-22"
    assert d["by_source"]["garmin"]["distance_km"] == 8.42
    assert d["by_source"]["garmin"]["duration"] == "0:45:10"
    assert d["by_source"]["apple_health"]["workout_count"] == 0
    assert d["sources_without_data"] == ["apple_health"]
    assert d["combined"]["distance_km"] == 8.42


def test_format_pace():
    assert format_pace(329.99) == "5:30 /km"
    assert format_pace(321.85) == "5:22 /km"
    assert format_pace(None) == "unavailable"


def test_format_signed_duration():
    assert format_signed_duration(850) == "+0:14:10"
    assert format_signed_duration(-905) == "-0:15:05"
