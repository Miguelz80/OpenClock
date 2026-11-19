from datetime import date

import pytest
from helpers import make_workout

from openclock.metrics import (
    Delta,
    DuplicatePolicy,
    compare,
    find_possible_duplicates,
    summarize,
    totals,
)
from openclock.models import Source, Sport
from openclock.periods import month_containing, previous_equivalent, week_containing

WEEK = week_containing(date(2026, 11, 18), "America/Sao_Paulo")


def test_totals_per_source_and_combined_without_duplicates():
    workouts = [
        make_workout(Source.GARMIN, "2026-11-17T09:30:00+00:00", 2710, 8420),
        make_workout(Source.APPLE_HEALTH, "2026-11-19T21:05:00+00:00", 1725, 5020),
    ]
    s = summarize(workouts, WEEK)
    assert s.by_source[Source.GARMIN].distance_m == 8420
    assert s.by_source[Source.APPLE_HEALTH].distance_m == 5020
    assert s.possible_duplicates == []
    assert s.combined.distance_m == pytest.approx(13440)
    assert s.combined.duration_s == pytest.approx(4435)


def test_workouts_outside_the_local_week_are_excluded():
    sunday_night_local = make_workout(start="2026-11-16T01:10:00+00:00")  # Sun 22:10 -03:00
    next_monday_local = make_workout(start="2026-11-23T03:00:00+00:00")  # Mon 00:00 -03:00
    s = summarize([sunday_night_local, next_monday_local], WEEK)
    assert s.workouts == []
    assert s.combined.workout_count == 0
    assert s.combined.distance_m == 0


def test_other_sports_are_excluded_by_default():
    walk = make_workout(sport=Sport.WALKING)
    assert summarize([walk], WEEK).combined.workout_count == 0
    assert summarize([walk], WEEK, sport=None).combined.workout_count == 1


def test_missing_metrics_are_counted_not_zeroed():
    t = totals([make_workout(distance_m=None), make_workout(distance_m=3000.0)])
    assert t.distance_m == 3000.0
    assert t.missing_distance == 1
    all_missing = totals([make_workout(distance_m=None, duration_s=None)])
    assert all_missing.distance_m is None
    assert all_missing.duration_s is None
    assert all_missing.missing_duration == 1


def test_empty_source_is_reported():
    s = summarize([make_workout(Source.GARMIN)], WEEK)
    assert s.sources_without_data == [Source.APPLE_HEALTH]


# --- duplicates ---------------------------------------------------------------------------

GARMIN_RUN = make_workout(Source.GARMIN, "2026-11-17T09:30:00+00:00", 2710, 8420)
APPLE_SAME_RUN = make_workout(Source.APPLE_HEALTH, "2026-11-17T09:30:40+00:00", 2690, 8390)


def test_overlapping_runs_from_two_devices_are_flagged():
    pairs = find_possible_duplicates([GARMIN_RUN, APPLE_SAME_RUN])
    assert len(pairs) == 1
    assert pairs[0].overlap_ratio > 0.9


def test_same_source_never_counts_as_duplicate():
    other = make_workout(Source.GARMIN, "2026-11-17T09:31:00+00:00", 2700, 8000, source_id="z")
    assert find_possible_duplicates([GARMIN_RUN, other]) == []


def test_different_sport_is_not_a_duplicate():
    ride = make_workout(
        Source.APPLE_HEALTH, "2026-11-17T09:30:00+00:00", 2700, 20000, sport=Sport.CYCLING
    )
    assert find_possible_duplicates([GARMIN_RUN, ride]) == []


def test_small_overlap_is_not_a_duplicate():
    # Starts 40 min into a 45 min run: overlap 5 min of a 30 min run (< 50%).
    later = make_workout(Source.APPLE_HEALTH, "2026-11-17T10:10:00+00:00", 1800, 5000)
    assert find_possible_duplicates([GARMIN_RUN, later]) == []


def test_missing_duration_falls_back_to_start_time():
    no_duration = make_workout(Source.APPLE_HEALTH, "2026-11-17T09:33:00+00:00", None, 8400)
    far = make_workout(
        Source.APPLE_HEALTH, "2026-11-17T09:40:00+00:00", None, 8400, source_id="far"
    )
    pairs = find_possible_duplicates([GARMIN_RUN, no_duration, far])
    assert [p.second.source_id for p in pairs] == [no_duration.source_id]
    assert pairs[0].overlap_ratio is None


