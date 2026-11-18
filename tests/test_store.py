from helpers import make_workout

from openclock.models import Source
from openclock.store import WorkoutStore


def test_reimport_replaces_instead_of_adding():
    store = WorkoutStore()
    batch = [make_workout(source_id="a"), make_workout(source_id="b")]
    first = store.add_all(batch)
    second = store.add_all(batch)
    assert (first.added, first.replaced) == (2, 0)
    assert (second.added, second.replaced) == (0, 2)
    assert len(store) == 2


def test_same_id_in_different_sources_is_kept_apart():
    store = WorkoutStore()
    store.add(make_workout(source=Source.GARMIN, source_id="same"))
    store.add(make_workout(source=Source.APPLE_HEALTH, source_id="same"))
    assert len(store) == 2


def test_all_is_sorted_by_start():
    store = WorkoutStore()
    store.add(make_workout(start="2026-11-19T09:00:00+00:00", source_id="later"))
    store.add(make_workout(start="2026-11-17T09:00:00+00:00", source_id="earlier"))
    assert [w.source_id for w in store.all()] == ["earlier", "later"]
