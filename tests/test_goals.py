from datetime import date, datetime

import pytest
from helpers import make_workout

from openclock.goals import (
    Goal,
    GoalMetric,
    GoalStatus,
    evaluate,
    load_goals_file,
    parse_goal,
    parse_goals,
    parse_pace,
)
from openclock.metrics import DuplicatePolicy
from openclock.models import Source, Sport
from openclock.periods import month_containing, week_containing

TZ = "America/Sao_Paulo"
WEEK = week_containing(date(2026, 11, 18), TZ)
END_OF_THURSDAY = datetime.fromisoformat("2026-11-20T00:00:00-03:00")  # 4/7 of the week
AFTER_WEEK = datetime.fromisoformat("2026-11-23T08:00:00-03:00")

PREVIOUS = make_workout(Source.GARMIN, "2026-11-10T09:30:00+00:00", 2475, 7500)
TUESDAY = make_workout(Source.GARMIN, "2026-11-17T09:30:00+00:00", 2710, 8420)
THURSDAY = make_workout(Source.APPLE_HEALTH, "2026-11-19T21:05:00+00:00", 1725, 5020)
WORKOUTS = [PREVIOUS, TUESDAY, THURSDAY]


def goal(metric="distance_km", target=20, **kw) -> Goal:
    return parse_goal({"metric": metric, "target": target, **kw})


# --- parsing -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "seconds"), [("5:30", 330), ("05:05 /km", 305), (290, 290.0)])
def test_parse_pace(text, seconds):
    assert parse_pace(text) == seconds


@pytest.mark.parametrize("bad", ["5.30", "5:75", "fast", ""])
def test_parse_pace_rejects(bad):
    with pytest.raises(ValueError, match="Pace target"):
        parse_pace(bad)


def test_parse_goal_defaults():
    g = parse_goal({"metric": "distance_km", "target": "20"})
    assert (g.id, g.per, g.sport, g.source, g.target) == (
        "distance_km-week",
        "week",
        Sport.RUNNING,
        None,
        20.0,
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"target": 1}, "'metric' is required"),
        ({"metric": "speed", "target": 1}, "unknown metric"),
        ({"metric": "distance_km"}, "'target' is required"),
        ({"metric": "distance_km", "target": -5}, "positive"),
        ({"metric": "distance_km", "target": "lots"}, "must be a number"),
        ({"metric": "distance_km", "target": 5, "per": "day"}, "'per' must be"),
        ({"metric": "distance_km", "target": 5, "sport": "chess"}, "unknown sport"),
        ({"metric": "distance_km", "target": 5, "source": "strava"}, "source must be"),
    ],
)
def test_parse_goal_errors(data, message):
    with pytest.raises(ValueError, match=message):
        parse_goal(data)


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="Duplicate goal id"):
        parse_goals([{"id": "a", "metric": "distance_km", "target": 1}] * 2)


def test_load_goals_file(tmp_path):
    path = tmp_path / "goals.toml"
    path.write_text('[[goal]]\nmetric = "avg_pace"\ntarget = "5:35"\n')
    (g,) = load_goals_file(path)
    assert g.metric == GoalMetric.AVG_PACE and g.target == 335
    path.write_text("[[goal]\n")
    with pytest.raises(ValueError, match="invalid TOML"):
        load_goals_file(path)


# --- progress ----------------------------------------------------------------------------------


def test_cumulative_goal_on_track_mid_week():
    p = evaluate(goal(), WORKOUTS, WEEK, END_OF_THURSDAY)
    assert p.status == GoalStatus.ON_TRACK
    assert p.actual == pytest.approx(13.44)
    assert p.elapsed_fraction == pytest.approx(4 / 7)
    assert p.expected_by_now == pytest.approx(20 * 4 / 7)
    assert p.remaining == pytest.approx(6.56)
    assert p.days_left == 3


def test_as_of_ignores_later_workouts_and_can_be_behind():
    end_of_wednesday = datetime.fromisoformat("2026-11-19T00:00:00-03:00")
    p = evaluate(goal(), WORKOUTS, WEEK, end_of_wednesday)
    assert p.actual == pytest.approx(8.42)  # Thursday's run has not happened yet
    assert p.status == GoalStatus.BEHIND  # 8.42 < 20 * 3/7 = 8.57


