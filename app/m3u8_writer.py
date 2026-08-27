"""Writes M3U8 playlist files.

Deliberately minimal: an M3U8 file is just an ordered list of absolute file
paths. It carries no track metadata, which is the whole point -- see the
plan's "Why M3U8" section for why that's the safety boundary for this
project. Paths are written byte-for-byte as decoded from the Rekordbox XML
so they match what's already in the DJ's Collection.
"""
from __future__ import annotations

import re
from pathlib import Path

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def safe_filename(name: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "untitled"


def write_m3u8(output_path: str | Path, track_paths: list[str]) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#EXTM3U"]
    lines.extend(track_paths)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
