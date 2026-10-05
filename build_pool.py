"""Build the REAL recommendation pool from today's Jamendo catalogue, balanced by genre.

  python build_pool.py                  -> pool_list.csv (about 60 downloadable songs per genre, ~1,000 total)
  python build_pool.py --per-genre 150  -> bigger pool (~2,700)
  python build_pool.py --audius-per-genre 0   -> Jamendo only (default adds ~30 Audius songs per genre)
  python build_pool.py --audius-only          -> Audius part only, into pool_audius.csv (pool_list.csv untouched)
  python build_pool.py --korean 100           -> Korean R&B and hip-hop from Audius + Korean-sung Jamendo songs (up to 100 each), into pool_korean.csv
  python build_pool.py --vocal 30             -> up to 30 songs WITH singing per popular genre (20 genres), into pool_vocal.csv
  python build_pool.py --vocal 150 --focus    -> tops the 8 focus genres up to 150 vocal songs each (adds, never replaces)
  python build_pool.py --expand-artists 8     -> other downloadable songs by Audius artists already in the pool (max 8 each)

Rules: only songs Jamendo marks as downloadable; 1-10 minutes long; one song per artist per genre
(no artist floods the pool); songs from the MTG-Jamendo TEST split are excluded so the final
test stays honest. Popularity (listens) is kept for the obscurity score.
Then:  nohup python -u run_tests.py --list pool_list.csv > run_pool.log 2>&1 &
"""
import argparse, csv, os, random
import sources
from results_index import write_list

HERE = os.path.dirname(os.path.abspath(__file__))
P = lambda fn: os.path.join(HERE, fn)          # every file next to this script, whatever folder you run it from

GENRE_TAGS = ["rock", "metal", "punk", "pop", "hiphop", "electronic", "techno", "drumnbass", "ambient",
              "classical", "jazz", "blues", "folk", "country", "reggae", "latin", "world", "soul",
              "funk", "lounge", "chillout", "soundtrack"]


def test_split_ids():
    p = os.path.join(HERE, "data", "split0-autotagging-test.tsv")
    if not os.path.exists(p):
        return set()
    with open(p) as f:
        next(f)
        return {int(l.split("\t")[0].split("_")[1]) for l in f}


AUDIUS_GENRES = ["Rock", "Metal", "Punk", "Pop", "Hip-Hop/Rap", "Electronic", "Techno", "Drum & Bass", "Ambient",
                 "Classical", "Jazz", "Blues", "Folk", "Country", "Reggae", "Latin", "World", "R&B/Soul", "Funk",
                 "Lo-Fi", "Acoustic", "Soundtrack"]


EXTRA_WORDS = ["", "music", "song", "beat", "instrumental", "original", "demo", "track"]


def audius_part(per_genre):
    """Downloadable, not-gated Audius tracks, one per artist per genre. Audius's play_count is its popularity.
    Few Audius tracks allow downloads, so each genre is searched several ways (different words, pages,
    and the trending lists) until it has enough. Prints where songs drop out, so a shortfall is explained."""
    out, used = [], set()
    for g in AUDIUS_GENRES:
        got, artists, short = [], set(), {"too short/long": 0, "same artist": 0}
        base = g.split("/")[0]

        def take(found):
            for t in found:
                if t["id"] in used:
                    continue
                if not 60 <= t["duration"] <= 600:
                    short["too short/long"] += 1; continue
                if t.get("artist_id") in artists:
                    short["same artist"] += 1; continue
                got.append(t); used.add(t["id"]); artists.add(t.get("artist_id"))
                if len(got) >= per_genre:
                    return True
            return False

        attempts = [("search", w, off) for w in EXTRA_WORDS for off in (0, 100)] + \
                   [("trending", t, 0) for t in ("allTime", "month", "week")] + [("underground", None, o) for o in (0, 100)]
        for kind, arg, off in attempts:
            if len(got) >= per_genre:
                break
            try:
                if kind == "search":
                    found = sources.audius_search((base + " " + arg).strip(), limit=100, genre=g, offset=off)
                elif kind == "trending":
                    found = sources.audius_trending(genre=g, time=arg)
                else:
                    found = sources.audius_trending(genre=g, underground=True, offset=off)
            except Exception as e:
                print(f"  Audius {kind} failed for {g}: {e}"); continue
            if take(found):
                break
        print(f"pool_audius_{g:14s} {len(got):3d}   (skipped: {short['too short/long']} too short/long, {short['same artist']} same artist)")
        for t in got:
            out.append(dict(group=f"pool_audius_{g.lower().replace(' ', '').replace('/', '_').replace('&', 'and')}",
                            source="audius", track_id=t["id"], jamendo_id="", title=t.get("title"), artist=t.get("artist"),
                            album="", duration=t["duration"], tags=g, listens=t.get("listens"), licence=t.get("licence"),
                            site_genre=t.get("genre"), site_mood=t.get("mood"), site_bpm=t.get("site_bpm"),
                            bpm_custom=t.get("bpm_custom"), listen=t.get("page"), expect="recommendation pool", i_agree=""))
    st = sources.AUDIUS_STATS
    print(f"Audius: {st['returned']} tracks seen, {st['not_downloadable']} not downloadable, {st['kept']} downloadable")
    return out


