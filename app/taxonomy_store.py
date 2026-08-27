"""Persistent, user-defined taxonomy of personal genre/subgenre categories.

Deliberately separate from Rekordbox's own genre metadata (see
app/normalize.py) -- the DJ's personal organization is richer than a
single Genre tag, and Rekordbox's genre field is never overwritten. This
module only manages the *shape* of the personal taxonomy (a tree of named
categories). Mapping tracks onto it lives in app/assignment_store.py --
kept separate so this module doesn't need to know tracks exist at all.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


class TaxonomyError(ValueError):
    pass


@dataclass
class TaxonomyNode:
    id: str
    name: str
    parent_id: str | None = None


class TaxonomyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._nodes: dict[str, TaxonomyNode] = {}
        self._order: list[str] = []  # insertion order, for stable display
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        self._nodes = {n["id"]: TaxonomyNode(**n) for n in nodes}
        self._order = [n["id"] for n in nodes]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"nodes": [asdict(self._nodes[nid]) for nid in self._order]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # -- CRUD --

    def create(self, name: str, parent_id: str | None = None) -> TaxonomyNode:
        name = name.strip()
        if not name:
            raise TaxonomyError("Category name cannot be blank")
        if parent_id is not None:
            self._require(parent_id)
        node = TaxonomyNode(id=f"tx-{uuid.uuid4().hex[:8]}", name=name, parent_id=parent_id)
        self._nodes[node.id] = node
        self._order.append(node.id)
        self._save()
        return node

    def rename(self, node_id: str, new_name: str) -> TaxonomyNode:
        node = self._require(node_id)
        new_name = new_name.strip()
        if not new_name:
            raise TaxonomyError("Category name cannot be blank")
        node.name = new_name
        self._save()
        return node

    def move(self, node_id: str, new_parent_id: str | None) -> TaxonomyNode:
        node = self._require(node_id)
        if new_parent_id is not None:
            self._require(new_parent_id)
            if new_parent_id == node_id or self._is_descendant(new_parent_id, node_id):
                raise TaxonomyError("Cannot move a category under itself or its own descendant")
        node.parent_id = new_parent_id
        self._save()
        return node

    def merge(self, source_id: str, target_id: str) -> TaxonomyNode:
        """Combine `source_id` into `target_id`: source's children are
        re-parented under target, and the source node is deleted.

        This only rewires the taxonomy tree itself. Callers own retargeting
        any genre mappings / track overrides that pointed at `source_id`
        (see AssignmentStore.retarget) -- kept as a separate step so this
        store doesn't need to know AssignmentStore exists.
        """
        if source_id == target_id:
            raise TaxonomyError("Cannot merge a category with itself")
        self._require(source_id)
        self._require(target_id)
        if self._is_descendant(target_id, source_id):
            raise TaxonomyError("Cannot merge a category into its own descendant")
        for child in self._children_of(source_id):
            child.parent_id = target_id
        del self._nodes[source_id]
        self._order.remove(source_id)
        self._save()
        return self._nodes[target_id]

    def delete(self, node_id: str, cascade: bool = False) -> list[str]:
        """Delete a category. Returns the ids of every node actually
        removed (the node itself, plus descendants if cascading)."""
        self._require(node_id)
        subtree = self._subtree_ids(node_id)
        if len(subtree) > 1 and not cascade:
            raise TaxonomyError(
                f"Category has {len(subtree) - 1} subcategory(ies) -- pass cascade=True to delete them too"
            )
        for nid in subtree:
            del self._nodes[nid]
            self._order.remove(nid)
        self._save()
        return subtree

    # -- reads --

    def get(self, node_id: str) -> TaxonomyNode | None:
        return self._nodes.get(node_id)

    def path_name(self, node_id: str) -> str:
        """Full breadcrumb, e.g. 'Afro House > Afro Deep'."""
        node = self._require(node_id)
        parts = [node.name]
        cursor = node
        while cursor.parent_id:
            cursor = self._require(cursor.parent_id)
            parts.append(cursor.name)
        return " > ".join(reversed(parts))

    def flat_list(self) -> list[dict]:
        """Every node with its full path -- convenient for populating a
        flat picker dropdown rather than a nested tree widget."""
        return [{"id": nid, "path": self.path_name(nid)} for nid in self._order]

    def tree(self) -> list[dict]:
        """Nested representation for the UI: top-level nodes with nested children."""

        def build(parent_id: str | None) -> list[dict]:
            return [
                {"id": nid, "name": self._nodes[nid].name, "children": build(nid)}
                for nid in self._order
                if self._nodes[nid].parent_id == parent_id
            ]

        return build(None)

    # -- internals --

    def _require(self, node_id: str) -> TaxonomyNode:
        if node_id not in self._nodes:
            raise TaxonomyError(f"Unknown category: {node_id}")
        return self._nodes[node_id]

    def _children_of(self, node_id: str) -> list[TaxonomyNode]:
        return [n for n in self._nodes.values() if n.parent_id == node_id]

    def _is_descendant(self, candidate_id: str, ancestor_id: str) -> bool:
        """True if `candidate_id` is anywhere below `ancestor_id` in the tree."""
        cursor = self._nodes.get(candidate_id)
        while cursor and cursor.parent_id:
            if cursor.parent_id == ancestor_id:
                return True
            cursor = self._nodes.get(cursor.parent_id)
        return False

    def _subtree_ids(self, node_id: str) -> list[str]:
        ids = [node_id]
        for child in self._children_of(node_id):
            ids.extend(self._subtree_ids(child.id))
        return ids
