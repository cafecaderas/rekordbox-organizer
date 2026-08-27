"""In-memory session state for a single local run of the tool.

This is a single-user, single-machine, local-first app (no auth, no
persistence beyond generated files) -- there is deliberately no database
here. Restarting the server clears state, which is fine: the whole
workflow is designed to be re-run from a fresh Rekordbox XML export
whenever the library changes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.normalize import cluster_genres
from app.xml_parser import Track, parse_collection, parse_collection_bytes


@dataclass
class ClusterRecord:
    id: str
    canonical_name: str
    raw_labels: list[str]
    track_ids: list[str]
    reasons: dict[str, str]
    status: str = "pending"  # pending | approved | rejected


@dataclass
class Session:
    source_xml_path: str = ""
    tracks_by_id: dict[str, Track] = field(default_factory=dict)
    clusters: dict[str, ClusterRecord] = field(default_factory=dict)
    unlabeled_track_ids: list[str] = field(default_factory=list)

    def load(self, xml_path: str) -> None:
        """Load from a filesystem path -- used by the automated tests and
        the synthetic fixture. Not exposed in the UI, since browsers can't
        hand back a real filesystem path from a file picker; see
        `load_from_bytes` for the real upload flow."""
        tracks = parse_collection(xml_path)
        self._apply(tracks, source_label=xml_path)

    def load_from_bytes(self, xml_bytes: bytes, filename: str) -> None:
        """Load from an uploaded file's raw bytes (the browser file-picker
        flow) without ever writing the upload to disk."""
        tracks = parse_collection_bytes(xml_bytes)
        self._apply(tracks, source_label=filename)

    def _apply(self, tracks: list[Track], source_label: str) -> None:
        raw_clusters, unlabeled = cluster_genres(tracks)

        self.source_xml_path = source_label
        self.tracks_by_id = {t.track_id: t for t in tracks}
        self.unlabeled_track_ids = unlabeled
        self.clusters = {}
        for i, c in enumerate(raw_clusters, start=1):
            cid = f"c{i}"
            self.clusters[cid] = ClusterRecord(
                id=cid,
                canonical_name=c.canonical_name,
                raw_labels=c.raw_labels,
                track_ids=c.track_ids,
                reasons=c.reasons,
            )

    def require_cluster(self, cluster_id: str) -> ClusterRecord:
        if cluster_id not in self.clusters:
            raise KeyError(f"Unknown cluster id: {cluster_id}")
        return self.clusters[cluster_id]

    def rename(self, cluster_id: str, new_name: str) -> ClusterRecord:
        cluster = self.require_cluster(cluster_id)
        cluster.canonical_name = new_name.strip() or cluster.canonical_name
        return cluster

    def set_status(self, cluster_id: str, status: str) -> ClusterRecord:
        cluster = self.require_cluster(cluster_id)
        cluster.status = status
        return cluster

    def merge(self, cluster_id_a: str, cluster_id_b: str) -> ClusterRecord:
        a = self.require_cluster(cluster_id_a)
        b = self.require_cluster(cluster_id_b)
        if a is b:
            raise ValueError("Cannot merge a cluster with itself")
        a.raw_labels = sorted(set(a.raw_labels) | set(b.raw_labels))
        a.track_ids = list(dict.fromkeys(a.track_ids + b.track_ids))
        a.reasons.update(b.reasons)
        del self.clusters[cluster_id_b]
        return a

    def split(self, cluster_id: str, raw_label: str) -> ClusterRecord:
        """Pull every track carrying `raw_label` out of `cluster_id` into
        its own new cluster."""
        source = self.require_cluster(cluster_id)
        if raw_label not in source.raw_labels:
            raise ValueError(f"Label {raw_label!r} is not part of cluster {cluster_id}")
        if len(source.raw_labels) == 1:
            raise ValueError("Cannot split a cluster that has only one raw label")

        moved_track_ids = [
            tid
            for tid in source.track_ids
            if self.tracks_by_id[tid].genre == raw_label
        ]
        source.raw_labels = [l for l in source.raw_labels if l != raw_label]
        source.track_ids = [tid for tid in source.track_ids if tid not in moved_track_ids]
        source.reasons.pop(raw_label, None)

        new_id = f"c-{uuid.uuid4().hex[:8]}"
        new_cluster = ClusterRecord(
            id=new_id,
            canonical_name=raw_label,
            raw_labels=[raw_label],
            track_ids=moved_track_ids,
            reasons={raw_label: "split out for review"},
            status="pending",
        )
        self.clusters[new_id] = new_cluster
        return new_cluster

    def approved_clusters(self) -> list[ClusterRecord]:
        return [c for c in self.clusters.values() if c.status == "approved"]


# Single global session -- this is intentionally a one-user local tool.
session = Session()
