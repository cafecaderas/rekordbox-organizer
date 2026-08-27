from app.assignment_store import AssignmentStore


def _store(tmp_path):
    return AssignmentStore(tmp_path / "assignments.json")


def test_map_genre_labels_resolves_for_matching_track(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House", "Afrohouse", "Afro"], "tx-1")
    assert store.resolve("Afro House", "/x/a.mp3") == "tx-1"
    assert store.resolve("Afro", "/x/b.mp3") == "tx-1"


def test_unmapped_genre_resolves_to_none(tmp_path):
    store = _store(tmp_path)
    assert store.resolve("Techno", "/x/a.mp3") is None


def test_track_override_wins_over_genre_mapping(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House"], "tx-1")
    store.set_track_override("/x/a.mp3", "tx-2")
    assert store.resolve("Afro House", "/x/a.mp3") == "tx-2"
    # A different track with the same genre still follows the bulk mapping.
    assert store.resolve("Afro House", "/x/b.mp3") == "tx-1"


def test_clear_track_override_falls_back_to_genre_mapping(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House"], "tx-1")
    store.set_track_override("/x/a.mp3", "tx-2")
    store.clear_track_override("/x/a.mp3")
    assert store.resolve("Afro House", "/x/a.mp3") == "tx-1"


def test_unmap_genre_labels_removes_mapping(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House"], "tx-1")
    store.unmap_genre_labels(["Afro House"])
    assert store.resolve("Afro House", "/x/a.mp3") is None


def test_track_with_no_genre_can_still_be_overridden(tmp_path):
    """The whole point of overrides: a track with a blank genre has no
    label to map, but can still be pinned directly to a category."""
    store = _store(tmp_path)
    store.set_track_override("/x/unlabeled.mp3", "tx-3")
    assert store.resolve("", "/x/unlabeled.mp3") == "tx-3"


def test_retarget_merge_repoints_mapping_and_overrides(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House"], "tx-old")
    store.set_track_override("/x/a.mp3", "tx-old")

    store.retarget("tx-old", "tx-new")

    assert store.resolve("Afro House", "/x/z.mp3") == "tx-new"
    assert store.resolve("Afro House", "/x/a.mp3") == "tx-new"


def test_retarget_delete_clears_mapping_and_overrides(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Afro House"], "tx-old")
    store.set_track_override("/x/a.mp3", "tx-old")

    store.retarget("tx-old", None)

    assert store.resolve("Afro House", "/x/z.mp3") is None
    assert store.resolve("Afro House", "/x/a.mp3") is None


def test_retarget_does_not_touch_unrelated_entries(tmp_path):
    store = _store(tmp_path)
    store.map_genre_labels(["Techno"], "tx-keep")
    store.retarget("tx-old", "tx-new")
    assert store.resolve("Techno", "/x/z.mp3") == "tx-keep"


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "assignments.json"
    store1 = AssignmentStore(path)
    store1.map_genre_labels(["Afro House"], "tx-1")
    store1.set_track_override("/x/a.mp3", "tx-2")

    store2 = AssignmentStore(path)
    assert store2.resolve("Afro House", "/x/z.mp3") == "tx-1"
    assert store2.resolve("Afro House", "/x/a.mp3") == "tx-2"
