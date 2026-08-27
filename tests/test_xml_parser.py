from pathlib import Path

from app.xml_parser import parse_collection

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rekordbox.xml"


def test_parses_all_tracks():
    tracks = parse_collection(FIXTURE)
    assert len(tracks) == 10


def test_decodes_percent_encoded_location():
    tracks = parse_collection(FIXTURE)
    savannah = next(t for t in tracks if t.track_id == "3")
    assert savannah.location == "/Users/dj/Music/Afro/Savannah Nights.mp3"


def test_plain_location_without_encoding():
    tracks = parse_collection(FIXTURE)
    sundown = next(t for t in tracks if t.track_id == "1")
    assert sundown.location == "/Users/dj/Music/Afro/Sundown.mp3"


def test_reads_genre_and_blank_genre():
    tracks = parse_collection(FIXTURE)
    by_id = {t.track_id: t for t in tracks}
    assert by_id["1"].genre == "Afro House"
    assert by_id["10"].genre == ""
