"""Local FastAPI backend for the DJ Genre Playlist Bootstrapper.

Runs entirely on localhost. No cloud calls, no LLM, no external services.
The only filesystem interactions are: (1) reading a Rekordbox XML export
the user points us at, and (2) writing M3U8 files to an output directory
the user chooses. Rekordbox's own database is never touched.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.assignment_store import AssignmentStore
from app.m3u8_writer import safe_filename, write_m3u8
from app.session import ClusterRecord, session
from app.taxonomy_store import TaxonomyError, TaxonomyStore

app = FastAPI(title="DJ Genre Playlist Bootstrapper")

STATIC_DIR = Path(__file__).parent / "static"

# Resolved from the project root (not the server's launch cwd) so the
# personal taxonomy always lives in the same place regardless of how
# uvicorn was started -- see the /api/default-output-dir fix for why cwd-
# relative paths are the wrong default here. Overridable via
# DJ_TOOL_DATA_DIR so the automated tests never touch real user data.
DATA_DIR = Path(os.environ.get("DJ_TOOL_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
taxonomy_store = TaxonomyStore(DATA_DIR / "taxonomy.json")
assignment_store = AssignmentStore(DATA_DIR / "assignments.json")


class LoadRequest(BaseModel):
    xml_path: str


class RenameRequest(BaseModel):
    name: str


class StatusRequest(BaseModel):
    status: str  # approved | rejected | pending


class MergeRequest(BaseModel):
    cluster_id_a: str
    cluster_id_b: str


class SplitRequest(BaseModel):
    raw_label: str


class GenerateRequest(BaseModel):
    output_dir: str = "output"


class CreateNodeRequest(BaseModel):
    name: str
    parent_id: str | None = None


class MoveNodeRequest(BaseModel):
    parent_id: str | None = None


class MergeNodesRequest(BaseModel):
    source_id: str
    target_id: str


class DeleteNodeRequest(BaseModel):
    cascade: bool = False


class AssignNodeRequest(BaseModel):
    node_id: str


def _taxonomy_status_for_labels(raw_labels: list[str]) -> dict:
    """Roll up the per-label genre mapping into one status for a whole
    cluster. "mapped" is the common case (the DJ used the bulk assign
    action, which maps every raw label in the cluster to the same node
    atomically); "partial"/"mixed" only show up from edge cases like a
    cluster split/merge happening after a mapping was already made."""
    mapped = {l: assignment_store.genre_mapping[l] for l in raw_labels if l in assignment_store.genre_mapping}
    if not mapped:
        return {"status": "unmapped", "node_id": None, "path": None}
    distinct_nodes = set(mapped.values())
    if len(distinct_nodes) > 1:
        return {"status": "mixed", "node_id": None, "path": None}
    node_id = next(iter(distinct_nodes))
    node = taxonomy_store.get(node_id)
    path = taxonomy_store.path_name(node_id) if node else None
    status = "mapped" if len(mapped) == len(raw_labels) else "partial"
    return {"status": status, "node_id": node_id, "path": path}


def _cluster_to_dict(cluster: ClusterRecord) -> dict:
    preview = [
        session.tracks_by_id[tid].name
        for tid in cluster.track_ids[:5]
        if tid in session.tracks_by_id
    ]
    return {
        "id": cluster.id,
        "canonical_name": cluster.canonical_name,
        "raw_labels": cluster.raw_labels,
        "reasons": cluster.reasons,
        "track_count": len(cluster.track_ids),
        "preview_tracks": preview,
        "status": cluster.status,
        "taxonomy": _taxonomy_status_for_labels(cluster.raw_labels),
    }


def _node_to_dict(node) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "parent_id": node.parent_id,
        "path": taxonomy_store.path_name(node.id),
    }


def _track_to_dict(track_id: str) -> dict:
    track = session.tracks_by_id[track_id]
    node_id = assignment_store.resolve(track.genre, track.location) if track.location else None
    return {
        "track_id": track_id,
        "name": track.name,
        "artist": track.artist,
        "genre": track.genre,
        "location": track.location,
        "taxonomy_node_id": node_id,
        "taxonomy_path": taxonomy_store.path_name(node_id) if node_id else None,
        "has_override": track.location in assignment_store.track_overrides,
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/default-output-dir")
def default_output_dir():
    """Where playlists land if the user doesn't change the output dir
    field -- resolved to an absolute path so the UI can show it up front,
    rather than the user finding out only after generating."""
    return {"path": str(Path("output").resolve())}


@app.post("/api/load")
def load(req: LoadRequest):
    """Load from a filesystem path already on the server's machine.

    Kept for the automated tests and the synthetic fixture (see
    tests/fixtures/sample_rekordbox.xml) and for scripting. The UI itself
    uses /api/load-upload instead, since a browser file picker can't hand
    back an absolute filesystem path.
    """
    path = Path(req.xml_path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    try:
        session.load(str(path))
    except Exception as exc:  # noqa: BLE001 - surface parser errors verbatim to the UI
        raise HTTPException(status_code=400, detail=f"Could not parse XML: {exc}") from exc
    return get_clusters()


@app.post("/api/load-upload")
async def load_upload(file: UploadFile = File(...)):
    """Load from a file the user picked via the browser's native file
    picker. The upload is parsed straight from memory and never written
    to disk -- consistent with the plan's read-only-against-Rekordbox
    stance, this doesn't touch the filesystem at all on the read side."""
    if not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Please select a Rekordbox XML export (.xml)")
    contents = await file.read()
    try:
        session.load_from_bytes(contents, file.filename)
    except Exception as exc:  # noqa: BLE001 - surface parser errors verbatim to the UI
        raise HTTPException(status_code=400, detail=f"Could not parse XML: {exc}") from exc
    return get_clusters()


