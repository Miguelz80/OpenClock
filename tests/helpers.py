"""Small builders for synthetic workouts used across tests."""

from __future__ import annotations

from datetime import datetime

from openclock.models import Source, Sport, Workout


def make_workout(
    source: Source = Source.GARMIN,
    start: str = "2026-11-17T09:30:00+00:00",
    duration_s: float | None = 1800.0,
    distance_m: float | None = 5000.0,
    sport: Sport = Sport.RUNNING,
    source_id: str | None = None,
) -> Workout:
    return Workout(
        source=source,
        source_id=source_id or f"{source.value}-{start}",
        sport=sport,
        start=datetime.fromisoformat(start),
        duration_s=duration_s,
        distance_m=distance_m,
        source_file="synthetic",
    )