def test_flag_policy_withholds_combined_total():
    s = summarize([GARMIN_RUN, APPLE_SAME_RUN], WEEK)
    assert s.combined is None
    assert "duplicate" in s.combined_withheld_reason
    # Per-source totals are still available.
    assert s.by_source[Source.GARMIN].distance_m == 8420
    assert s.by_source[Source.APPLE_HEALTH].distance_m == 8390


def test_count_all_policy_adds_everything():
    s = summarize([GARMIN_RUN, APPLE_SAME_RUN], WEEK, duplicate_policy=DuplicatePolicy.COUNT_ALL)
    assert s.combined.distance_m == 8420 + 8390


@pytest.mark.parametrize(
    ("policy", "kept_distance", "excluded_source"),
    [
        (DuplicatePolicy.PREFER_GARMIN, 8420, Source.APPLE_HEALTH),
        (DuplicatePolicy.PREFER_APPLE_HEALTH, 8390, Source.GARMIN),
    ],
)
def test_prefer_policies_keep_one_record_per_pair(policy, kept_distance, excluded_source):
    extra = make_workout(
        Source.APPLE_HEALTH, "2026-11-20T09:00:00+00:00", 1500, 4000, source_id="extra"
    )
    s = summarize([GARMIN_RUN, APPLE_SAME_RUN, extra], WEEK, duplicate_policy=policy)
    assert s.combined.workout_count == 2
    assert s.combined.distance_m == kept_distance + 4000
    assert [w.source for w in s.excluded_from_combined] == [excluded_source]


# --- pace and comparisons ------------------------------------------------------------------


def test_pace_is_total_time_over_total_distance_of_complete_workouts():
    t = totals(
        [
            make_workout(duration_s=1500, distance_m=5000, source_id="a"),  # 5:00 /km
            make_workout(duration_s=3600, distance_m=10000, source_id="b"),  # 6:00 /km
            make_workout(duration_s=None, distance_m=3000, source_id="c"),  # no pace
            make_workout(duration_s=900, distance_m=None, source_id="d"),  # no pace
        ]
    )
    assert t.pace_s_per_km == pytest.approx((1500 + 3600) / 15)  # 340 s/km, not the mean 330
    assert t.pace_workout_count == 2
    assert t.longest_distance_m == 10000


def test_pace_unavailable_without_complete_workouts():
    t = totals([make_workout(distance_m=None), make_workout(distance_m=0.0, source_id="z")])
    assert t.pace_s_per_km is None
    assert t.pace_workout_count == 0


def test_delta():
    assert Delta(13440, 10600).change == 2840
    assert Delta(13440, 10600).change_pct == pytest.approx(26.79, abs=0.01)
    assert Delta(5, 0).change_pct is None
    assert Delta(None, 10).change is None


PREV_WEEK = previous_equivalent(WEEK)


def test_compare_week_with_previous_week():
    workouts = [
        make_workout(Source.GARMIN, "2026-11-10T09:30:00+00:00", 2475, 7500),
        make_workout(Source.GARMIN, "2026-11-17T09:30:00+00:00", 2710, 8420),
    ]
    c = compare(summarize(workouts, WEEK), summarize(workouts, PREV_WEEK))
    garmin = c.by_source[Source.GARMIN]
    assert garmin["distance_m"].change == pytest.approx(920)
    assert garmin["pace_s_per_km"].change == pytest.approx(2710 / 8.42 - 330)
    assert c.combined["workout_count"].change == 0


def test_compare_withholds_combined_when_a_period_has_duplicates():
    workouts = [GARMIN_RUN, APPLE_SAME_RUN]
    c = compare(summarize(workouts, WEEK), summarize(workouts, PREV_WEEK))
    assert c.combined is None
    assert "current" in c.combined_withheld_reason


def test_compare_rejects_different_kinds():
    month = month_containing(date(2026, 11, 18), "America/Sao_Paulo")
    with pytest.raises(ValueError, match="same kind"):
        compare(summarize([], WEEK), summarize([], month))
