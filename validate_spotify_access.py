"""
Milestone 0 sanity check: confirm Spotify's Client Credentials flow works for
this app's credentials and that search/track/artist lookups succeed, confirm
audio-features fails with 403 as expected, and confirm Deezer supplies the
popularity/obscurity signal (Spotify no longer returns popularity/followers/
genres for apps without a quota extension - confirmed live, broader than the
original audio-features-only deprecation).

Usage:
    1. Copy .env.example to .env and fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
       from https://developer.spotify.com/dashboard
    2. python validate_spotify_access.py
"""

import os
import sys

import requests
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
        results["track_name"] = track["name"]
        results["artist_name"] = track["artists"][0]["name"]
    except Exception as e:
        fail(f"search failed: {e}")
        return 1

    # 2. track lookup (metadata only - popularity is no longer returned)
    try:
        sp.track(results["track_id"])
        ok("track lookup succeeded (note: 'popularity' field is no longer returned by this app)")
    except Exception as e:
        fail(f"track lookup failed: {e}")

    # 3. artist lookup (metadata only - followers/genres no longer returned)
    try:
        sp.artist(results["artist_id"])
        ok("artist lookup succeeded (note: 'followers'/'genres' fields are no longer returned by this app)")
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

    # 5. Deezer - our actual popularity/obscurity source (rank + artist nb_fan)
    try:
        deezer_search = requests.get(
            "https://api.deezer.com/search",
            params={"q": f"{results['track_name']} {results['artist_name']}"},
            timeout=10,
        ).json()
        deezer_track = deezer_search["data"][0]
        deezer_artist = requests.get(
            f"https://api.deezer.com/artist/{deezer_track['artist']['id']}", timeout=10
        ).json()
        ok(
            f"Deezer popularity signal: rank={deezer_track['rank']}, "
            f"artist nb_fan={deezer_artist['nb_fan']}, preview={'yes' if deezer_track.get('preview') else 'no'}"
        )
    except Exception as e:
        fail(f"Deezer lookup failed: {e}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
