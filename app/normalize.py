"""Deterministic, explainable genre-tag clustering.

Deliberately string-based only (rapidfuzz) -- no embeddings, no ML model.
Every merge decision has a concrete reason attached so it's clear to the DJ
(and to us) why two labels ended up in the same cluster, and the review UI
can show it. If this proves insufficient in practice, that's the trigger to
consider embeddings -- not before.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

UNLABELED_TOKENS = {"", "unknown", "n/a", "none"}

# Labels whose *normalized ratio* similarity clears this are treated as
# spelling/punctuation variants of the same thing (e.g. "Afrohouse" vs
# "Afro House").
RATIO_MERGE_THRESHOLD = 90


@dataclass
class GenreCluster:
    canonical_name: str
    raw_labels: list[str] = field(default_factory=list)
    track_ids: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)  # raw_label -> why it merged


def _normalize(label: str) -> str:
    cleaned = label.strip().lower()
    for ch in ("-", "_", "/"):
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


def _is_word_prefix(short_norm: str, long_norm: str) -> bool:
    """True if `short_norm`'s tokens are exactly the leading tokens of
    `long_norm`'s tokens -- e.g. "afro" is a word-prefix of "afro house",
    "melodic" is a word-prefix of "melodic house".

    This intentionally only matches on the *leading* word(s). DJ compound
    genre tags overwhelmingly follow "[Modifier] [Base Genre]" order (Afro
    House, Melodic Techno, Deep House), and shorthand tends to drop the
    trailing base-genre word, not the leading modifier. Matching only on
    a leading-word prefix lets "Afro" merge into "Afro House" while
    refusing to merge generic base-genre words like "House" or "Techno"
    into every compound genre that ends with them.
    """
    short_tokens = short_norm.split()
    long_tokens = long_norm.split()
    if not short_tokens or len(short_tokens) >= len(long_tokens):
        return False
    return long_tokens[: len(short_tokens)] == short_tokens


def _merge_reason(a_norm: str, b_norm: str) -> str | None:
    if a_norm == b_norm:
        return "identical after normalization"
    ratio = fuzz.ratio(a_norm, b_norm)
    if ratio >= RATIO_MERGE_THRESHOLD:
        return f"spelling variant (similarity {ratio:.0f}%)"
    shorter, longer = sorted([a_norm, b_norm], key=len)
    if _is_word_prefix(shorter, longer):
        return "shorthand prefix of a compound genre"
    return None


class _UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_genres(tracks) -> tuple[list[GenreCluster], list[str]]:
    """Cluster tracks by genre.

    Returns (clusters, unlabeled_track_ids). Unlabeled tracks (blank or
    "Unknown" genre) are deliberately excluded from fuzzy clustering --
    there's no string signal to cluster on, so they're surfaced separately
    for the DJ to handle manually rather than guessed at.
    """
    labels_by_track: dict[str, str] = {}
    distinct_labels: set[str] = set()
    unlabeled_track_ids: list[str] = []

    for t in tracks:
        norm = _normalize(t.genre)
        if norm in UNLABELED_TOKENS:
            unlabeled_track_ids.append(t.track_id)
            continue
        labels_by_track[t.track_id] = t.genre
        distinct_labels.add(t.genre)

    labels = sorted(distinct_labels)
    uf = _UnionFind(labels)
    reasons: dict[tuple[str, str], str] = {}

    for i, a in enumerate(labels):
        a_norm = _normalize(a)
        for b in labels[i + 1 :]:
            b_norm = _normalize(b)
            reason = _merge_reason(a_norm, b_norm)
            if reason:
                uf.union(a, b)
                reasons[(a, b)] = reason

    groups: dict[str, list[str]] = {}
    for label in labels:
        root = uf.find(label)
        groups.setdefault(root, []).append(label)

    track_ids_by_label: dict[str, list[str]] = {}
    for track_id, label in labels_by_track.items():
        track_ids_by_label.setdefault(label, []).append(track_id)

    clusters: list[GenreCluster] = []
    for root, member_labels in groups.items():
        # canonical name = the label with the most tracks, tie-broken by
        # longest string (fuller/more specific tags read better as a name).
        canonical = max(
            member_labels,
            key=lambda l: (len(track_ids_by_label.get(l, [])), len(l)),
        )
        cluster = GenreCluster(canonical_name=canonical, raw_labels=sorted(member_labels))
        for label in member_labels:
            cluster.track_ids.extend(track_ids_by_label.get(label, []))
            if label == canonical:
                cluster.reasons[label] = "canonical label"
            else:
                pair = (label, canonical) if (label, canonical) in reasons else (canonical, label)
                cluster.reasons[label] = reasons.get(pair, "grouped via another label")
        clusters.append(cluster)

    clusters.sort(key=lambda c: c.canonical_name.lower())
    return clusters, unlabeled_track_ids
