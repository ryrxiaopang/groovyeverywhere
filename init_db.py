"""
Milestone 0: local storage setup.

Creates data/lodge.db (SQLite) with a single `tracks` table that Milestone 1
(catalog building) will populate: one row per pop-pilot track, holding
Spotify catalog metadata, the Deezer-sourced popularity signal (Spotify no
longer returns popularity/followers/genres for apps without a quota
extension - confirmed during Milestone 0), the matched Deezer preview, and
(later) paths to the downloaded audio clip and its embedding.

Run once: python init_db.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data/lodge.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    spotify_track_id   TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    artist_name         TEXT NOT NULL,
    spotify_artist_id   TEXT NOT NULL,
    deezer_track_id     TEXT,
    deezer_rank         INTEGER,
    deezer_artist_id    TEXT,
    artist_nb_fan       INTEGER,
    genre               TEXT,
    deezer_preview_url  TEXT,
    audio_path          TEXT,
    embedding_path      TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    print(f"Initialized {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
