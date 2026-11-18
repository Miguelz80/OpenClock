"""Garmin FIT activity importer, built on Garmin's official FIT Python SDK.

One ``Workout`` is produced per ``session`` message:

- ``start``       <- ``session.start_time``
- ``duration_s``  <- ``session.total_timer_time`` (active time, pauses excluded)
- ``distance_m``  <- ``session.total_distance`` (the SDK applies the FIT scale, so meters)
- ``source_id``   <- ``file_id.serial_number`` + ``file_id.time_created`` + session index,
  so re-importing the same file (or a renamed copy) yields the same identifiers.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from openclock.importers import FileImportError, ImportResult
from openclock.models import Source, Sport, Workout

_SPORTS = {
    "running": Sport.RUNNING,
    "walking": Sport.WALKING,
    "cycling": Sport.CYCLING,
    "e_biking": Sport.CYCLING,
    "swimming": Sport.SWIMMING,
}


def _sport(value: Any) -> Sport:
    return _SPORTS.get(str(value), Sport.OTHER) if value is not None else Sport.OTHER


def _number(value: Any) -> float | None:
    # The SDK omits fields that hold FIT's "invalid" marker, so absence means unavailable.
    return float(value) if isinstance(value, int | float) else None


def _file_prefix(file_id: dict[str, Any], data: bytes) -> str:
    serial = file_id.get("serial_number")
    created = file_id.get("time_created")
    if serial is not None and isinstance(created, datetime):
        return f"{serial}-{int(created.timestamp())}"
    # Without device identity, fall back to the content hash: stable for identical files.
    return "sha256-" + hashlib.sha256(data).hexdigest()[:16]


def parse_fit_bytes(data: bytes, source_file: str) -> ImportResult:
    """Decode FIT ``data``. Raises ``FileImportError`` if the file is not valid FIT."""
    if not Decoder(Stream.from_byte_array(bytearray(data))).is_fit():
        raise FileImportError(f"{source_file}: not a FIT file")
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    if errors:
        raise FileImportError(f"{source_file}: {errors[0]}")

    file_ids = messages.get("file_id_mesgs", [])
    file_id = file_ids[0] if file_ids else {}
    if file_id.get("type") not in (None, "activity"):
        raise FileImportError(
            f"{source_file}: FIT file type {file_id.get('type')!r} is not an activity"
        )

    prefix = _file_prefix(file_id, data)
    result = ImportResult()
    for position, session in enumerate(messages.get("session_mesgs", [])):
        index = session.get("message_index", position)
        start = session.get("start_time")
        if not isinstance(start, datetime):
            result.warnings.append(f"{source_file}: session {index} has no start_time; skipped")
            continue
        result.workouts.append(
            Workout(
                source=Source.GARMIN,
                source_id=f"{prefix}-s{index}",
                sport=_sport(session.get("sport")),
                start=start,
                duration_s=_number(session.get("total_timer_time")),
                distance_m=_number(session.get("total_distance")),
                source_file=source_file,
                raw_sport=str(session.get("sport")) if session.get("sport") is not None else None,
            )
        )
    if not result.workouts and not result.warnings:
        result.warnings.append(f"{source_file}: no sessions found")
    return result


def import_fit(path: str | Path) -> ImportResult:
    path = Path(path)
    return parse_fit_bytes(path.read_bytes(), source_file=path.name)
