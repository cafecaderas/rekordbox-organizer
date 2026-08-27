"""Read-only parser for a Rekordbox "Export Collection in xml format" file.

Never writes to this file or to Rekordbox. Only extracts what we need:
track id, genre, and the track's file path.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class Track:
    track_id: str
    name: str
    artist: str
    genre: str
    location: str  # local filesystem path, decoded from the file:// URI


def _decode_location(raw_location: str) -> str:
    """Rekordbox stores Location as a percent-encoded file:// URI, e.g.
    'file://localhost/Users/dj/Music/Afro/Savannah%20Nights.mp3'.
    M3U8 playlists need a plain filesystem path, not a URI, so this is
    decoded once here rather than in every consumer.
    """
    parsed = urlparse(raw_location)
    return unquote(parsed.path)


def parse_collection(source: str | Path | IO[bytes]) -> list[Track]:
    """Parse the <COLLECTION> tracks out of a Rekordbox XML export.

    `source` can be a filesystem path (dev/test flow, e.g. the fixture
    used by the automated tests) or an open binary file-like object (the
    real flow: a browser file upload streamed straight into the parser,
    never written to disk).

    Raises FileNotFoundError / ET.ParseError on bad input rather than
    guessing, since a malformed export means the rest of the pipeline
    would be working from wrong data.
    """
    tree = ET.parse(source)
    root = tree.getroot()
    collection = root.find("COLLECTION")
    if collection is None:
        raise ValueError("No <COLLECTION> element found in the XML file")

    tracks = []
    for track_el in collection.findall("TRACK"):
        location = track_el.get("Location", "")
        tracks.append(
            Track(
                track_id=track_el.get("TrackID", ""),
                name=track_el.get("Name", ""),
                artist=track_el.get("Artist", ""),
                genre=track_el.get("Genre", "").strip(),
                location=_decode_location(location) if location else "",
            )
        )
    return tracks


def parse_collection_bytes(data: bytes) -> list[Track]:
    """Convenience wrapper for parsing an in-memory XML upload (no temp file)."""
    return parse_collection(io.BytesIO(data))
