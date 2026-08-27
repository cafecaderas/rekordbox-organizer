import os
import tempfile
from pathlib import Path

# Must be set before `app.main` is imported: it constructs the taxonomy/
# assignment stores at module load time, and without this they'd read and
# write the real project's data/ directory during test runs.
os.environ["DJ_TOOL_DATA_DIR"] = tempfile.mkdtemp(prefix="dj_tool_test_data_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main as main_module  # noqa: E402
from app.assignment_store import AssignmentStore  # noqa: E402
from app.main import app  # noqa: E402
from app.session import session  # noqa: E402
from app.taxonomy_store import TaxonomyStore  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rekordbox.xml"
FIXTURE_2 = Path(__file__).parent / "fixtures" / "sample_rekordbox_2.xml"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_taxonomy(tmp_path):
    """Give every test a fresh taxonomy/assignment store -- these persist
    to disk by design, so without this, a category created in one test
    would leak into the next."""
    main_module.taxonomy_store = TaxonomyStore(tmp_path / "taxonomy.json")
    main_module.assignment_store = AssignmentStore(tmp_path / "assignments.json")
    yield


def _load():
    return client.post("/api/load", json={"xml_path": str(FIXTURE)})


def test_load_missing_file_returns_404():
    resp = client.post("/api/load", json={"xml_path": "/nonexistent/path.xml"})
    assert resp.status_code == 404


def test_load_valid_fixture_returns_clusters():
    resp = _load()
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_track_count"] == 10
    assert data["unlabeled_track_count"] == 2
    names = {c["canonical_name"] for c in data["clusters"]}
    assert names == {"Afro House", "Melodic House", "Techno"}


def test_full_flow_approve_and_generate(tmp_path):
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")

    approve = client.post(f"/api/clusters/{afro['id']}/status", json={"status": "approved"})
    assert approve.json()["status"] == "approved"

    out_dir = tmp_path / "playlists"
    gen = client.post("/api/generate", json={"output_dir": str(out_dir)})
    assert gen.status_code == 200
    results = gen.json()["generated"]
    assert len(results) == 1
    assert results[0]["canonical_name"] == "Afro House"
    assert results[0]["track_count"] == 4

    written = Path(results[0]["file_path"])
    assert written.exists()
    content = written.read_text()
    assert content.startswith("#EXTM3U\n")
    assert "/Users/dj/Music/Afro/Sundown.mp3" in content


def test_generate_with_no_approved_clusters_returns_400():
    _load()
    for cid in list(session.clusters):
        session.set_status(cid, "pending")
    resp = client.post("/api/generate", json={"output_dir": "output"})
    assert resp.status_code == 400


def test_rename_unknown_cluster_returns_404():
    _load()
    resp = client.post("/api/clusters/does-not-exist/rename", json={"name": "X"})
    assert resp.status_code == 404


def test_invalid_status_value_returns_400():
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    cid = clusters[0]["id"]
    resp = client.post(f"/api/clusters/{cid}/status", json={"status": "bogus"})
    assert resp.status_code == 400


# --- /api/load-upload: the real browser file-picker flow ---


def test_upload_a_different_real_looking_export_not_the_fixture():
    """Proves the pipeline processes whatever file bytes are uploaded --
    not the hardcoded fixture -- by uploading a second, distinct export
    with its own genres and confirming those (and only those) come back."""
    with open(FIXTURE_2, "rb") as f:
        resp = client.post(
            "/api/load-upload",
            files={"file": ("my_real_rekordbox_export.xml", f, "text/xml")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_xml_path"] == "my_real_rekordbox_export.xml"
    assert data["total_track_count"] == 5
    names = {c["canonical_name"] for c in data["clusters"]}
    # Deep House / Deephouse / Deep -> one cluster; Dub Techno / Dub-Techno -> another.
    assert names == {"Deep House", "Dub Techno"}
    deep = next(c for c in data["clusters"] if c["canonical_name"] == "Deep House")
    assert deep["track_count"] == 3
    # None of the first fixture's genres should have leaked in.
    assert "Afro House" not in names
    assert "Techno" not in names


def test_uploaded_file_flows_through_full_review_and_generate(tmp_path):
    with open(FIXTURE_2, "rb") as f:
        client.post("/api/load-upload", files={"file": ("export.xml", f, "text/xml")})
    clusters = client.get("/api/clusters").json()["clusters"]
    dub = next(c for c in clusters if c["canonical_name"] == "Dub Techno")
    client.post(f"/api/clusters/{dub['id']}/status", json={"status": "approved"})

    out_dir = tmp_path / "playlists"
    gen = client.post("/api/generate", json={"output_dir": str(out_dir)})
    results = gen.json()["generated"]
    assert results[0]["canonical_name"] == "Dub Techno"
    assert results[0]["track_count"] == 2
    content = Path(results[0]["file_path"]).read_text()
    assert "/Users/dj/Music/Dub/Basalt.mp3" in content
    assert "/Users/dj/Music/Dub/Halide.mp3" in content


def test_upload_rejects_non_xml_filename():
    resp = client.post(
        "/api/load-upload",
        files={"file": ("collection.txt", b"not xml", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_rejects_malformed_xml():
    resp = client.post(
        "/api/load-upload",
        files={"file": ("broken.xml", b"<not><valid", "text/xml")},
    )
    assert resp.status_code == 400


def test_default_output_dir_is_absolute():
    resp = client.get("/api/default-output-dir")
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert Path(path).is_absolute()
    assert Path(path).name == "output"


def test_generate_resolves_relative_output_dir_to_absolute(tmp_path, monkeypatch):
    """Regression test: a relative output_dir must come back as an
    absolute file_path, otherwise the user has no way to know where the
    server actually wrote the file (this was the bug -- the response
    echoed back the same relative string the user typed in)."""
    monkeypatch.chdir(tmp_path)
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/status", json={"status": "approved"})

    gen = client.post("/api/generate", json={"output_dir": "output"})
    file_path = gen.json()["generated"][0]["file_path"]
    assert Path(file_path).is_absolute()
    assert Path(file_path) == tmp_path / "output" / "Afro House.m3u8"
    assert Path(file_path).exists()


def test_upload_never_writes_to_disk():
    """The upload flow parses straight from memory -- confirm nothing
    resembling the uploaded filename shows up on disk anywhere under the
    project during load (only /api/generate should ever write files)."""
    before = set(Path(".").rglob("suspicious_upload_marker.xml"))
    with open(FIXTURE_2, "rb") as f:
        client.post(
            "/api/load-upload",
            files={"file": ("suspicious_upload_marker.xml", f, "text/xml")},
        )
    after = set(Path(".").rglob("suspicious_upload_marker.xml"))
    assert before == after == set()


# --- Personal taxonomy: tree CRUD ---


def test_create_taxonomy_tree_and_fetch_it():
    afro = client.post("/api/taxonomy/nodes", json={"name": "Afro House"}).json()
    client.post("/api/taxonomy/nodes", json={"name": "Afro Deep", "parent_id": afro["id"]})
    client.post("/api/taxonomy/nodes", json={"name": "Afro Peak", "parent_id": afro["id"]})

    tree = client.get("/api/taxonomy").json()["tree"]
    assert len(tree) == 1
    assert tree[0]["name"] == "Afro House"
    assert {c["name"] for c in tree[0]["children"]} == {"Afro Deep", "Afro Peak"}


def test_create_returns_full_breadcrumb_path():
    afro = client.post("/api/taxonomy/nodes", json={"name": "Afro House"}).json()
    deep = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep", "parent_id": afro["id"]}).json()
    assert deep["path"] == "Afro House > Afro Deep"


def test_rename_taxonomy_node():
    node = client.post("/api/taxonomy/nodes", json={"name": "Melodic"}).json()
    resp = client.post(f"/api/taxonomy/nodes/{node['id']}/rename", json={"name": "Melodic House"})
    assert resp.json()["name"] == "Melodic House"


def test_move_taxonomy_node_under_new_parent():
    a = client.post("/api/taxonomy/nodes", json={"name": "A"}).json()
    b = client.post("/api/taxonomy/nodes", json={"name": "B"}).json()
    child = client.post("/api/taxonomy/nodes", json={"name": "Child", "parent_id": a["id"]}).json()

    resp = client.post(f"/api/taxonomy/nodes/{child['id']}/move", json={"parent_id": b["id"]})
    assert resp.json()["parent_id"] == b["id"]


def test_move_cycle_returns_400():
    a = client.post("/api/taxonomy/nodes", json={"name": "A"}).json()
    b = client.post("/api/taxonomy/nodes", json={"name": "B", "parent_id": a["id"]}).json()
    resp = client.post(f"/api/taxonomy/nodes/{a['id']}/move", json={"parent_id": b["id"]})
    assert resp.status_code == 400


def test_delete_node_with_children_requires_cascade():
    a = client.post("/api/taxonomy/nodes", json={"name": "A"}).json()
    client.post("/api/taxonomy/nodes", json={"name": "Child", "parent_id": a["id"]})
    resp = client.post(f"/api/taxonomy/nodes/{a['id']}/delete", json={"cascade": False})
    assert resp.status_code == 400


def test_delete_with_cascade_succeeds():
    a = client.post("/api/taxonomy/nodes", json={"name": "A"}).json()
    client.post("/api/taxonomy/nodes", json={"name": "Child", "parent_id": a["id"]})
    resp = client.post(f"/api/taxonomy/nodes/{a['id']}/delete", json={"cascade": True})
    assert resp.status_code == 200
    assert resp.json()["tree"] == []


# --- Assigning Rekordbox genre clusters onto the taxonomy ---


def test_cluster_starts_unmapped():
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    assert afro["taxonomy"] == {"status": "unmapped", "node_id": None, "path": None}


def test_assign_cluster_maps_all_its_raw_labels():
    node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")

    resp = client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": node["id"]})
    assert resp.json()["taxonomy"] == {"status": "mapped", "node_id": node["id"], "path": "Afro Deep"}

    # Re-fetching independently confirms it's really persisted in the
    # mapping, not just echoed back by the assign endpoint.
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    assert afro["taxonomy"]["status"] == "mapped"


def test_assign_cluster_to_unknown_node_returns_404():
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    resp = client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": "nope"})
    assert resp.status_code == 404


def test_unassign_cluster_clears_mapping():
    node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": node["id"]})

    client.post(f"/api/clusters/{afro['id']}/unassign-taxonomy")

    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    assert afro["taxonomy"]["status"] == "unmapped"


def test_mapping_survives_a_fresh_load_of_the_same_export():
    """The whole point of mapping by raw genre label rather than by
    cluster id: it should auto-apply again next time the same genres show
    up, without the DJ re-assigning anything."""
    node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": node["id"]})

    _load()  # simulates re-exporting/re-loading the same library later
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    assert afro["taxonomy"]["status"] == "mapped"
    assert afro["taxonomy"]["node_id"] == node["id"]


# --- Per-track review / overrides ---


def test_cluster_tracks_endpoint_lists_effective_assignment():
    node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": node["id"]})

    tracks = client.get(f"/api/clusters/{afro['id']}/tracks").json()["tracks"]
    assert len(tracks) == 4
    assert all(t["taxonomy_node_id"] == node["id"] for t in tracks)
    assert all(not t["has_override"] for t in tracks)


def test_track_override_wins_over_cluster_mapping():
    bulk_node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    exception_node = client.post("/api/taxonomy/nodes", json={"name": "Afro Organic"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": bulk_node["id"]})

    tracks = client.get(f"/api/clusters/{afro['id']}/tracks").json()["tracks"]
    one_track = tracks[0]

    resp = client.post(
        f"/api/tracks/{one_track['track_id']}/assign-taxonomy", json={"node_id": exception_node["id"]}
    )
    assert resp.json()["taxonomy_node_id"] == exception_node["id"]
    assert resp.json()["has_override"] is True

    tracks = client.get(f"/api/clusters/{afro['id']}/tracks").json()["tracks"]
    overridden = next(t for t in tracks if t["track_id"] == one_track["track_id"])
    others = [t for t in tracks if t["track_id"] != one_track["track_id"]]
    assert overridden["taxonomy_node_id"] == exception_node["id"]
    assert all(t["taxonomy_node_id"] == bulk_node["id"] for t in others)


def test_unassign_track_falls_back_to_cluster_mapping():
    bulk_node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    exception_node = client.post("/api/taxonomy/nodes", json={"name": "Afro Organic"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": bulk_node["id"]})
    track_id = client.get(f"/api/clusters/{afro['id']}/tracks").json()["tracks"][0]["track_id"]
    client.post(f"/api/tracks/{track_id}/assign-taxonomy", json={"node_id": exception_node["id"]})

    resp = client.post(f"/api/tracks/{track_id}/unassign-taxonomy")
    assert resp.json()["taxonomy_node_id"] == bulk_node["id"]
    assert resp.json()["has_override"] is False


def test_unlabeled_tracks_endpoint_and_manual_assignment():
    node = client.post("/api/taxonomy/nodes", json={"name": "Needs Review"}).json()
    _load()
    unlabeled = client.get("/api/unlabeled-tracks").json()["tracks"]
    assert len(unlabeled) == 2
    assert all(t["taxonomy_node_id"] is None for t in unlabeled)

    # A track with no genre has no label to map -- it can still be
    # pinned directly via override, since that's keyed by file path.
    track_id = unlabeled[0]["track_id"]
    resp = client.post(f"/api/tracks/{track_id}/assign-taxonomy", json={"node_id": node["id"]})
    assert resp.json()["taxonomy_node_id"] == node["id"]

    unlabeled = client.get("/api/unlabeled-tracks").json()["tracks"]
    assigned = next(t for t in unlabeled if t["track_id"] == track_id)
    assert assigned["taxonomy_node_id"] == node["id"]


# --- Merging/deleting taxonomy categories retargets assignments ---


def test_merging_taxonomy_categories_retargets_cluster_mapping():
    source = client.post("/api/taxonomy/nodes", json={"name": "Melodic"}).json()
    target = client.post("/api/taxonomy/nodes", json={"name": "Melodic House"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    melodic = next(c for c in clusters if c["canonical_name"] == "Melodic House")
    client.post(f"/api/clusters/{melodic['id']}/assign-taxonomy", json={"node_id": source["id"]})

    resp = client.post("/api/taxonomy/merge", json={"source_id": source["id"], "target_id": target["id"]})
    assert resp.status_code == 200

    clusters = client.get("/api/clusters").json()["clusters"]
    melodic = next(c for c in clusters if c["canonical_name"] == "Melodic House")
    assert melodic["taxonomy"]["node_id"] == target["id"]


def test_deleting_a_mapped_taxonomy_category_unassigns_its_tracks():
    node = client.post("/api/taxonomy/nodes", json={"name": "Afro Deep"}).json()
    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": node["id"]})

    client.post(f"/api/taxonomy/nodes/{node['id']}/delete", json={"cascade": False})

    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    assert afro["taxonomy"]["status"] == "unmapped"


# --- Generating M3U8 from the personal taxonomy ---


def test_generate_from_taxonomy_with_no_assignments_returns_400():
    _load()
    resp = client.post("/api/taxonomy/generate", json={"output_dir": "output"})
    assert resp.status_code == 400


def test_generate_from_taxonomy_writes_one_file_per_category(tmp_path):
    afro_house = client.post("/api/taxonomy/nodes", json={"name": "Afro House"}).json()
    afro_deep = client.post(
        "/api/taxonomy/nodes", json={"name": "Afro Deep", "parent_id": afro_house["id"]}
    ).json()
    techno_node = client.post("/api/taxonomy/nodes", json={"name": "Driving Techno"}).json()

    _load()
    clusters = client.get("/api/clusters").json()["clusters"]
    afro = next(c for c in clusters if c["canonical_name"] == "Afro House")
    techno = next(c for c in clusters if c["canonical_name"] == "Techno")
    client.post(f"/api/clusters/{afro['id']}/assign-taxonomy", json={"node_id": afro_deep["id"]})
    client.post(f"/api/clusters/{techno['id']}/assign-taxonomy", json={"node_id": techno_node["id"]})

    resp = client.post("/api/taxonomy/generate", json={"output_dir": str(tmp_path)})
    assert resp.status_code == 200
    results = {r["path"]: r for r in resp.json()["generated"]}
    assert set(results) == {"Afro House > Afro Deep", "Driving Techno"}
    assert results["Afro House > Afro Deep"]["track_count"] == 4
    assert results["Driving Techno"]["track_count"] == 2

    written = Path(results["Afro House > Afro Deep"]["file_path"])
    assert written.name == "Afro House - Afro Deep.m3u8"
    assert written.exists()
    assert "/Users/dj/Music/Afro/Sundown.mp3" in written.read_text()


def test_generate_from_taxonomy_includes_track_overrides(tmp_path):
    node = client.post("/api/taxonomy/nodes", json={"name": "Needs Review"}).json()
    _load()
    unlabeled = client.get("/api/unlabeled-tracks").json()["tracks"]
    track_id = unlabeled[0]["track_id"]
    client.post(f"/api/tracks/{track_id}/assign-taxonomy", json={"node_id": node["id"]})

    resp = client.post("/api/taxonomy/generate", json={"output_dir": str(tmp_path)})
    results = resp.json()["generated"]
    assert len(results) == 1
    assert results[0]["path"] == "Needs Review"
    assert results[0]["track_count"] == 1
