"""Add songs from Spotify playlists / artists (and named artists) to the YouTube pool list, inside the existing genres.

  python spotify_read.py ...                       # (helper) the track lists were read from the public embed pages and
                                                   #   saved in spotify_tracks.json
  python build_from_spotify.py --dry-run --limit 5 # try a few first
  python build_from_spotify.py                     # search YouTube (yt-dlp, no API quota), write pool_youtube.csv

For each track: search YouTube for "artist title" and accept a result ONLY when the title matches, the artist is in the
channel or title, and the length is within a few seconds of Spotify's length (so a cover, remix or reaction is not taken for
the song). Songs with no verified match are listed at the end and skipped. At most MAX_PER_ARTIST songs per artist.
Named artists (NAMED) have no track list: their most-viewed songs from their own channel are taken instead.
The audio is not downloaded here; run_tests.py analyses the list later and deletes the audio after each song.
"""
import argparse, csv, json, os, re, sys, unicodedata
import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_youtube import NOT_A_SONG
from results_index import pool_keys, latest_rows, write_list, RES

SOURCES = os.path.join(HERE, "spotify_tracks.json")
CACHE = os.path.join(RES, "spotify_match_cache.json")
POOL = os.path.join(HERE, "pool_youtube.csv")
MAX_PER_ARTIST = 3
# genre family (an EXISTING pool genre) for each source; the group is yt_<genre>
GENRE_OF_SOURCE = {"0LvYmZs7u4gUEh2e1z7Yk3": "electronic",     # The Best of NCS
                   "3jTU1IOqkO7Mz4zdbXPose": "pop",            # Stephen Dawes
                   "7FDAVjogXVbKRjCoUMjAHU": "hiphop",         # Independent/Underrated Artists 2024/2025 (mostly UK rap)
                   "4xjI8zUp95YgPxtP9aXduA": "indie",          # underrated artists you've never heard
                   "79uwjet39OoutEPSd1NLQY": "rnb"}            # Underrated RnB Songs
NAMED = {"ruel": ("Ruel", "rnb"), "jupiterkid": ("jupiterkid", "indie"), "2hollis": ("2hollis", "electronic")}


