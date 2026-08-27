from pathlib import Path

from app.normalize import cluster_genres
from app.xml_parser import parse_collection

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rekordbox.xml"


def _cluster_by_label(clusters, label):
    for c in clusters:
        if label in c.raw_labels:
            return c
    return None


def test_afro_house_variants_cluster_together():
    tracks = parse_collection(FIXTURE)
    clusters, _ = cluster_genres(tracks)
    afro = _cluster_by_label(clusters, "Afro House")
    assert afro is not None
    assert set(afro.raw_labels) == {"Afro House", "Afrohouse", "Afro-House", "Afro"}
    assert len(afro.track_ids) == 4
    assert afro.canonical_name == "Afro House"


def test_melodic_variants_cluster_together():
    tracks = parse_collection(FIXTURE)
    clusters, _ = cluster_genres(tracks)
    melodic = _cluster_by_label(clusters, "Melodic")
    assert melodic is not None
    assert set(melodic.raw_labels) == {"Melodic House", "Melodic"}
    assert melodic.canonical_name == "Melodic House"


def test_techno_is_its_own_cluster_no_false_merge():
    tracks = parse_collection(FIXTURE)
    clusters, _ = cluster_genres(tracks)
    techno = _cluster_by_label(clusters, "Techno")
    assert techno is not None
    assert techno.raw_labels == ["Techno"]
    assert len(techno.track_ids) == 2
    # "Techno" must not have absorbed "Afro House" or "Melodic House" --
    # the base-genre word shouldn't swallow unrelated compound genres.
    assert "Afro House" not in techno.raw_labels
    assert "Melodic House" not in techno.raw_labels


def test_house_does_not_swallow_compound_genres():
    """Regression guard for the exact false-merge failure mode the plan
    calls out: a generic trailing base-genre word ('House') must not
    absorb every compound genre that happens to end with it."""
    tracks = parse_collection(FIXTURE)
    tracks = list(tracks) + [
        type(tracks[0])(track_id="99", name="X", artist="Y", genre="House", location="/x.mp3")
    ]
    clusters, _ = cluster_genres(tracks)
    house = _cluster_by_label(clusters, "House")
    assert house is not None
    assert house.raw_labels == ["House"]


def test_blank_and_unknown_genres_are_unlabeled_not_clustered():
    tracks = parse_collection(FIXTURE)
    clusters, unlabeled = cluster_genres(tracks)
    assert "9" in unlabeled  # Genre="Unknown"
    assert "10" in unlabeled  # Genre=""
    for c in clusters:
        assert "9" not in c.track_ids
        assert "10" not in c.track_ids


def test_every_labeled_track_appears_exactly_once():
    tracks = parse_collection(FIXTURE)
    clusters, unlabeled = cluster_genres(tracks)
    all_clustered_ids = [tid for c in clusters for tid in c.track_ids]
    assert len(all_clustered_ids) == len(set(all_clustered_ids))
    assert len(all_clustered_ids) + len(unlabeled) == len(tracks)
