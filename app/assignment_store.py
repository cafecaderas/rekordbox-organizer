"""Persistent mapping from Rekordbox genre tags -- and, for exceptions,
individual tracks -- onto nodes in the personal taxonomy (see
app/taxonomy_store.py).

Two layers, in priority order:

  1. Track overrides -- an individual track pinned to a specific category,
     keyed by its absolute file path (the same identity used everywhere
     else in this app, e.g. for M3U8 generation). This is also the escape
     hatch for tracks with no genre tag at all: there's no genre label to
     map, but a track can still be pinned directly.

  2. Genre mapping -- a raw Rekordbox genre string (e.g. "Afro House",
     "Afrohouse") mapped to a category. This is the bulk mechanism: when
     the DJ assigns a whole genre cluster to a taxonomy category in the
     review UI, every raw label currently in that cluster gets the same
     mapping, so it applies automatically on every future re-export
     without asking again -- keyed by the raw label rather than this
     app's own (ephemeral, regenerated-per-run) cluster ids.

Neither layer ever touches Rekordbox's own Genre tag -- this is purely
this app's own bookkeeping, held separately from Rekordbox's data.
"""
from __future__ import annotations

import json
from pathlib import Path


class AssignmentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.genre_mapping: dict[str, str] = {}  # raw genre label -> node_id
        self.track_overrides: dict[str, str] = {}  # track location -> node_id
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.genre_mapping = data.get("genre_mapping", {})
        self.track_overrides = data.get("track_overrides", {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"genre_mapping": self.genre_mapping, "track_overrides": self.track_overrides}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- writes --

    def map_genre_labels(self, raw_labels: list[str], node_id: str) -> None:
        for label in raw_labels:
            self.genre_mapping[label] = node_id
        self._save()

    def unmap_genre_labels(self, raw_labels: list[str]) -> None:
        for label in raw_labels:
            self.genre_mapping.pop(label, None)
        self._save()

    def set_track_override(self, location: str, node_id: str) -> None:
        self.track_overrides[location] = node_id
        self._save()

    def clear_track_override(self, location: str) -> None:
        self.track_overrides.pop(location, None)
        self._save()

    def retarget(self, old_node_id: str, new_node_id: str | None) -> None:
        """Repoint every mapping/override that referenced `old_node_id`.

        Used when a taxonomy category is merged (new_node_id = the merge
        target, so tracks stay assigned) or deleted (new_node_id = None,
        so tracks explicitly fall back to unassigned rather than silently
        pointing at a category that no longer exists).
        """
        changed = False
        for label, nid in list(self.genre_mapping.items()):
            if nid == old_node_id:
                if new_node_id is None:
                    del self.genre_mapping[label]
                else:
                    self.genre_mapping[label] = new_node_id
                changed = True
        for loc, nid in list(self.track_overrides.items()):
            if nid == old_node_id:
                if new_node_id is None:
                    del self.track_overrides[loc]
                else:
                    self.track_overrides[loc] = new_node_id
                changed = True
        if changed:
            self._save()

    # -- reads --

    def resolve(self, genre_label: str, location: str) -> str | None:
        """Effective taxonomy node for a track: a per-track override wins,
        otherwise fall back to whatever its raw genre label maps to (and
        None if neither applies -- the track is simply unassigned)."""
        if location in self.track_overrides:
            return self.track_overrides[location]
        return self.genre_mapping.get(genre_label)
