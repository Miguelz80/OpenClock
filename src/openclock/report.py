"""JSON-friendly views of workouts and summaries, shared by the CLI and the MCP server.

Values are rounded only here, at the edge. Internal sums keep full precision.
"""

from __future__ import annotations

from typing import Any

from openclock.metrics import Delta, DuplicateCandidate, PeriodComparison, PeriodSummary, Totals
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


def format_pace(seconds_per_km: float | None) -> str:
    """``329.99`` -> ``"5:30 /km"``; ``None`` -> ``"unavailable"``."""
    if seconds_per_km is None:
        return UNAVAILABLE
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d} /km"


def format_signed_duration(seconds: float | None) -> str:
    """``-905`` -> ``"-0:15:05"``; ``None`` -> ``"unavailable"``."""
    if seconds is None:
        return UNAVAILABLE
    sign = "-" if seconds < 0 else "+"
    return sign + format_duration(abs(seconds))


def _pace(workout: Workout) -> float | None:
    if workout.distance_m and workout.duration_s is not None:
        return workout.duration_s / (workout.distance_m / 1000)
    return None


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
        "pace": format_pace(_pace(workout)),
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
        "avg_pace": format_pace(totals.pace_s_per_km),
        "avg_pace_s_per_km": _s(totals.pace_s_per_km),
        "avg_pace_based_on_workouts": totals.pace_workout_count,
        "longest_km": _km(totals.longest_distance_m),
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


def _rounded(value: float | None, digits: int) -> float | str:
    return UNAVAILABLE if value is None else round(value, digits)


def _deltas_to_dict(deltas: dict[str, Delta]) -> dict[str, Any]:
    count, dist, dur, pace = (
        deltas["workout_count"],
        deltas["distance_m"],
        deltas["duration_s"],
        deltas["pace_s_per_km"],
    )
    pace_change = pace.change
    if pace_change is None:
        direction = UNAVAILABLE
    elif round(pace_change) == 0:
        direction = "same"
    else:
        direction = "faster" if pace_change < 0 else "slower"
    return {
        "workout_count": {
            "current": int(count.current or 0),
            "previous": int(count.previous or 0),
            "change": int(count.change or 0),
        },
        "distance_km": {
            "current": _km(dist.current),
            "previous": _km(dist.previous),
            "change": _km(dist.change),
            "change_pct": _rounded(dist.change_pct, 1),
        },
        "duration": {
            "current": format_duration(dur.current),
            "previous": format_duration(dur.previous),
            "change": format_signed_duration(dur.change),
            "change_s": _s(dur.change),
            "change_pct": _rounded(dur.change_pct, 1),
        },
        "avg_pace": {
            "current": format_pace(pace.current),
            "previous": format_pace(pace.previous),
            "change_s_per_km": _s(pace_change),
            "direction": direction,
        },
    }


def comparison_to_dict(comparison: PeriodComparison) -> dict[str, Any]:
    return {
        "current": summary_to_dict(comparison.current),
        "previous": summary_to_dict(comparison.previous),
        "changes": {
            "by_source": {
                source.value: _deltas_to_dict(d) for source, d in comparison.by_source.items()
            },
            "combined": _deltas_to_dict(comparison.combined) if comparison.combined else None,
            "combined_withheld_reason": comparison.combined_withheld_reason,
        },
    }
