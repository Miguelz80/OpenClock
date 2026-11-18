import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from garmin_fit_sdk import Encoder, Profile

from openclock.importers import FileImportError
from openclock.importers.fit import import_fit, parse_fit_bytes
from openclock.models import Source, Sport
from openclock.store import WorkoutStore
from openclock.synthetic import GARMIN_DEMO_FILE, FitSession, fit_bytes, write_samples

SAMPLES = Path(__file__).parent.parent / "samples"
START = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)


def test_demo_samples_are_reproducible_from_generator(tmp_path):
    generated = [p for p in write_samples(tmp_path) if p.suffix == ".fit"]
    assert len(generated) == 2
    for path in generated:
        assert path.read_bytes() == (SAMPLES / path.name).read_bytes(), path.name


def test_demo_sample_values():
    (w,) = import_fit(SAMPLES / GARMIN_DEMO_FILE).workouts
    assert w.source == Source.GARMIN
    assert w.sport == Sport.RUNNING
    assert w.start == START
    assert w.duration_s == 2710.0  # timer time, not the 2750 s elapsed
    assert w.distance_m == 8420.0
    assert w.source_file == GARMIN_DEMO_FILE
    assert w.source_id == "3999999901-1794907800-s0"


def test_reimport_and_renamed_copy_keep_the_same_ids(tmp_path):
    copy = tmp_path / "renamed.fit"
    shutil.copy(SAMPLES / GARMIN_DEMO_FILE, copy)
    store = WorkoutStore()
    store.add_all(import_fit(SAMPLES / GARMIN_DEMO_FILE).workouts)
    second = store.add_all(import_fit(SAMPLES / GARMIN_DEMO_FILE).workouts)
    third = store.add_all(import_fit(copy).workouts)
    assert (second.added, third.added) == (0, 0)
    assert len(store) == 1


def test_units_keep_centimeter_and_millisecond_precision():
    data = fit_bytes([FitSession(START, timer_s=1234.567, distance_m=5012.34)])
    (w,) = parse_fit_bytes(data, "x.fit").workouts
    assert w.distance_m == pytest.approx(5012.34)
    assert w.duration_s == pytest.approx(1234.567)


def test_missing_distance_is_unavailable():
    data = fit_bytes([FitSession(START, timer_s=1800.0, distance_m=None)])
    (w,) = parse_fit_bytes(data, "treadmill.fit").workouts
    assert w.distance_m is None
    assert w.duration_s == 1800.0


def test_missing_duration_is_unavailable():
    data = fit_bytes([FitSession(START, timer_s=None, distance_m=3000.0)])
    (w,) = parse_fit_bytes(data, "x.fit").workouts
    assert w.duration_s is None


def test_multisport_file_gives_one_workout_per_session():
    data = fit_bytes(
        [
            FitSession(START, timer_s=1200.0, distance_m=10000.0, sport="cycling"),
            FitSession(datetime(2026, 11, 17, 10, 0, tzinfo=UTC), 900.0, 3000.0, "running"),
        ]
    )
    workouts = parse_fit_bytes(data, "brick.fit").workouts
    assert [w.sport for w in workouts] == [Sport.CYCLING, Sport.RUNNING]
    assert len({w.source_id for w in workouts}) == 2


def test_unknown_sport_maps_to_other_and_keeps_raw_label():
    data = fit_bytes([FitSession(START, 600.0, None, sport="rowing")])
    (w,) = parse_fit_bytes(data, "x.fit").workouts
    assert w.sport == Sport.OTHER
    assert w.raw_sport == "rowing"


def test_file_without_device_identity_uses_content_hash():
    data = fit_bytes([FitSession(START, 600.0, 1000.0)], serial=None)
    first = parse_fit_bytes(data, "a.fit").workouts[0]
    again = parse_fit_bytes(data, "b.fit").workouts[0]
    assert first.source_id.startswith("sha256-")
    assert first.source_id == again.source_id


def test_session_without_start_time_is_skipped_with_warning():
    mesg = Profile["mesg_num"]
    encoder = Encoder()
    encoder.write_mesg(
        {"mesg_num": mesg["FILE_ID"], "type": "activity", "serial_number": 1, "time_created": START}
    )
    encoder.write_mesg({"mesg_num": mesg["SESSION"], "message_index": 0, "total_distance": 1.0})
    result = parse_fit_bytes(encoder.close(), "nostart.fit")
    assert result.workouts == []
    assert "no start_time" in result.warnings[0]


def test_corrupted_file_is_rejected():
    data = bytearray(fit_bytes([FitSession(START, 600.0, 1000.0)]))
    data[-5] ^= 0xFF
    with pytest.raises(FileImportError, match="CRC"):
        parse_fit_bytes(bytes(data), "broken.fit")


def test_non_fit_file_is_rejected():
    with pytest.raises(FileImportError, match="not a FIT file"):
        parse_fit_bytes(b"<xml/>", "wrong.fit")
