"""The milestone question, answered from the committed samples."""

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from openclock import service
from openclock.library import Library
from openclock.synthetic import AppleWorkout, apple_health_xml

SAMPLES = Path(__file__).parent.parent / "samples"
TZ = "America/Sao_Paulo"


@pytest.fixture
def library():
    return Library(SAMPLES)


def test_how_far_did_i_run_this_week_on_each_source(library):
    r = service.summarize_period(library, timezone=TZ, reference_date="2026-11-18")
    assert r["period"]["first_day"] == "2026-11-16"
    assert r["period"]["last_day"] == "2026-11-22"
    assert r["period"]["timezone"] == TZ
    garmin, apple = r["by_source"]["garmin"], r["by_source"]["apple_health"]
    assert (garmin["workout_count"], garmin["distance_km"], garmin["duration"]) == (
        1,
        8.42,
        "0:45:10",
    )
    assert (apple["workout_count"], apple["distance_km"], apple["duration"]) == (1, 5.02, "0:28:45")
    assert r["possible_duplicates"] == []
    assert r["combined"]["distance_km"] == 13.44
    assert r["combined"]["duration"] == "1:13:55"
    assert [w["source_file"] for w in r["workouts"]] == [
        "garmin_run_2026-11-17.fit",
        "apple_health_export_sample.xml",
    ]
    assert r["notes"] == []


def test_utc_moves_the_sunday_night_run_into_the_week(library):
    r = service.summarize_period(library, timezone="UTC", reference_date="2026-11-18")
    assert r["by_source"]["apple_health"]["workout_count"] == 2
    assert r["by_source"]["apple_health"]["distance_km"] == 8.12


def test_default_timezone_is_flagged(library, monkeypatch):
    monkeypatch.delenv(service.TIMEZONE_ENV, raising=False)
    r = service.summarize_period(library, reference_date="2026-11-18")
    assert r["period"]["timezone"] == "UTC"
    assert "using UTC" in r["notes"][0]


def test_timezone_from_environment(library, monkeypatch):
    monkeypatch.setenv(service.TIMEZONE_ENV, TZ)
    r = service.summarize_period(library, reference_date="2026-11-18")
    assert r["period"]["timezone"] == TZ


def test_custom_range_and_walking(library):
    r = service.summarize_period(
        library, timezone=TZ, start_date="2026-11-21", end_date="2026-11-21", sport="walking"
    )
    assert r["period"]["kind"] == "custom"
    assert r["by_source"]["apple_health"]["distance_km"] == 3.2


def test_list_workouts_filters(library):
    r = service.list_workouts(library, timezone=TZ, reference_date="2026-11-18")
    assert r["workout_count"] == 3  # Garmin run, Apple run, Apple walk
    only_garmin = service.list_workouts(
        library, timezone=TZ, reference_date="2026-11-18", source="garmin"
    )
    assert [w["source"] for w in only_garmin["workouts"]] == ["garmin"]
    assert only_garmin["workouts"][0]["start_local"] == "2026-11-17T06:30:00-03:00"


def test_stale_and_missing_sources_are_noted(library):
    r = service.summarize_period(library, timezone=TZ, reference_date="2026-12-09")
    assert r["combined"]["workout_count"] == 0
    assert any("garmin" in n and "outdated" in n for n in r["notes"])
    assert any("apple_health" in n and "outdated" in n for n in r["notes"])


def test_only_one_source_present(tmp_path):
    shutil.copy(SAMPLES / "garmin_run_2026-11-17.fit", tmp_path)
    r = service.summarize_period(Library(tmp_path), timezone=TZ, reference_date="2026-11-18")
    assert r["sources_without_data"] == ["apple_health"]
    assert "No apple_health files in the data directory." in r["notes"]


