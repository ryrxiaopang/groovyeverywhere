"""
Milestone 0 sanity check: confirm the Spotify Client Credentials flow works
for this app's credentials, that search/track/artist/popularity lookups
succeed, and that audio-features fails with 403 as expected (Spotify
deprecated it for new apps on Nov 27, 2024).

Usage:
    1. Copy .env.example to .env and fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
       from https://developer.spotify.com/dashboard
    2. python validate_spotify_access.py
"""

import os
import sys

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

PROBE_TRACK_QUERY = "Blinding Lights The Weeknd"


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def main() -> int:
    if not CLIENT_ID or not CLIENT_SECRET:
        fail("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set. Copy .env.example to .env and fill them in.")
        return 1

    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=CLIENT_ID, client_secret=CLIENT_SECRET
        )
    )

    results = {}

    # 1. search
    try:
        search_result = sp.search(q=PROBE_TRACK_QUERY, type="track", limit=1)
        track = search_result["tracks"]["items"][0]
        ok(f"search: found '{track['name']}' by {track['artists'][0]['name']}")
        results["track_id"] = track["id"]
        results["artist_id"] = track["artists"][0]["id"]
    except Exception as e:
        fail(f"search failed: {e}")
        return 1

    # 2. track lookup + popularity
    try:
        track_info = sp.track(results["track_id"])
        ok(f"track lookup: popularity={track_info['popularity']}")
    except Exception as e:
        fail(f"track lookup failed: {e}")

    # 3. artist lookup + followers
    try:
        artist_info = sp.artist(results["artist_id"])
        ok(
            f"artist lookup: followers={artist_info['followers']['total']}, "
            f"genres={artist_info['genres']}"
        )
    except Exception as e:
        fail(f"artist lookup failed: {e}")

    # 4. audio_features - expected to fail with 403
    try:
        sp.audio_features([results["track_id"]])
        fail(
            "audio_features succeeded — unexpected. Either Spotify changed policy, "
            "or this app has a legacy quota extension. Re-check assumptions before relying on it."
        )
    except SpotifyException as e:
        if e.http_status == 403:
            ok(f"audio_features correctly returned 403 ({e})")
        else:
            fail(f"audio_features failed with unexpected status {e.http_status}: {e}")
    except Exception as e:
        fail(f"audio_features raised unexpected error type: {e}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
