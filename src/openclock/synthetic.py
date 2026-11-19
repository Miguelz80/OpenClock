"""Synthetic sample files for the demo and tests. All data here is fictional.

Regenerate the committed samples with::

    python -m openclock.synthetic samples/
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

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


def write_samples(directory: str | Path) -> list[Path]:
    """Write the demo sample files into ``directory`` and return their paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    garmin = directory / GARMIN_DEMO_FILE
    garmin.write_bytes(fit_bytes([GARMIN_DEMO_SESSION]))
    return [garmin]


if __name__ == "__main__":  # pragma: no cover
    for written in write_samples(sys.argv[1] if len(sys.argv) > 1 else "samples"):
        print(f"wrote {written}")
