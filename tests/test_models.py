from datetime import UTC, datetime, timedelta

import pytest
from helpers import make_workout

from openclock.models import Source, Sport, Workout


def test_start_is_normalized_to_utc():
    w = make_workout(start="2026-11-17T06:30:00-03:00")
    assert w.start == datetime(2026, 11, 17, 9, 30, tzinfo=UTC)
    assert w.start.utcoffset() == timedelta(0)


def test_naive_start_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        Workout(Source.GARMIN, "x", Sport.RUNNING, datetime(2026, 11, 17), 1.0, 1.0, "f")


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_invalid_metrics_are_rejected(bad):
    with pytest.raises(ValueError):
        make_workout(distance_m=bad)


def test_missing_metrics_stay_none():
    w = make_workout(duration_s=None, distance_m=None)
    assert w.duration_s is None
    assert w.distance_m is None
    assert w.end is None


def test_end_and_key():
    w = make_workout(start="2026-11-17T09:30:00+00:00", duration_s=600, source_id="abc")
    assert w.end == datetime(2026, 11, 17, 9, 40, tzinfo=UTC)
    assert w.key == (Source.GARMIN, "abc")
