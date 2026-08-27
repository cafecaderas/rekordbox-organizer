from pathlib import Path

import pytest

from app.session import Session

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rekordbox.xml"


def _fresh_session() -> Session:
    s = Session()
    s.load(str(FIXTURE))
    return s


def _find_cluster_id(session: Session, canonical_name: str) -> str:
    return next(c.id for c in session.clusters.values() if c.canonical_name == canonical_name)


def test_rename_changes_canonical_name():
    s = _fresh_session()
    cid = _find_cluster_id(s, "Afro House")
    s.rename(cid, "Afro House (Deep)")
    assert s.clusters[cid].canonical_name == "Afro House (Deep)"


def test_rename_blank_is_ignored():
    s = _fresh_session()
    cid = _find_cluster_id(s, "Afro House")
    s.rename(cid, "   ")
    assert s.clusters[cid].canonical_name == "Afro House"


def test_set_status_approved_then_included_in_approved_clusters():
    s = _fresh_session()
    cid = _find_cluster_id(s, "Techno")
    s.set_status(cid, "approved")
    assert s.clusters[cid] in s.approved_clusters()


def test_merge_combines_tracks_and_removes_source_cluster():
    s = _fresh_session()
    afro_id = _find_cluster_id(s, "Afro House")
    melodic_id = _find_cluster_id(s, "Melodic House")
    afro_track_count = len(s.clusters[afro_id].track_ids)
    melodic_track_count = len(s.clusters[melodic_id].track_ids)

    merged = s.merge(afro_id, melodic_id)

    assert merged.id == afro_id
    assert len(merged.track_ids) == afro_track_count + melodic_track_count
    assert melodic_id not in s.clusters
    assert set(merged.raw_labels) >= {"Afro House", "Melodic House"}


def test_merge_with_self_raises():
    s = _fresh_session()
    afro_id = _find_cluster_id(s, "Afro House")
    with pytest.raises(ValueError):
        s.merge(afro_id, afro_id)


def test_split_moves_only_matching_tracks_into_new_cluster():
    s = _fresh_session()
    afro_id = _find_cluster_id(s, "Afro House")
    original_count = len(s.clusters[afro_id].track_ids)

    new_cluster = s.split(afro_id, "Afro")

    assert new_cluster.canonical_name == "Afro"
    assert len(new_cluster.track_ids) == 1
    assert "Afro" not in s.clusters[afro_id].raw_labels
    assert len(s.clusters[afro_id].track_ids) == original_count - 1
    assert new_cluster.status == "pending"


def test_split_last_remaining_label_raises():
    s = _fresh_session()
    techno_id = _find_cluster_id(s, "Techno")
    with pytest.raises(ValueError):
        s.split(techno_id, "Techno")


def test_split_unknown_label_raises():
    s = _fresh_session()
    afro_id = _find_cluster_id(s, "Afro House")
    with pytest.raises(ValueError):
        s.split(afro_id, "Not A Real Label")


def test_unlabeled_tracks_never_appear_in_any_cluster():
    s = _fresh_session()
    all_clustered = {tid for c in s.clusters.values() for tid in c.track_ids}
    assert all_clustered.isdisjoint(s.unlabeled_track_ids)