@app.get("/api/clusters")
def get_clusters():
    return {
        "source_xml_path": session.source_xml_path,
        "clusters": [_cluster_to_dict(c) for c in session.clusters.values()],
        "unlabeled_track_count": len(session.unlabeled_track_ids),
        "total_track_count": len(session.tracks_by_id),
    }


@app.post("/api/clusters/{cluster_id}/rename")
def rename_cluster(cluster_id: str, req: RenameRequest):
    try:
        cluster = session.rename(cluster_id, req.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cluster_to_dict(cluster)


@app.post("/api/clusters/{cluster_id}/status")
def set_cluster_status(cluster_id: str, req: StatusRequest):
    if req.status not in {"approved", "rejected", "pending"}:
        raise HTTPException(status_code=400, detail="status must be approved, rejected, or pending")
    try:
        cluster = session.set_status(cluster_id, req.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cluster_to_dict(cluster)


@app.post("/api/clusters/merge")
def merge_clusters(req: MergeRequest):
    try:
        cluster = session.merge(req.cluster_id_a, req.cluster_id_b)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_clusters()


@app.post("/api/clusters/{cluster_id}/split")
def split_cluster(cluster_id: str, req: SplitRequest):
    try:
        session.split(cluster_id, req.raw_label)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_clusters()


@app.post("/api/generate")
def generate(req: GenerateRequest):
    approved = session.approved_clusters()
    if not approved:
        raise HTTPException(status_code=400, detail="No approved clusters to generate playlists for")

    # Resolve to an absolute path before doing anything else. `output_dir`
    # is otherwise relative to wherever the server process happened to be
    # started from, which is invisible to the user and made "where did my
    # playlist go?" impossible to answer from the UI alone.
    output_dir = Path(req.output_dir).expanduser().resolve()
    results = []
    for cluster in approved:
        paths = []
        skipped = 0
        for tid in cluster.track_ids:
            track = session.tracks_by_id.get(tid)
            if track and track.location:
                paths.append(track.location)
            else:
                skipped += 1
        if not paths:
            results.append(
                {
                    "cluster_id": cluster.id,
                    "canonical_name": cluster.canonical_name,
                    "file_path": None,
                    "track_count": 0,
                    "skipped_count": skipped,
                    "error": "No resolvable file paths for this cluster",
                }
            )
            continue
        out_file = output_dir / f"{safe_filename(cluster.canonical_name)}.m3u8"
        write_m3u8(out_file, paths)
        results.append(
            {
                "cluster_id": cluster.id,
                "canonical_name": cluster.canonical_name,
                "file_path": str(out_file),
                "track_count": len(paths),
                "skipped_count": skipped,
            }
        )
    return {"generated": results}


# --- Personal taxonomy: the category tree itself (app/taxonomy_store.py) ---


@app.get("/api/taxonomy")
def get_taxonomy():
    return {"tree": taxonomy_store.tree(), "flat": taxonomy_store.flat_list()}


@app.post("/api/taxonomy/nodes")
def create_taxonomy_node(req: CreateNodeRequest):
    try:
        node = taxonomy_store.create(req.name, req.parent_id)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _node_to_dict(node)


@app.post("/api/taxonomy/nodes/{node_id}/rename")
def rename_taxonomy_node(node_id: str, req: RenameRequest):
    try:
        node = taxonomy_store.rename(node_id, req.name)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _node_to_dict(node)


@app.post("/api/taxonomy/nodes/{node_id}/move")
def move_taxonomy_node(node_id: str, req: MoveNodeRequest):
    try:
        node = taxonomy_store.move(node_id, req.parent_id)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _node_to_dict(node)


@app.post("/api/taxonomy/merge")
def merge_taxonomy_nodes(req: MergeNodesRequest):
    try:
        taxonomy_store.merge(req.source_id, req.target_id)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Tracks/genres mapped to the now-deleted source category follow it
    # into the merge target rather than silently becoming unassigned.
    assignment_store.retarget(req.source_id, req.target_id)
    return get_taxonomy()


@app.post("/api/taxonomy/nodes/{node_id}/delete")
def delete_taxonomy_node(node_id: str, req: DeleteNodeRequest):
    try:
        removed_ids = taxonomy_store.delete(node_id, cascade=req.cascade)
    except TaxonomyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Anything that was mapped to a deleted category (or one of its
    # deleted descendants) explicitly falls back to unassigned, rather
    # than pointing at a category id that no longer exists.
    for removed_id in removed_ids:
        assignment_store.retarget(removed_id, None)
    return get_taxonomy()


# --- Assigning tracks/genres onto the taxonomy (app/assignment_store.py) ---


@app.post("/api/clusters/{cluster_id}/assign-taxonomy")
def assign_cluster_to_taxonomy(cluster_id: str, req: AssignNodeRequest):
    try:
        cluster = session.require_cluster(cluster_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if taxonomy_store.get(req.node_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown taxonomy category: {req.node_id}")
    assignment_store.map_genre_labels(cluster.raw_labels, req.node_id)
    return _cluster_to_dict(cluster)


@app.post("/api/clusters/{cluster_id}/unassign-taxonomy")
def unassign_cluster_from_taxonomy(cluster_id: str):
    try:
        cluster = session.require_cluster(cluster_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assignment_store.unmap_genre_labels(cluster.raw_labels)
    return _cluster_to_dict(cluster)


@app.get("/api/clusters/{cluster_id}/tracks")
def get_cluster_tracks(cluster_id: str):
    try:
        cluster = session.require_cluster(cluster_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"tracks": [_track_to_dict(tid) for tid in cluster.track_ids]}


@app.get("/api/unlabeled-tracks")
def get_unlabeled_tracks():
    """Tracks with no Rekordbox genre at all -- there's no label to map,
    so the only way to organize these today is a manual per-track
    override. Automatic classification for this group is future work
    (see the plan's "Missing Genres" section) -- deliberately not built
    yet."""
    return {"tracks": [_track_to_dict(tid) for tid in session.unlabeled_track_ids]}


@app.post("/api/tracks/{track_id}/assign-taxonomy")
def assign_track_to_taxonomy(track_id: str, req: AssignNodeRequest):
    if track_id not in session.tracks_by_id:
        raise HTTPException(status_code=404, detail=f"Unknown track id: {track_id}")
    track = session.tracks_by_id[track_id]
    if not track.location:
        raise HTTPException(status_code=400, detail="Track has no file path -- cannot assign it")
    if taxonomy_store.get(req.node_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown taxonomy category: {req.node_id}")
    assignment_store.set_track_override(track.location, req.node_id)
    return _track_to_dict(track_id)


@app.post("/api/tracks/{track_id}/unassign-taxonomy")
def unassign_track_from_taxonomy(track_id: str):
    if track_id not in session.tracks_by_id:
        raise HTTPException(status_code=404, detail=f"Unknown track id: {track_id}")
    track = session.tracks_by_id[track_id]
    if track.location:
        assignment_store.clear_track_override(track.location)
    return _track_to_dict(track_id)


@app.post("/api/taxonomy/generate")
def generate_from_taxonomy(req: GenerateRequest):
    """Generate one M3U8 per taxonomy category that has at least one
    track currently resolved to it -- via genre mapping, a track
    override, or both. Additive to /api/generate (the raw-Rekordbox-genre
    flow): this doesn't replace it, it's the personal-taxonomy version of
    the same last step."""
    by_node: dict[str, list] = {}
    for track_id, track in session.tracks_by_id.items():
        if not track.location:
            continue
        node_id = assignment_store.resolve(track.genre, track.location)
        if node_id:
            by_node.setdefault(node_id, []).append(track)

    if not by_node:
        raise HTTPException(
            status_code=400,
            detail="No tracks are assigned to any personal taxonomy category yet",
        )

    output_dir = Path(req.output_dir).expanduser().resolve()
    results = []
    for node_id, tracks in by_node.items():
        node = taxonomy_store.get(node_id)
        if node is None:
            continue  # category was deleted mid-session; retarget already cleaned this up on reload
        path_name = taxonomy_store.path_name(node_id)
        out_file = output_dir / f"{safe_filename(path_name.replace(' > ', ' - '))}.m3u8"
        write_m3u8(out_file, [t.location for t in tracks])
        results.append(
            {
                "node_id": node_id,
                "path": path_name,
                "file_path": str(out_file),
                "track_count": len(tracks),
            }
        )
    return {"generated": results}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
