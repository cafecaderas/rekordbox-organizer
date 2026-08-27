from pathlib import Path

from app.m3u8_writer import safe_filename, write_m3u8


def test_write_m3u8_contains_header_and_paths(tmp_path):
    out = tmp_path / "Afro House.m3u8"
    paths = ["/Users/dj/Music/Afro/Sundown.mp3", "/Users/dj/Music/Afro/Baobab.mp3"]
    result = write_m3u8(out, paths)
    content = result.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1:] == paths


def test_write_m3u8_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "dir" / "playlist.m3u8"
    write_m3u8(out, ["/a.mp3"])
    assert out.exists()


def test_safe_filename_strips_unsafe_chars():
    assert safe_filename("Afro/House: Deep*") == "Afro_House_ Deep_"


def test_safe_filename_empty_falls_back():
    assert safe_filename("") == "untitled"