# ------------------------------------------------------------------ Korean R&B / hip-hop on Audius
KOREAN_SEARCHES = {
    "korean_rnb": (["korean r&b", "korean rnb", "k-r&b", "krnb", "k-rnb", "한국 알앤비", "알앤비", "케이알앤비"], ["R&B/Soul", None]),
    "korean_hiphop": (["korean hip hop", "korean rap", "khiphop", "k-hiphop", "k-rap", "한국 힙합", "힙합", "랩"], ["Hip-Hop/Rap", None]),
}
KOREAN_WORDS = ("korean", "korea", "k-r&b", "krnb", "k-rnb", "khiphop", "k-hiphop", "k-rap", "seoul", "busan")


def looks_korean(t):
    """Hangul anywhere in title/artist/tags/description, or an explicit Korean tag. Search alone isn't enough:
    'korean rnb' also returns plenty of non-Korean songs."""
    text = " ".join(str(t.get(k) or "") for k in ("title", "artist", "tags", "description", "handle"))
    if any("\uac00" <= ch <= "\ud7a3" or "\u1100" <= ch <= "\u11ff" or "\u3130" <= ch <= "\u318f" for ch in text):
        return True
    low = text.lower()
    return any(w in low for w in KOREAN_WORDS)


def korean_part(per_style):
    out, used = [], set()
    for style, (queries, genres) in KOREAN_SEARCHES.items():
        got, artists, skipped = [], {}, {"not Korean": 0, "length": 0, "artist limit": 0}
        for q in queries:
            for g in genres:
                for off in (0, 100):
                    if len(got) >= per_style:
                        break
                    try:
                        found = sources.audius_search(q, limit=100, genre=g, offset=off)
                    except Exception as e:
                        print(f"  search failed ({q}, {g}): {e}"); continue
                    for t in found:
                        if t["id"] in used:
                            continue
                        if not looks_korean(t):
                            skipped["not Korean"] += 1; continue
                        if not 60 <= t["duration"] <= 600:
                            skipped["length"] += 1; continue
                        if artists.get(t.get("artist_id"), 0) >= 2:      # at most 2 songs per artist
                            skipped["artist limit"] += 1; continue
                        got.append(t); used.add(t["id"]); artists[t.get("artist_id")] = artists.get(t.get("artist_id"), 0) + 1
                        if len(got) >= per_style:
                            break
        print(f"pool_audius_{style:14s} {len(got):3d} songs from {len(artists)} artists   (skipped: "
              + ", ".join(f"{v} {k}" for k, v in skipped.items()) + ")")
        for t in got:
            out.append(dict(group=f"pool_audius_{style}", source="audius", track_id=t["id"], jamendo_id="",
                            title=t.get("title"), artist=t.get("artist"), album="", duration=t["duration"],
                            tags=t.get("tags", ""), listens=t.get("listens"), licence=t.get("licence"),
                            site_genre=t.get("genre"), site_mood=t.get("mood"), site_bpm=t.get("site_bpm"),
                            bpm_custom=t.get("bpm_custom"), listen=t.get("page"), expect="recommendation pool", i_agree=""))
    return out


