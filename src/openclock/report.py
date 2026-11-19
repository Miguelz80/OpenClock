"""JSON-friendly views of workouts and summaries, shared by the CLI and the MCP server.

Values are rounded only here, at the edge. Internal sums keep full precision.
"""

from __future__ import annotations

from typing import Any

from openclock.metrics import DuplicateCandidate, PeriodSummary, Totals
from openclock.models import Workout
from openclock.periods import Period, resolve_timezone

UNAVAILABLE = "unavailable"


def format_duration(seconds: float | None) -> str:
    """``3725.4`` -> ``"1:02:05"``; ``None`` -> ``"unavailable"``."""
    if seconds is None:
        return UNAVAILABLE
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _km(meters: float | None) -> float | str:
    return UNAVAILABLE if meters is None else round(meters / 1000, 3)


def _m(meters: float | None) -> float | str:
    return UNAVAILABLE if meters is None else round(meters, 1)


def _s(seconds: float | None) -> float | str:
    return UNAVAILABLE if seconds is None else round(seconds, 1)


def period_to_dict(period: Period) -> dict[str, Any]:
    return {
        "kind": period.kind,
        "timezone": period.timezone,
        "start": period.start.isoformat(),
        "end_exclusive": period.end.isoformat(),
        "first_day": period.first_day.isoformat(),
        "last_day": period.last_day.isoformat(),
    }


def workout_to_dict(workout: Workout, tz_name: str) -> dict[str, Any]:
    tz = resolve_timezone(tz_name)
    unavailable = [
        name
        for name, value in (("duration", workout.duration_s), ("distance", workout.distance_m))
        if value is None
    ]
    return {
        "source": workout.source.value,
        "source_id": workout.source_id,
        "sport": workout.sport.value,
        "raw_sport": workout.raw_sport,
        "start_local": workout.start.astimezone(tz).isoformat(),
        "start_utc": workout.start.isoformat(),
        "duration_s": _s(workout.duration_s),
        "duration": format_duration(workout.duration_s),
        "distance_m": _m(workout.distance_m),
        "distance_km": _km(workout.distance_m),
        "unavailable_metrics": unavailable,
        "source_file": workout.source_file,
    }


def totals_to_dict(totals: Totals) -> dict[str, Any]:
    return {
        "workout_count": totals.workout_count,
        "distance_km": _km(totals.distance_m),
        "distance_m": _m(totals.distance_m),
        "duration": format_duration(totals.duration_s),
        "duration_s": _s(totals.duration_s),
        "workouts_missing_distance": totals.missing_distance,
        "workouts_missing_duration": totals.missing_duration,
    }


def _duplicate_to_dict(pair: DuplicateCandidate) -> dict[str, Any]:
    return {
        "workouts": [
            {"source": w.source.value, "source_id": w.source_id, "source_file": w.source_file}
            for w in (pair.first, pair.second)
        ],
        "overlap_ratio": pair.overlap_ratio,
        "reason": pair.reason,
    }


def summary_to_dict(summary: PeriodSummary) -> dict[str, Any]:
    tz_name = summary.period.timezone
    return {
        "period": period_to_dict(summary.period),
        "sport": summary.sport.value if summary.sport else "all",
        "by_source": {source.value: totals_to_dict(t) for source, t in summary.by_source.items()},
        "sources_without_data": [s.value for s in summary.sources_without_data],
        "possible_duplicates": [_duplicate_to_dict(p) for p in summary.possible_duplicates],
        "duplicate_policy": summary.duplicate_policy.value,
        "combined": totals_to_dict(summary.combined) if summary.combined else None,
        "combined_withheld_reason": summary.combined_withheld_reason,
        "excluded_from_combined": [
            {"source": w.source.value, "source_id": w.source_id}
            for w in summary.excluded_from_combined
        ],
        "workouts": [workout_to_dict(w, tz_name) for w in summary.workouts],
    }
