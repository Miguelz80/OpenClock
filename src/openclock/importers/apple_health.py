"""Apple Health ``export.xml`` importer.

Reads the file produced by the Health app ("Export All Health Data"), either the extracted
``export.xml`` or the ``export.zip`` archive. The file is streamed, since real exports can be
hundreds of megabytes, and parsed through ``defusedxml`` to block entity-expansion attacks.

One ``Workout`` is produced per ``<Workout>`` element:

- ``start``       <- ``startDate`` (e.g. ``2026-11-19 18:05:00 -0300``)
- ``duration_s``  <- ``duration`` + ``durationUnit`` (Apple's active duration)
- ``distance_m``  <- a ``<WorkoutStatistics type="HKQuantityTypeIdentifierDistance…">`` child
  (iOS 16+ exports) or the legacy ``totalDistance`` / ``totalDistanceUnit`` attributes.
- ``source_id``   <- hash of activity type, source name, start and end. The export carries no
  workout UUID, so this is the most stable identity available.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse

from openclock.importers import FileImportError, ImportResult
from openclock.models import Source, Sport, Workout

_SPORTS = {
    "HKWorkoutActivityTypeRunning": Sport.RUNNING,
    "HKWorkoutActivityTypeWalking": Sport.WALKING,
    "HKWorkoutActivityTypeCycling": Sport.CYCLING,
    "HKWorkoutActivityTypeSwimming": Sport.SWIMMING,
}

#: Preferred distance statistic for each sport, when a workout has several.
_DISTANCE_TYPE = {
    Sport.RUNNING: "HKQuantityTypeIdentifierDistanceWalkingRunning",
    Sport.WALKING: "HKQuantityTypeIdentifierDistanceWalkingRunning",
    Sport.CYCLING: "HKQuantityTypeIdentifierDistanceCycling",
    Sport.SWIMMING: "HKQuantityTypeIdentifierDistanceSwimming",
}
_DISTANCE_PREFIX = "HKQuantityTypeIdentifierDistance"

#: Length units found in Health exports, in meters.
LENGTH_UNITS = {"m": 1.0, "cm": 0.01, "km": 1000.0, "mi": 1609.344, "ft": 0.3048, "yd": 0.9144}
#: Time units found in Health exports, in seconds.
TIME_UNITS = {"s": 1.0, "sec": 1.0, "min": 60.0, "hr": 3600.0, "h": 3600.0}

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"


def parse_apple_date(value: str) -> datetime:
    """``"2026-11-19 18:05:00 -0300"`` -> aware datetime."""
    return datetime.strptime(value.strip(), _DATE_FORMAT)


def _convert(value: str | None, unit: str | None, table: dict[str, float]) -> float | None:
    """Convert ``value`` in ``unit``. Returns ``None`` if absent; raises on unknown units."""
    if value is None or value == "":
        return None
    if unit not in table:
        raise ValueError(f"unknown unit {unit!r}")
    return float(value) * table[unit]


def _distance(workout: Element, sport: Sport) -> tuple[str | None, str | None]:
    stats = {
        s.get("type"): s
        for s in workout.findall("WorkoutStatistics")
        if (s.get("type") or "").startswith(_DISTANCE_PREFIX) and s.get("sum")
    }
    if stats:
        chosen = stats.get(_DISTANCE_TYPE.get(sport, ""), next(iter(stats.values())))
        return chosen.get("sum"), chosen.get("unit")
    return workout.get("totalDistance"), workout.get("totalDistanceUnit")


def _source_id(activity: str, source_name: str, start: datetime, end: datetime | None) -> str:
    end_text = end.astimezone(UTC).isoformat() if end else ""
    key = f"{activity}|{source_name}|{start.astimezone(UTC).isoformat()}|{end_text}"
    return "hk-" + hashlib.sha256(key.encode()).hexdigest()[:20]


def _workout(elem: Element, source_file: str, warnings: list[str]) -> Workout | None:
    activity = elem.get("workoutActivityType", "")
    label = f"{source_file}: workout {activity or '?'} at {elem.get('startDate')}"
    try:
        start = parse_apple_date(elem.get("startDate", ""))
    except ValueError:
        warnings.append(f"{label}: invalid or missing startDate; skipped")
        return None
    end_raw = elem.get("endDate")
    try:
        end = parse_apple_date(end_raw) if end_raw else None
    except ValueError:
        end = None

    sport = _SPORTS.get(activity, Sport.OTHER)
    try:
        duration = _convert(elem.get("duration"), elem.get("durationUnit"), TIME_UNITS)
    except ValueError as exc:
        warnings.append(f"{label}: duration {exc}; reported as unavailable")
        duration = None
    value, unit = _distance(elem, sport)
    try:
        distance = _convert(value, unit, LENGTH_UNITS)
    except ValueError as exc:
        warnings.append(f"{label}: distance {exc}; reported as unavailable")
        distance = None

    return Workout(
        source=Source.APPLE_HEALTH,
        source_id=_source_id(activity, elem.get("sourceName", ""), start, end),
        sport=sport,
        start=start,
        duration_s=duration,
        distance_m=distance,
        source_file=source_file,
        raw_sport=activity or None,
    )


@contextmanager
def _open_export(path: Path) -> Iterator[IO[bytes]]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [
                n for n in archive.namelist() if n.endswith("/export.xml") or n == "export.xml"
            ]
            if not names:
                raise FileImportError(f"{path.name}: no export.xml inside the archive")
            with archive.open(names[0]) as handle:
                yield handle
    else:
        with path.open("rb") as handle:
            yield handle


def parse_apple_health(stream: IO[bytes], source_file: str) -> ImportResult:
    """Stream-parse an Apple Health export. Raises ``FileImportError`` if it is not one."""
    result = ImportResult()
    depth = 0
    root: Element | None = None
    try:
        for event, elem in iterparse(stream, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = elem
                    if elem.tag != "HealthData":
                        raise FileImportError(
                            f"{source_file}: root element is <{elem.tag}>, expected <HealthData>"
                        )
                depth += 1
                continue
            depth -= 1
            if depth == 1:  # a direct child of <HealthData> is complete
                if elem.tag == "Workout":
                    workout = _workout(elem, source_file, result.warnings)
                    if workout is not None:
                        result.workouts.append(workout)
                root.clear()  # keep memory flat on large exports
    except (ParseError, DefusedXmlException) as exc:
        raise FileImportError(f"{source_file}: invalid XML ({exc})") from exc
    if root is None:
        raise FileImportError(f"{source_file}: empty file")
    return result


def import_apple_health(path: str | Path) -> ImportResult:
    path = Path(path)
    with _open_export(path) as stream:
        return parse_apple_health(stream, source_file=path.name)