def test_completed_period_met_and_not_met():
    assert evaluate(goal(target=20), WORKOUTS, WEEK, AFTER_WEEK).status == GoalStatus.NOT_MET
    assert evaluate(goal(target=13), WORKOUTS, WEEK, AFTER_WEEK).status == GoalStatus.MET


def test_pace_goal_lower_is_better():
    assert evaluate(goal("avg_pace", "5:35"), WORKOUTS, WEEK, AFTER_WEEK).status == GoalStatus.MET
    slow = evaluate(goal("avg_pace", "5:00"), WORKOUTS, WEEK, END_OF_THURSDAY)
    assert slow.status == GoalStatus.IN_PROGRESS
    assert slow.remaining is None


def test_longest_run_goal_per_month():
    month = month_containing(date(2026, 11, 18), TZ)
    p = evaluate(goal("longest_km", 10, per="month"), WORKOUTS, month, END_OF_THURSDAY)
    assert p.status == GoalStatus.IN_PROGRESS
    assert p.actual == pytest.approx(8.42)
    met = evaluate(goal("longest_km", 8, per="month"), WORKOUTS, month, END_OF_THURSDAY)
    assert met.status == GoalStatus.MET


def test_count_and_duration_goals():
    runs = evaluate(goal("workout_count", 3), WORKOUTS, WEEK, AFTER_WEEK)
    assert (runs.actual, runs.status, runs.remaining) == (2, GoalStatus.NOT_MET, 1)
    minutes = evaluate(goal("duration_min", 60), WORKOUTS, WEEK, AFTER_WEEK)
    assert minutes.actual == pytest.approx((2710 + 1725) / 60)
    assert minutes.status == GoalStatus.MET


def test_source_specific_goal():
    p = evaluate(goal(source="apple_health", target=5), WORKOUTS, WEEK, AFTER_WEEK)
    assert p.actual == pytest.approx(5.02)
    assert [w.source for w in p.workouts] == [Source.APPLE_HEALTH]


def test_not_started_and_no_data():
    before = datetime.fromisoformat("2026-11-15T12:00:00-03:00")
    assert evaluate(goal(), WORKOUTS, WEEK, before).status == GoalStatus.NOT_STARTED
    old_week = week_containing(date(2026, 10, 1), TZ)
    assert evaluate(goal(), WORKOUTS, old_week, AFTER_WEEK).status == GoalStatus.NO_DATA


def test_history_marks_periods_before_first_workout_as_no_data():
    p = evaluate(goal(), WORKOUTS, WEEK, END_OF_THURSDAY, history=3)
    assert [h.period.first_day.isoformat() for h in p.history] == [
        "2026-11-09",
        "2026-11-02",
        "2026-10-26",
    ]
    assert [h.status for h in p.history] == [
        GoalStatus.NOT_MET,
        GoalStatus.NO_DATA,
        GoalStatus.NO_DATA,
    ]
    assert p.history[0].actual == pytest.approx(7.5)
    assert p.recent_met == (0, 1)
    assert p.recent_average == pytest.approx(7.5)


def test_duplicates_make_combined_goal_unavailable_until_a_policy_is_chosen():
    same_run = make_workout(Source.APPLE_HEALTH, "2026-11-17T09:30:30+00:00", 2700, 8400)
    workouts = [TUESDAY, same_run]
    flagged = evaluate(goal(), workouts, WEEK, END_OF_THURSDAY)
    assert flagged.status == GoalStatus.UNAVAILABLE
    assert "duplicate" in flagged.reason
    pace = evaluate(goal("avg_pace", "5:35"), workouts, WEEK, END_OF_THURSDAY)
    assert pace.status == GoalStatus.UNAVAILABLE
    chosen = evaluate(goal(), workouts, WEEK, END_OF_THURSDAY, DuplicatePolicy.PREFER_GARMIN)
    assert chosen.actual == pytest.approx(8.42)


def test_missing_distance_is_unavailable_not_zero():
    no_distance = make_workout(Source.GARMIN, "2026-11-17T09:30:00+00:00", 2710, None)
    p = evaluate(goal(), [no_distance], WEEK, END_OF_THURSDAY)
    assert p.status == GoalStatus.UNAVAILABLE
    assert p.actual is None


def test_naive_as_of_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate(goal(), WORKOUTS, WEEK, datetime(2026, 11, 19))
