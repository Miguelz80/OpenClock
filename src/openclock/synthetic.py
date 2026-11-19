"""Synthetic sample files for the demo and tests. All data here is fictional.

Regenerate the committed samples with::

    python -m openclock.synthetic samples/
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import quoteattr

from garmin_fit_sdk import Encoder, Profile

_MESG = Profile["mesg_num"]

#: Fictional device serial number used in every synthetic Garmin file.
SYNTHETIC_SERIAL = 3_999_999_901


@dataclass(frozen=True, slots=True)
class FitSession:
    start: datetime
    timer_s: float | None
    distance_m: float | None
    sport: str = "running"
    elapsed_s: float | None = None


def fit_bytes(
    sessions: list[FitSession],
    serial: int | None = SYNTHETIC_SERIAL,
    time_created: datetime | None = None,
) -> bytes:
    """Encode a minimal FIT activity file (file_id, sessions, activity) with the official SDK."""
    if not sessions:
        raise ValueError("at least one session is required")
    created = time_created or sessions[0].start
    encoder = Encoder()
    file_id = {
        "mesg_num": _MESG["FILE_ID"],
        "type": "activity",
        "manufacturer": "development",
        "product": 0,
        "time_created": created,
    }
    if serial is not None:
        file_id["serial_number"] = serial
    encoder.write_mesg(file_id)

    last_end = created
    for index, s in enumerate(sessions):
        active = s.timer_s or 0.0
        end = s.start + timedelta(seconds=s.elapsed_s or active)
        last_end = max(last_end, end)
        mesg = {
            "mesg_num": _MESG["SESSION"],
            "message_index": index,
            "timestamp": end,
            "start_time": s.start,
            "sport": s.sport,
            "event": "session",
            "event_type": "stop",
        }
        if s.timer_s is not None:
            mesg["total_timer_time"] = s.timer_s
            mesg["total_elapsed_time"] = s.elapsed_s if s.elapsed_s is not None else s.timer_s
        if s.distance_m is not None:
            mesg["total_distance"] = s.distance_m
        encoder.write_mesg(mesg)

    encoder.write_mesg(
        {
            "mesg_num": _MESG["ACTIVITY"],
            "timestamp": last_end,
            "num_sessions": len(sessions),
            "type": "manual",
            "event": "activity",
            "event_type": "stop",
        }
    )
    return encoder.close()


@dataclass(frozen=True, slots=True)
class AppleWorkout:
    """One ``<Workout>`` for a synthetic Apple Health export.

    ``duration`` and ``distance`` are written in ``duration_unit`` / ``distance_unit`` exactly as
    given, so tests can exercise unit conversion. ``legacy=True`` writes the pre-iOS 16
    ``totalDistance`` attributes instead of a ``<WorkoutStatistics>`` child.
    """

    start: datetime
    end: datetime
    duration: float | None
    distance: float | None
    activity: str = "HKWorkoutActivityTypeRunning"
    duration_unit: str = "min"
    distance_unit: str = "km"
    source_name: str = "Synthetic Apple Watch"
    legacy: bool = False


def _apple_date(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S %z")


def _attrs(**values: object) -> str:
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in values.items() if v is not None)


_APPLE_DTD = """<!DOCTYPE HealthData [
<!-- Synthetic export in the shape of the Health app's export.xml -->
<!ELEMENT HealthData (ExportDate,Me,(Record|Workout)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
]>"""


def apple_health_xml(workouts: list[AppleWorkout], exported: datetime | None = None) -> str:
    """Build a synthetic Apple Health ``export.xml`` document."""
    exported = exported or max((w.end for w in workouts), default=datetime(2026, 1, 1))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        _APPLE_DTD,
        '<HealthData locale="en_US">',
        f" <ExportDate {_attrs(value=_apple_date(exported))}/>",
        ' <Me HKCharacteristicTypeIdentifierDateOfBirth="" '
        'HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>',
    ]
    for w in workouts:
        # A heart-rate sample next to each workout: real exports are mostly <Record>s.
        lines.append(
            " <Record "
            + _attrs(
                type="HKQuantityTypeIdentifierHeartRate",
                sourceName=w.source_name,
                unit="count/min",
                creationDate=_apple_date(w.end),
                startDate=_apple_date(w.start),
                endDate=_apple_date(w.start),
                value=140,
            )
            + "/>"
        )
        attrs = {
            "workoutActivityType": w.activity,
            "duration": w.duration,
            "durationUnit": w.duration_unit if w.duration is not None else None,
            "sourceName": w.source_name,
            "sourceVersion": "11.0",
            "creationDate": _apple_date(w.end),
            "startDate": _apple_date(w.start),
            "endDate": _apple_date(w.end),
        }
        if w.legacy and w.distance is not None:
            attrs["totalDistance"] = w.distance
            attrs["totalDistanceUnit"] = w.distance_unit
        lines.append(f" <Workout {_attrs(**attrs)}>")
        lines.append('  <MetadataEntry key="HKIndoorWorkout" value="0"/>')
        if not w.legacy and w.distance is not None:
            stat = _attrs(
                type="HKQuantityTypeIdentifierDistanceWalkingRunning",
                startDate=_apple_date(w.start),
                endDate=_apple_date(w.end),
                sum=w.distance,
                unit=w.distance_unit,
            )
            lines.append(f"  <WorkoutStatistics {stat}/>")
        lines.append(" </Workout>")
    lines.append("</HealthData>")
    return "\n".join(lines) + "\n"


# --- Demo samples --------------------------------------------------------------------------
# Week of Monday 2026-11-16 in America/Sao_Paulo (UTC-03:00, no DST).

GARMIN_DEMO_FILE = "garmin_run_2026-11-17.fit"
#: Tuesday 2026-11-17 06:30 in São Paulo: 8.42 km in 45:10 of active time (45:50 elapsed).
GARMIN_DEMO_SESSION = FitSession(
    start=datetime.fromisoformat("2026-11-17T06:30:00-03:00"),
    timer_s=2710.0,
    elapsed_s=2750.0,
    distance_m=8420.0,
)

APPLE_DEMO_FILE = "apple_health_export_sample.xml"
APPLE_DEMO_WORKOUTS = [
    #: Sunday 2026-11-15 22:10 in São Paulo (= Monday 01:10 UTC): belongs to the PREVIOUS week.
    AppleWorkout(
        start=datetime.fromisoformat("2026-11-15T22:10:00-03:00"),
        end=datetime.fromisoformat("2026-11-15T22:29:00-03:00"),
        duration=18.5,
        distance=3.1,
    ),
    #: Thursday 2026-11-19 18:05 in São Paulo: 5.02 km in 28:45. Counted this week.
    AppleWorkout(
        start=datetime.fromisoformat("2026-11-19T18:05:00-03:00"),
        end=datetime.fromisoformat("2026-11-19T18:34:20-03:00"),
        duration=28.75,
        distance=5.02,
    ),
    #: Saturday 2026-11-21 09:00 in São Paulo: a walk, so not part of the running total.
    AppleWorkout(
        start=datetime.fromisoformat("2026-11-21T09:00:00-03:00"),
        end=datetime.fromisoformat("2026-11-21T09:40:00-03:00"),
        duration=40.0,
        distance=3.2,
        activity="HKWorkoutActivityTypeWalking",
    ),
]
APPLE_DEMO_EXPORTED = datetime.fromisoformat("2026-11-22T20:00:00-03:00")


def write_samples(directory: str | Path) -> list[Path]:
    """Write the demo sample files into ``directory`` and return their paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    garmin = directory / GARMIN_DEMO_FILE
    garmin.write_bytes(fit_bytes([GARMIN_DEMO_SESSION]))
    apple = directory / APPLE_DEMO_FILE
    apple.write_text(apple_health_xml(APPLE_DEMO_WORKOUTS, APPLE_DEMO_EXPORTED), encoding="utf-8")
    return [garmin, apple]


if __name__ == "__main__":  # pragma: no cover
    for written in write_samples(sys.argv[1] if len(sys.argv) > 1 else "samples"):
        print(f"wrote {written}")