# ------------------------------------------------------------------ more songs from artists already in the pool
def expand_artists(per_artist, lists=("pool_audius.csv", "pool_korean.csv", "pool_list.csv", "pool_audius_more.csv")):
    """Artists who allow downloads on one song often allow it on others. For every Audius artist already in a
    pool list, add their other downloadable songs, up to `per_artist` songs per artist in total (so no artist
    floods the pool). New songs keep the group of the artist's first song, so genre groups stay meaningful."""
    rows, have = [], set()
    for fn in lists:
        if os.path.exists(P(fn)):
            with open(P(fn), encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get("source") == "audius":
                        rows.append(r); have.add(r["track_id"])
    more_before = []
    if os.path.exists(P("pool_audius_more.csv")):               # earlier expansions are kept, not replaced
        with open(P("pool_audius_more.csv"), encoding="utf-8-sig") as f:
            more_before = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("no Audius songs in the pool lists yet (run --audius-only / --korean first)")
    by_artist = {}
    for i, r in enumerate(rows):
        try:
            aid = sources.audius_track_owner(r["track_id"])
        except Exception as e:
            print(f"  lookup failed for {r['track_id']}: {e}"); continue
        if aid:
            by_artist.setdefault(aid, []).append(r)
        if (i + 1) % 50 == 0:
            print(f"  looked up {i + 1}/{len(rows)} songs")
    out = []
    for aid, theirs in by_artist.items():
        room = per_artist - len(theirs)
        if room <= 0:
            continue
        try:
            found = sources.audius_user_tracks(aid) + sources.audius_user_tracks(aid, offset=100)
        except Exception as e:
            print(f"  artist {aid}: {e}"); continue
        first = theirs[0]
        for t in sorted(found, key=lambda t: t.get("listens") or 0):      # least played first: the hidden ones
            if room <= 0:
                break
            if t["id"] in have or not 60 <= t["duration"] <= 600:
                continue
            have.add(t["id"]); room -= 1
            out.append(dict(group=first["group"], source="audius", track_id=t["id"], jamendo_id="",
                            title=t.get("title"), artist=t.get("artist"), album="", duration=t["duration"],
                            tags=t.get("tags", "") or first.get("tags", ""), listens=t.get("listens"),
                            licence=t.get("licence"), site_genre=t.get("genre"), site_mood=t.get("mood"),
                            site_bpm=t.get("site_bpm"), bpm_custom=t.get("bpm_custom"), listen=t.get("page"),
                            expect="recommendation pool", i_agree=""))
    out = more_before + out
    n_art = len({r["artist"] for r in out})
    print(f"{len(by_artist)} Audius artists in the pool; added {len(out)} more songs from {n_art} of them "
          f"(cap {per_artist} songs per artist)")
    return out


def korean_jamendo(per_style):
    """Korean songs on Jamendo. Its lyrics-language filter (lang=ko) returns 'Internal Error', so this uses text
    search (English and Korean words) and the kpop tag instead, then keeps only songs that look Korean (Hangul or
    'korean'/'seoul'/... in title, artist, album or tags). Sorted into R&B, hip-hop and other by Jamendo's genre tags.
    Search hits include some non-Korean 'Korean-style' library music, so check the list before trusting it."""
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if not cid:
        print("  JAMENDO_CLIENT_ID not set: Jamendo part skipped"); return []
    banned = test_split_ids(); out, used, per_artist = [], set(), {}
    count = {"korean_rnb": 0, "korean_hiphop": 0, "korean_other": 0}
    seen = errors = not_korean = 0
    searches = [("search", q) for q in ("korean r&b", "korean rnb", "k-r&b", "korean soul", "korean hip hop",
                                         "korean rap", "k-hiphop", "korean", "k-pop", "kpop", "seoul",
                                         "한국", "알앤비", "힙합", "랩", "서울", "사랑")] + [("tags", "kpop"), ("tags", "korean")]
    for kind, q in searches:
        for offset in (0, 200, 400):
            params = {"client_id": cid, "format": "json", "limit": 200, "offset": offset,
                      "include": "stats musicinfo", "audiodlformat": "mp32", kind: q}
            try:
                j = sources._get(f"{sources.JAMENDO}/tracks/", params=params).json()
            except Exception as e:
                errors += 1; print(f"  Jamendo {kind} '{q}' failed: {e}"); break
            h = j.get("headers") or {}
            if h.get("status") == "failed":
                errors += 1; print(f"  Jamendo {kind} '{q}': {h.get('error_message')}"); break
            res = j.get("results", [])
            if not res:
                break
            seen += len(res)
            for t in res:
                tid = int(t["id"])
                if tid in used:
                    continue
                g = ((t.get("musicinfo") or {}).get("tags") or {}).get("genres") or []
                info = {"title": t.get("name"), "artist": t.get("artist_name"), "tags": " ".join(g),
                        "description": t.get("album_name"), "handle": ""}
                if not looks_korean(info):
                    not_korean += 1; continue
                if (tid in banned or not t.get("audiodownload_allowed")
                        or not 60 <= float(t.get("duration") or 0) <= 600 or per_artist.get(t.get("artist_id"), 0) >= 3):
                    continue
                gl = " ".join(g).lower()
                style = ("korean_rnb" if any(w in gl for w in ("rnb", "soul", "r&b")) else
                         "korean_hiphop" if any(w in gl for w in ("hiphop", "hip-hop", "rap", "trap")) else "korean_other")
                if count[style] >= per_style:
                    continue
                used.add(tid); per_artist[t.get("artist_id")] = per_artist.get(t.get("artist_id"), 0) + 1; count[style] += 1
                st = t.get("stats") or {}
                out.append(dict(group=f"pool_jamendo_{style}", source="jamendo", track_id=tid, jamendo_id=tid,
                                title=t.get("name"), artist=t.get("artist_name"), album=t.get("album_name"),
                                duration=t.get("duration"), tags=" ".join(g),
                                listens=next((st[k] for k in sources.LISTEN_KEYS if st.get(k) not in (None, "")), ""),
                                licence=t.get("license_ccurl", ""), site_genre="", site_mood="", site_bpm="", bpm_custom="",
                                listen=t.get("shareurl", ""), expect="recommendation pool", i_agree=""))
    for style, n in count.items():
        print(f"pool_jamendo_{style:13s} {n:3d} songs")
    print(f"Jamendo: {seen} search hits, {not_korean} didn't look Korean, {len(out)} kept "
          f"(downloadable, 1-10 min, max 3 per artist, not in the test split)" + (f"; {errors} searches failed" if errors else ""))
    if out:
        print("  check these by ear: search hits include some 'Korean-style' library music by non-Korean producers")
    return out

# ------------------------------------------------------------------ songs with singing (most listeners want vocals)
VOCAL_TAGS = ["pop", "rnb", "soul", "hiphop", "rap", "rock", "indie", "alternative", "folk", "singersongwriter",
              "electronic", "dance", "latin", "reggae", "country", "punk", "metal", "funk", "jazz", "blues"]


FOCUS_TAGS = ["pop", "rnb", "hiphop", "indie", "alternative", "rock", "singersongwriter", "electronic"]


def vocal_part(per_genre, tags=None):
    """Downloadable Jamendo songs WITH singing, across popular genres. Jamendo's vocal/instrumental filter is used,
    and each result's own label is checked too (Jamendo's language filter turned out to be broken, so no filter
    is trusted blindly). Skips songs already in any pool list and the final-test songs; one song per artist per genre."""
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if not cid:
        raise SystemExit("Set JAMENDO_CLIENT_ID first")
    from results_index import POOL_LISTS, list_key
    have = set()
    for fn in POOL_LISTS:
        if os.path.exists(P(fn)):
            with open(P(fn), encoding="utf-8-sig") as f:
                have |= {list_key(r) for r in csv.DictReader(f)}
    banned = test_split_ids(); random.seed(11)
    out, used, not_vocal, failed = [], set(), 0, 0
    # songs per genre already in pool_vocal.csv count towards the target, so a later run only tops up
    already = {}
    if os.path.exists(P("pool_vocal.csv")):
        with open(P("pool_vocal.csv"), encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                already[r["tags"]] = already.get(r["tags"], 0) + 1
    for g in (tags or VOCAL_TAGS):
        got, artists = [], set()
        need = per_genre - already.get(g, 0)
        if need <= 0:
            print(f"pool_vocal_{g:17s} already {already.get(g, 0)}"); continue
        for offset in (0, 200, 400, 800, 1600, 2400, 3200):
            if len(got) >= need:
                break
            if len(got) >= per_genre:
                break
            try:
                j = sources._get(f"{sources.JAMENDO}/tracks/", params={
                    "client_id": cid, "format": "json", "limit": 200, "offset": offset, "tags": g,
                    "vocalinstrumental": "vocal", "include": "stats musicinfo", "audiodlformat": "mp32"}).json()
            except Exception as e:
                failed += 1; print(f"  {g}: search failed ({e})"); break
            if (j.get("headers") or {}).get("status") == "failed":
                failed += 1; print(f"  {g}: Jamendo error: {(j.get('headers') or {}).get('error_message')}"); break
            res = j.get("results", [])
            if not res:
                break
            random.shuffle(res)
            for t in res:
                tid = int(t["id"])
                vi = ((t.get("musicinfo") or {}).get("vocalinstrumental") or "").lower()
                if vi and vi != "vocal":
                    not_vocal += 1; continue
                if (tid in used or f"jamendo_{tid}" in have or tid in banned or not t.get("audiodownload_allowed")
                        or not 60 <= float(t.get("duration") or 0) <= 600 or t.get("artist_id") in artists):
                    continue
                got.append(t); used.add(tid); artists.add(t.get("artist_id"))
                if len(got) >= need:
                    break
        print(f"pool_vocal_{g:17s} +{len(got):3d}  (now {already.get(g, 0) + len(got)})")
        for t in got:
            st = t.get("stats") or {}
            out.append(dict(group=f"pool_vocal_{g}", source="jamendo", track_id=int(t["id"]), jamendo_id=int(t["id"]),
                            title=t.get("name"), artist=t.get("artist_name"), album=t.get("album_name"),
                            duration=t.get("duration"), tags=g,
                            listens=next((st[k] for k in sources.LISTEN_KEYS if st.get(k) not in (None, "")), ""),
                            licence=t.get("license_ccurl", ""), site_genre="", site_mood="", site_bpm="", bpm_custom="",
                            listen=t.get("shareurl", ""), expect="recommendation pool (vocal)", i_agree=""))
    print(f"Jamendo: {len(out)} vocal songs kept" + (f"; {not_vocal} results were labelled instrumental and skipped" if not_vocal else "")
          + (f"; {failed} searches failed" if failed else ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-genre", type=int, default=60)
    ap.add_argument("--audius-per-genre", type=int, default=30)
    ap.add_argument("--audius-only", action="store_true",
                    help="only build the Audius part, into pool_audius.csv (pool_list.csv is left alone)")
    ap.add_argument("--korean", type=int, default=0, metavar="N",
                    help="only Korean R&B and hip-hop from Audius, up to N songs each, into pool_korean.csv")
    ap.add_argument("--expand-artists", type=int, default=0, metavar="N",
                    help="add more downloadable songs by Audius artists already in the pool, up to N songs per artist, "
                         "into pool_audius_more.csv")
    ap.add_argument("--vocal", type=int, default=0, metavar="N",
                    help="Jamendo songs WITH singing: top up to N per genre in pool_vocal.csv (adds, never replaces)")
    ap.add_argument("--focus", action="store_true",
                    help="with --vocal: only the 8 focus genres (" + ", ".join(FOCUS_TAGS) + ")")
    a = ap.parse_args()
    if a.vocal:
        out = vocal_part(a.vocal, FOCUS_TAGS if a.focus else None)
        if not out:
            raise SystemExit("no new vocal songs found")
        if os.path.exists(P("pool_vocal.csv")):              # keep every song already in the list
            with open(P("pool_vocal.csv"), encoding="utf-8-sig") as f:
                out = list(csv.DictReader(f)) + out
        write_list(P("pool_vocal.csv"), out)
        print("\npool_vocal.csv written. Analyse with: "
              "nohup python -u run_tests.py --list pool_vocal.csv > pool_vocal.log 2>&1 &")
        return
    if a.expand_artists:
        out = expand_artists(a.expand_artists)
        if not out:
            raise SystemExit("no extra songs found")
        write_list(P("pool_audius_more.csv"), out)
        print("pool_audius_more.csv written. Analyse with: "
              "nohup python -u run_tests.py --list pool_audius_more.csv > pool_more.log 2>&1 &")
        return
    if a.korean:
        out = korean_part(a.korean)
        st = sources.AUDIUS_STATS
        print(f"Audius: {st['returned']} tracks seen, {st['not_downloadable']} not downloadable, {st['kept']} downloadable\n")
        out += korean_jamendo(a.korean)
        if not out:
            raise SystemExit("no downloadable Korean R&B / hip-hop songs found on Audius or Jamendo")
        write_list(P("pool_korean.csv"), out)
        print(f"\npool_korean.csv: {len(out)} songs. Analyse with: "
              "nohup python -u run_tests.py --list pool_korean.csv > pool_korean.log 2>&1 &")
        return
    if a.audius_only:
        out = audius_part(a.audius_per_genre)
        if not out:
            raise SystemExit("no Audius songs found")
        write_list(P("pool_audius.csv"), out)
        print(f"\npool_audius.csv: {len(out)} Audius songs. Analyse with: "
              "nohup python -u run_tests.py --list pool_audius.csv > pool_audius.log 2>&1 &")
        return
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if not cid:
        raise SystemExit("Set JAMENDO_CLIENT_ID first")
    random.seed(5)
    banned = test_split_ids()
    used, out = set(), []
    for g in GENRE_TAGS:
        got, artists, tries = [], set(), 0
        while len(got) < a.per_genre and tries < 8:
            tries += 1
            offset = random.choice([0, 200, 400, 800, 1600, 3200]) if tries > 1 else 0
            r = sources._get(f"{sources.JAMENDO}/tracks/", params={
                "client_id": cid, "format": "json", "limit": 200, "offset": offset, "tags": g,
                "include": "stats musicinfo", "audiodlformat": "mp32"})
            res = r.json().get("results", [])
            if not res:
                continue
            random.shuffle(res)
            for t in res:
                tid = int(t["id"])
                if (tid in used or tid in banned or not t.get("audiodownload_allowed")
                        or not 60 <= float(t.get("duration") or 0) <= 600 or t.get("artist_id") in artists):
                    continue
                got.append(t); used.add(tid); artists.add(t.get("artist_id"))
                if len(got) >= a.per_genre:
                    break
        print(f"pool_{g:12s} {len(got)}")
        for t in got:
            st = t.get("stats") or {}
            out.append(dict(group=f"pool_{g}", source="jamendo", track_id=int(t["id"]), jamendo_id=int(t["id"]),
                            title=t.get("name"), artist=t.get("artist_name"), album=t.get("album_name"),
                            duration=t.get("duration"), tags=g,
                            listens=next((st[k] for k in sources.LISTEN_KEYS if st.get(k) not in (None, "")), ""),
                            licence=t.get("license_ccurl", ""), site_genre="", site_mood="", site_bpm="", bpm_custom="",
                            listen=t.get("shareurl", ""), expect="recommendation pool", i_agree=""))
    if a.audius_per_genre:
        out += audius_part(a.audius_per_genre)
    write_list(P("pool_list.csv"), out)
    nj = sum(o["source"] == "jamendo" for o in out)
    print(f"\npool_list.csv: {len(out)} songs ({nj} Jamendo, {len(out) - nj} Audius)")


if __name__ == "__main__":
    main()
