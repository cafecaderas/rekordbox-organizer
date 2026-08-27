# DJ Genre Playlist Bootstrapper (rekordbox-organizer)

A local tool for turning the messy, inconsistent genre tags in a Rekordbox
library into clean, organized M3U8 playlists.

Runs entirely on your machine. No cloud calls, no LLM, no external services.
The only filesystem interactions are: (1) reading a Rekordbox XML export you
point it at, and (2) writing `.m3u8` playlist files to an output directory
you choose. Your Rekordbox database itself is never touched.

## What it does

Rekordbox genre tags tend to be inconsistent across a real library — e.g.
`House`, `house`, `Deep House`, `House Music` might all describe the same
thing depending on when/how a track was tagged. This tool:

1. **Loads** a Rekordbox XML export and clusters tracks by their raw genre
   label.
2. Lets you **review, rename, merge, or split** those clusters until they
   match how you actually think about your library.
3. Optionally lets you build a **personal taxonomy** — your own genre tree
   (e.g. `House > Deep House`) — and assign clusters or individual tracks
   into it.
4. **Generates** one `.m3u8` playlist per approved cluster or taxonomy
   category, pointing at your tracks' real file paths.

## Requirements

- Python 3.13
- A Rekordbox XML library export (Rekordbox → File → Export Collection in
  xml format)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running it

```bash
source .venv/bin/activate
uvicorn app.main:app --port 8000 --reload
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
app/
  main.py             FastAPI app + all HTTP routes
  session.py           In-memory session: loaded tracks, genre clusters
  xml_parser.py         Parses the Rekordbox XML export
  normalize.py          Genre label clustering/normalization
  taxonomy_store.py     Personal genre taxonomy (tree), persisted to data/
  assignment_store.py   Cluster/track -> taxonomy assignments, persisted to data/
  m3u8_writer.py        Writes .m3u8 playlist files
  static/               Frontend (single-page UI)
tests/                  pytest suite, mirrors app/ modules
data/                   Your personal taxonomy + assignments (gitignored)
output/                 Generated playlists (gitignored)
```

`data/` and `output/` are gitignored on purpose — they hold your personal
taxonomy and generated playlists, not project source.

## Workflow

Changes land on `main` through a pull request, not a direct push — including
for docs-only changes like this README. See [CONTRIBUTING.md](CONTRIBUTING.md).