def norm(s):
    """Lower case words; accents folded (Monae = Monáe) but Korean / Japanese / Chinese letters kept."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()
    return re.sub(r"[^\w]+", " ", s.replace("_", " ")).split()


def clean_title(t):
    return re.sub(r"[\(\[].*?[\)\]]|\bfeat\.?.*$|\bwith\b.*$|\s-\s.*(remaster|version|edit).*$", "", t or "", flags=re.I).strip() or t


def verify(e, title, artists, dur):
    """True when a search result really is this song."""
    ct, cc = norm(e.get("title")), norm(e.get("channel") or e.get("uploader"))
    if NOT_A_SONG.search(e.get("title") or "") or e.get("is_live"):
        return False
    if re.search(r"\b(cover|remix|slowed|sped|nightcore|reaction|live|instrumental|lyrics? video)\b", " ".join(ct)) \
            and not re.search(r"\b(cover|remix|slowed|live)\b", (title or "").lower()):
        return False
    t = norm(clean_title(title))
    first = norm(artists.split(",")[0])
    if not t or not first:
        return False
    title_ok = sum(w in ct for w in t) >= max(1, int(0.8 * len(t) + 0.5))
    artist_ok = sum(w in (ct + cc) for w in first) >= max(1, int(0.7 * len(first) + 0.5))
    d = e.get("duration") or 0
    dur_ok = (not dur) or abs(d - dur) <= max(8.0, 0.04 * dur)
    return title_ok and artist_ok and dur_ok and 60 <= d <= 600


def official_rank(e, artists):
    cc = " ".join(norm(e.get("channel") or e.get("uploader")))
    first = " ".join(norm(artists.split(",")[0]))
    return (first in cc or cc.endswith("topic")), e.get("view_count") or 0


def flat_search(ydl, q, n):
    try:
        return ydl.extract_info(f"ytsearch{n}:{q}", download=False).get("entries", [])
    except Exception as ex:
        print("   search failed:", str(ex)[:80])
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tracks of each source (testing)")
    ap.add_argument("--sources", default=SOURCES, help="JSON file of sources (default spotify_tracks.json). An entry may carry "
                    "'genre' (an existing pool genre) and, for kind=artist, 'more': N extra songs from the artist's own channel "
                    "(default 25 from spotify_artists.py; their Spotify top 10 are always tried too)")
    ap.add_argument("--no-named", action="store_true", help="skip the built-in NAMED artists (ruel, jupiterkid, 2hollis)")
    a = ap.parse_args()
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    sources = json.load(open(a.sources, encoding="utf-8"))
    existing = list(csv.DictReader(open(POOL, encoding="utf-8-sig"))) if os.path.exists(POOL) else []
    taken = set(pool_keys()) | set(latest_rows()) | {f"youtube_{r['track_id']}" for r in existing}
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True})
    rows, missed, per_artist = [], [], {}

    def add(e, title, artist, genre):
        vid = e["id"]
        if f"youtube_{vid}" in taken:
            return False
        taken.add(f"youtube_{vid}")
        rows.append(dict(source="youtube", track_id=vid, title=title, artist=artist, duration=e.get("duration"),
                         listens=e.get("view_count") or 0, licence="youtube-standard",
                         listen=f"https://www.youtube.com/watch?v={vid}", site_genre=genre, group=f"yt_{genre}", i_agree=""))
        return True

    for src in sources:
        genre = src.get("genre") or GENRE_OF_SOURCE.get(src["id"], "indie")
        print(f"\n== {src['name']} ({len(src['tracks'])} tracks) -> yt_{genre}")
        for t in (src["tracks"][: a.limit] if a.limit else src["tracks"]):
            title, artists = t["title"], (t["artists"] or "").replace("\xa0", " ")
            first = artists.split(",")[0].strip()
            if per_artist.get(first.lower(), 0) >= (10 if src.get("kind") == "artist" else MAX_PER_ARTIST):
                continue
            ck = f"{first}|{title}"
            if ck not in cache:
                cands = [e for e in flat_search(ydl, f"{first} {clean_title(title)}", 6) if verify(e, title, artists, t["seconds"])]
                cands.sort(key=lambda e: official_rank(e, artists), reverse=True)
                cache[ck] = cands[0] if cands else None
                json.dump(cache, open(CACHE, "w", encoding="utf-8"))
            e = cache[ck]
            if not e:
                missed.append(f"{title} - {artists}")
                continue
            if add(e, title, first, genre):
                per_artist[first.lower()] = per_artist.get(first.lower(), 0) + 1

    def named_songs(name, genre, n):
        """The artist's most-viewed songs from their OWN channel (channel name contains the artist's name)."""
        ck = f"named|{name.lower()}|{n}"
        if ck not in cache:
            # a bigger ask needs a deeper search: ~4 results per wanted song (40-100), from two queries merged (10 Oct: more songs per artist)
            depth = max(40, min(100, 4 * n))
            ents, ids = [], set()
            for q in (name, f"{name} official audio"):
                for e in flat_search(ydl, q, depth):
                    if e.get("id") not in ids:
                        ids.add(e.get("id")); ents.append(e)
            nm = norm(name)
            own = [e for e in ents if nm and all(w in " ".join(norm(e.get("channel") or e.get("uploader"))) for w in nm)
                   and not NOT_A_SONG.search(e.get("title") or "") and 90 <= (e.get("duration") or 0) <= 480]
            seen, pick = set(), []
            for e in sorted(own, key=lambda e: -(e.get("view_count") or 0)):
                k = " ".join(norm(clean_title(e.get("title"))))
                if k in seen:
                    continue
                seen.add(k); pick.append(e)
            cache[ck] = pick[:n]
            json.dump(cache, open(CACHE, "w", encoding="utf-8"))
        got = 0
        for e in cache[ck]:
            title = re.sub(rf"^{re.escape(name)}\s*[-–:]\s*", "", e.get("title") or "", flags=re.I)
            got += add(e, title, name, genre)
        print(f"  {name}: {got} songs from their own channel" + ("" if got else "   (none found on a channel with that name: send me a link)"))

    print("\n== named artists (their most-viewed songs on their own channel)")
    for key, (name, genre) in ({} if a.no_named else NAMED).items():
        named_songs(name, genre, 6)
    for src in sources:                                  # artist pages: also their own channel's other songs ("more": N)
        if src.get("kind") == "artist" and src.get("more"):
            named_songs(src["name"], src.get("genre") or "indie", int(src["more"]))

    print(f"\n{len(rows)} verified songs to add; {len(missed)} tracks had no verified YouTube match (skipped)")
    for m in missed[:40]:
        print("   no match:", m)
    if len(missed) > 40:
        print(f"   ... and {len(missed) - 40} more")
    if a.dry_run or not rows:
        print("(dry run: nothing written)" if a.dry_run else "nothing to add")
        return
    write_list(POOL, existing + rows)
    print(f"pool_youtube.csv now has {len(existing) + len(rows)} songs (+{len(rows)}). Analyse them with run_tests.py --list pool_youtube.csv")


if __name__ == "__main__":
    main()