def test_duplicate_across_devices_withholds_combined_total(tmp_path):
    shutil.copy(SAMPLES / "garmin_run_2026-11-17.fit", tmp_path)
    # The same Tuesday run, recorded by the Apple Watch too.
    same_run = AppleWorkout(
        start=datetime.fromisoformat("2026-11-17T06:30:20-03:00"),
        end=datetime.fromisoformat("2026-11-17T07:15:30-03:00"),
        duration=44.9,
        distance=8.39,
    )
    (tmp_path / "export.xml").write_text(apple_health_xml([same_run]))
    library = Library(tmp_path)

    flagged = service.summarize_period(library, timezone=TZ, reference_date="2026-11-18")
    assert flagged["combined"] is None
    assert len(flagged["possible_duplicates"]) == 1
    assert flagged["by_source"]["garmin"]["distance_km"] == 8.42
    assert flagged["by_source"]["apple_health"]["distance_km"] == 8.39
    assert any("possible duplicate" in n for n in flagged["notes"])

    preferred = service.summarize_period(
        library, timezone=TZ, reference_date="2026-11-18", duplicate_policy="prefer_garmin"
    )
    assert preferred["combined"]["distance_km"] == 8.42
    assert preferred["excluded_from_combined"][0]["source"] == "apple_health"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timezone": "Mars/Base"}, "Unknown time zone"),
        ({"timezone": TZ, "start_date": "2026-11-01"}, "both start_date and end_date"),
        ({"timezone": TZ, "reference_date": "18/11/2026"}, "ISO date"),
        ({"timezone": TZ, "sport": "chess"}, "Unknown sport"),
        ({"timezone": TZ, "duplicate_policy": "guess"}, "Unknown duplicate_policy"),
    ],
)
def test_invalid_arguments(library, kwargs, message):
    with pytest.raises(ValueError, match=message):
        service.summarize_period(library, **kwargs)


# --- milestone 2: comparisons ----------------------------------------------------------------


def test_how_did_my_running_change_since_last_week(library):
    r = service.compare_periods(library, timezone=TZ, reference_date="2026-11-18")
    assert r["previous"]["period"]["first_day"] == "2026-11-09"
    assert r["previous"]["period"]["last_day"] == "2026-11-15"
    combined = r["changes"]["combined"]
    assert combined["workout_count"] == {"current": 2, "previous": 2, "change": 0}
    assert combined["distance_km"]["change"] == 2.84
    assert combined["distance_km"]["change_pct"] == 26.8
    assert combined["duration"]["change"] == "+0:14:10"
    assert combined["avg_pace"] == {
        "current": "5:30 /km",
        "previous": "5:38 /km",
        "change_s_per_km": -8.2,
        "direction": "faster",
    }
    garmin = r["changes"]["by_source"]["garmin"]
    assert (garmin["distance_km"]["previous"], garmin["distance_km"]["current"]) == (7.5, 8.42)
    assert r["notes"] == []


def test_pace_in_summary(library):
    r = service.summarize_period(library, timezone=TZ, reference_date="2026-11-18")
    assert r["by_source"]["garmin"]["avg_pace"] == "5:22 /km"
    assert r["combined"]["avg_pace"] == "5:30 /km"
    assert r["combined"]["longest_km"] == 8.42
    assert r["workouts"][0]["pace"] == "5:22 /km"


def test_month_summary_and_comparison(library):
    month = service.summarize_period(
        library, timezone=TZ, reference_date="2026-11-18", period_kind="month"
    )
    assert (month["period"]["first_day"], month["period"]["last_day"]) == (
        "2026-11-01",
        "2026-11-30",
    )
    assert month["combined"]["workout_count"] == 4  # every run in the samples
    assert month["combined"]["distance_km"] == 24.04
    r = service.compare_periods(
        library, timezone=TZ, reference_date="2026-11-18", period_kind="month"
    )
    assert r["previous"]["period"]["first_day"] == "2026-10-01"
    assert any("different lengths (30 vs 31 days)" in n for n in r["notes"])
    assert any("No workouts in the previous period" in n for n in r["notes"])
    assert r["changes"]["combined"]["distance_km"]["change_pct"] == "unavailable"


def test_compare_custom_range(library):
    r = service.compare_periods(
        library, timezone=TZ, start_date="2026-11-16", end_date="2026-11-22"
    )
    assert r["previous"]["period"]["first_day"] == "2026-11-09"
    assert r["previous"]["period"]["kind"] == "custom"


def test_unknown_period_kind(library):
    with pytest.raises(ValueError, match="Unknown period"):
        service.summarize_period(library, timezone=TZ, period_kind="year")


# --- milestone 2: goals ----------------------------------------------------------------------


def _by_id(result):
    return {g["id"]: g for g in result["goals"]}


