import io
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openclock.importers import FileImportError
from openclock.importers.apple_health import import_apple_health, parse_apple_health
from openclock.models import Source, Sport
from openclock.store import WorkoutStore
from openclock.synthetic import APPLE_DEMO_FILE, AppleWorkout, apple_health_xml, write_samples

SAMPLES = Path(__file__).parent.parent / "samples"
START = datetime.fromisoformat("2026-11-19T18:05:00-03:00")
END = datetime.fromisoformat("2026-11-19T18:34:20-03:00")


def parse(xml: str, name: str = "export.xml"):
    return parse_apple_health(io.BytesIO(xml.encode()), name)


def one(**overrides):
    fields = {"start": START, "end": END, "duration": 28.75, "distance": 5.02} | overrides
    (w,) = parse(apple_health_xml([AppleWorkout(**fields)])).workouts
    return w


def test_demo_sample_is_reproducible_from_generator(tmp_path):
    (generated,) = [p for p in write_samples(tmp_path) if p.suffix == ".xml"]
    assert generated.read_bytes() == (SAMPLES / APPLE_DEMO_FILE).read_bytes()


def test_demo_sample_values():
    result = import_apple_health(SAMPLES / APPLE_DEMO_FILE)
    assert result.warnings == []
    assert [w.sport for w in result.workouts] == [Sport.RUNNING, Sport.RUNNING, Sport.WALKING]
    run = result.workouts[1]
    assert run.source == Source.APPLE_HEALTH
    assert run.start == datetime(2026, 11, 19, 21, 5, tzinfo=UTC)
    assert run.duration_s == pytest.approx(1725.0)  # 28.75 min
    assert run.distance_m == pytest.approx(5020.0)  # 5.02 km
    assert run.source_file == APPLE_DEMO_FILE
    assert run.raw_sport == "HKWorkoutActivityTypeRunning"


def test_reimport_and_copies_keep_the_same_ids(tmp_path):
    copy = tmp_path / "export.xml"
    shutil.copy(SAMPLES / APPLE_DEMO_FILE, copy)
    store = WorkoutStore()
    store.add_all(import_apple_health(SAMPLES / APPLE_DEMO_FILE).workouts)
    again = store.add_all(import_apple_health(SAMPLES / APPLE_DEMO_FILE).workouts)
    copied = store.add_all(import_apple_health(copy).workouts)
    assert (again.added, copied.added) == (0, 0)
    assert len(store) == 3


def test_zip_archive_is_supported(tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(SAMPLES / APPLE_DEMO_FILE, "apple_health_export/export.xml")
    from_zip = import_apple_health(archive).workouts
    from_xml = import_apple_health(SAMPLES / APPLE_DEMO_FILE).workouts
    assert [w.source_id for w in from_zip] == [w.source_id for w in from_xml]


def test_zip_without_export_is_rejected(tmp_path):
    archive = tmp_path / "other.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("readme.txt", "nothing here")
    with pytest.raises(FileImportError, match="no export.xml"):
        import_apple_health(archive)


@pytest.mark.parametrize(
    ("distance", "unit", "meters"),
    [(5.02, "km", 5020.0), (3.1, "mi", 4988.9664), (5020, "m", 5020.0), (1000, "yd", 914.4)],
)
def test_distance_units(distance, unit, meters):
    assert one(distance=distance, distance_unit=unit).distance_m == pytest.approx(meters)


@pytest.mark.parametrize(
    ("duration", "unit", "seconds"),
    [(28.75, "min", 1725.0), (1725, "s", 1725.0), (0.5, "hr", 1800.0)],
)
def test_duration_units(duration, unit, seconds):
    assert one(duration=duration, duration_unit=unit).duration_s == pytest.approx(seconds)


def test_legacy_total_distance_attributes():
    assert one(legacy=True, distance=3.1, distance_unit="mi").distance_m == pytest.approx(4988.9664)


def test_missing_distance_is_unavailable():
    w = one(distance=None)
    assert w.distance_m is None
    assert w.duration_s == pytest.approx(1725.0)


def test_missing_duration_is_unavailable():
    assert one(duration=None).duration_s is None


def test_unknown_unit_is_unavailable_with_warning():
    xml = apple_health_xml([AppleWorkout(START, END, 28.75, 5.02, distance_unit="furlong")])
    result = parse(xml)
    assert result.workouts[0].distance_m is None
    assert "unknown unit 'furlong'" in result.warnings[0]


def test_invalid_start_date_is_skipped_with_warning():
    xml = apple_health_xml([AppleWorkout(START, END, 28.75, 5.02)])
    workout_dates = 'startDate="2026-11-19 18:05:00 -0300" endDate="2026-11-19 18:34:20 -0300">'
    assert xml.count(workout_dates) == 1
    xml = xml.replace(workout_dates, 'startDate="yesterday">')
    result = parse(xml)
    assert result.workouts == []
    assert "invalid or missing startDate" in result.warnings[0]


def test_different_source_apps_get_different_ids():
    a = one(source_name="Synthetic Apple Watch")
    b = one(source_name="Connect")  # e.g. Garmin Connect writing into Apple Health
    assert a.source_id != b.source_id


def test_unknown_activity_maps_to_other():
    w = one(activity="HKWorkoutActivityTypeRowing")
    assert w.sport == Sport.OTHER
    assert w.raw_sport == "HKWorkoutActivityTypeRowing"


def test_wrong_root_element_is_rejected():
    with pytest.raises(FileImportError, match="expected <HealthData>"):
        parse("<gpx></gpx>")


def test_malformed_xml_is_rejected():
    with pytest.raises(FileImportError, match="invalid XML"):
        parse('<HealthData><Workout startDate="x"></HealthData>')


def test_entity_expansion_is_blocked():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE HealthData [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><HealthData>&b;</HealthData>'
    )
    with pytest.raises(FileImportError, match="invalid XML"):
        parse(bomb)