def test_goal_progress_from_goals_file(library):
    r = service.goal_progress(library, timezone=TZ, as_of="2026-11-19", history=1)
    assert r["goals_from"] == "goals.toml"
    assert r["as_of"] == "2026-11-20T00:00-03:00"  # a date means "the whole day counts"
    goals = _by_id(r)
    distance = goals["weekly-distance"]
    assert distance["status"] == "on_track"
    assert (distance["actual"], distance["target"], distance["remaining"]) == (13.44, 20, 6.56)
    assert distance["expected_by_now"] == 11.43
    assert distance["days_left"] == 3
    assert distance["history"] == [
        {
            "first_day": "2026-11-09",
            "last_day": "2026-11-15",
            "actual": 10.6,
            "actual_display": "10.60 km",
            "status": "not_met",
        }
    ]
    assert [b["source_file"] for b in distance["based_on"]] == [
        "garmin_run_2026-11-17.fit",
        "apple_health_export_sample.xml",
    ]
    assert goals["weekly-runs"]["actual"] == 2
    assert goals["weekly-pace"]["status"] == "met"
    assert goals["weekly-pace"]["actual_display"] == "5:30 /km"
    assert goals["monthly-long-run"]["status"] == "in_progress"
    assert goals["monthly-long-run"]["period"]["kind"] == "month"


def test_goal_progress_after_the_week(library):
    r = service.goal_progress(library, timezone=TZ, as_of="2026-11-22", history=0)
    goals = _by_id(r)
    assert goals["weekly-distance"]["status"] == "not_met"
    assert goals["weekly-distance"]["progress_pct"] == 67.2
    assert goals["weekly-runs"]["status"] == "not_met"
    assert goals["weekly-pace"]["status"] == "met"


def test_inline_goals_override_the_file(library):
    r = service.goal_progress(
        library,
        timezone=TZ,
        as_of="2026-11-22",
        goals=[{"id": "ten", "metric": "distance_km", "target": 10}],
    )
    assert r["goals_from"] == "request"
    assert [g["id"] for g in r["goals"]] == ["ten"]
    assert r["goals"][0]["status"] == "met"


def test_reference_date_selects_another_week(library):
    r = service.goal_progress(
        library, timezone=TZ, as_of="2026-11-22", reference_date="2026-11-12", history=0
    )
    assert _by_id(r)["weekly-distance"]["period"]["first_day"] == "2026-11-09"
    assert _by_id(r)["weekly-distance"]["actual"] == 10.6


def test_no_goals_note(tmp_path):
    shutil.copy(SAMPLES / "garmin_run_2026-11-17.fit", tmp_path)
    r = service.goal_progress(Library(tmp_path), timezone=TZ, as_of="2026-11-19")
    assert r["goals"] == []
    assert any("No goals defined" in n for n in r["notes"])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"as_of": "Thursday"}, "as_of must be"),
        ({"history": 50}, "history must be"),
        ({"goals": [{"metric": "distance_km"}]}, "'target' is required"),
    ],
)
def test_goal_progress_invalid_arguments(library, kwargs, message):
    with pytest.raises(ValueError, match=message):
        service.goal_progress(library, timezone=TZ, **kwargs)


# --- data folder check -----------------------------------------------------------------------


def test_check_data_on_samples(library):
    r = service.check_data(library, timezone=TZ)
    assert r["sources"]["garmin"] == {
        "files": 2,
        "workouts": 2,
        "by_sport": {"running": 2},
        "first_day": "2026-11-10",
        "last_day": "2026-11-17",
        "missing_distance": 0,
        "missing_duration": 0,
    }
    assert r["sources"]["apple_health"]["by_sport"] == {"running": 2, "walking": 1}
    assert r["possible_duplicates"] == [] and r["problems"] == []
    assert r["goals"]["goals"] == [
        "weekly-distance",
        "weekly-runs",
        "weekly-pace",
        "monthly-long-run",
    ]


def test_check_data_reports_duplicates_problems_and_bad_goals(tmp_path):
    shutil.copy(SAMPLES / "garmin_run_2026-11-17.fit", tmp_path)
    same_run = AppleWorkout(
        start=datetime.fromisoformat("2026-11-17T06:30:20-03:00"),
        end=datetime.fromisoformat("2026-11-17T07:15:30-03:00"),
        duration=44.9,
        distance=8.39,
    )
    (tmp_path / "export.xml").write_text(apple_health_xml([same_run]))
    (tmp_path / "broken.fit").write_bytes(b"nope")
    (tmp_path / "goals.toml").write_text('[[goal]]\nmetric = "speed"\ntarget = 1\n')
    r = service.check_data(Library(tmp_path), timezone=TZ)
    assert len(r["possible_duplicates"]) == 1
    assert r["problems"][0]["file"] == "broken.fit"
    assert "unknown metric" in r["goals"]["error"]
    assert any("possible duplicate" in n for n in r["notes"])


def test_check_data_on_empty_folder(tmp_path):
    r = service.check_data(Library(tmp_path), timezone=TZ)
    assert r["files"] == 0
    assert any("No workouts found" in n for n in r["notes"])
