"""Grow the recommendation pool with LOWER-VIEW YouTube songs, balanced by genre.

Why: the Jamendo/Audius/FMA pool skews instrumental and is thin in popular vocal genres (K-pop, Korean R&B,
Mandopop/Cantopop, ...). This picks the *least-viewed* music videos per genre so the songs we add still fit the
"hidden gems" idea. Only metadata is taken here, from the official YouTube Data API (a key you already have for
check_youtube.py). The audio is fetched later by run_tests.py with yt-dlp and DELETED straight after analysis -
nothing but the numbers is ever kept. These tracks are marked source=youtube, licence=youtube-standard (or
creativeCommon when YouTube says so), so the catalogue stays honest about where they came from.

  export YOUTUBE_API_KEY=...                 # once, in ~/.bashrc (never in code or screenshots)
  python build_youtube.py --list-genres      # the genre searches it will run
  python build_youtube.py                     # ~40 low-view songs per default genre -> pool_youtube.csv
  python build_youtube.py --per 30 --max-views 30000
  python build_youtube.py --genres kpop krnb cpop --per 50
  python build_youtube.py --cc-only           # keep only Creative-Commons-licensed videos

Then analyse them (audio is temporary and deleted after each song):
  nohup python -u run_tests.py --list pool_youtube.csv > pool_youtube.log 2>&1 &

Quota: each genre costs ~100 units per page of results (search.list); the free key allows ~10,000 units/day
(about 100 searches). The run is additive and resumable - it merges into pool_youtube.csv and skips songs already
listed or already analysed - so if the quota runs out, just run it again tomorrow. Marks you make in the
i_agree column (n = "wrong genre, drop it") are carried over, like every other pool list.
"""
import argparse, os, re, sys, time
import requests
import sources
from results_index import write_list, pool_keys, latest_rows, HERE

API = "https://www.googleapis.com/youtube/v3"
MUSIC_CATEGORY = "10"                     # YouTube's "Music" category, to skip talking/gameplay videos

# Genre -> the words searched on YouTube. Tuned for the gaps in the current pool; override with --genres.
DEFAULT_GENRES = {
    "kpop":     "kpop b-side",
    "krnb":     "korean r&b soul",
    "khiphop":  "korean hip hop",
    "cpop":     "mandopop indie",
    "cantopop": "cantopop",
    "jpop":     "j-pop indie",
    "vocal_pop":"indie pop vocal",
    "rnb":      "r&b soul vocal",
    "hiphop":   "underground hip hop",
    "singer":   "singer songwriter acoustic vocal",
    # added 7 Oct: phrases close to the project owner's own playlist, plus a few more mainstream gaps
    "kindie":   "korean indie",
    "kballad":  "korean ballad",
    "klofi":    "korean lofi hip hop",
    "mrnb":     "mandarin r&b",
    "chiphop":  "chinese hip hop",
    "twindie":  "taiwan indie",
    "jrnb":     "japanese r&b",
    "citypop":  "city pop",
    "indiepop": "bedroom pop",
    "indierock": "indie rock band",
    "altrock":  "alternative rock band",
    "indiefolk": "indie folk",
    "electro":  "melodic electronic vocal",
    # western families that already exist in the pool (from build_underrated.py) but had no search of their own
    "rock":        "rock band new song",
    "pop":         "pop singer new song",
    "alternative": "alternative band",
    "electronic":  "electronic vocal track",
    "indie":       "indie band",
}

# More variety INSIDE the existing genres (no new genres): other sub-styles, languages and scenes of each genre.
# `--variety` runs these after the main search above, round by round (every genre gets its round-1 query before any
# gets its round-2 query), so a stopped or quota-limited run is still spread across all genres.
EXTRA_QUERIES = {
    "kpop":      ["korean pop new release", "k-pop girl group debut", "korean boy band b-side"],
    "krnb":      ["korean r&b", "krnb slow jam", "korean soul vocal"],
    "khiphop":   ["korean rapper new", "korean underground rap", "korean trap"],
    "cpop":      ["mandopop ballad", "chinese pop new song", "mandarin indie folk"],
    "cantopop":  ["cantonese pop ballad", "hong kong indie band", "cantonese r&b"],
    "jpop":      ["japanese pop new song", "j-rock band", "japanese indie pop"],
    "vocal_pop": ["dream pop vocal", "synth pop vocal", "bedroom pop vocal"],
    "rnb":       ["neo soul", "alternative r&b", "contemporary r&b new"],
    "hiphop":    ["conscious rap", "boom bap new", "melodic rap"],
    "singer":    ["acoustic singer songwriter original", "piano singer songwriter", "folk pop singer"],
    "kindie":    ["korean indie band", "korean indie folk", "korean shoegaze"],
    "kballad":   ["korean ost ballad", "korean piano ballad", "korean acoustic ballad"],
    "klofi":     ["korean chill hip hop", "korean lofi r&b", "korean jazz hip hop"],
    "mrnb":      ["mandopop r&b", "taiwan r&b", "chinese neo soul"],
    "chiphop":   ["chinese rap new", "chinese trap", "chinese underground rap"],
    "twindie":   ["taiwan indie band", "taiwan folk", "taiwan bedroom pop"],
    "jrnb":      ["japanese neo soul", "japanese r&b new", "japanese soul vocal"],
    "citypop":   ["japanese city pop new", "city pop inspired", "japanese funk pop vocal"],
    "indiepop":  ["indie pop new", "jangle pop", "lofi indie pop"],
    "indierock": ["indie rock new", "garage rock band", "math rock vocal"],
    "altrock":   ["alternative rock new", "post-grunge band", "emo rock band"],
    "indiefolk": ["indie folk new", "chamber folk", "folk rock band"],
    "electro":   ["synthwave vocal", "future bass vocal", "downtempo vocal"],
    "rock":      ["hard rock band new", "classic rock style band", "soft rock band"],
    "pop":       ["pop ballad new", "dance pop new", "electropop"],
    "alternative": ["alternative pop", "dark alternative", "alternative r&b rock"],
    "electronic": ["house vocal", "trip hop", "chillwave vocal"],
    "indie":     ["indie singer songwriter band", "indie electronic", "lofi indie"],
}

# Titles that are almost never an original song with singing. Found by check_youtube_quality.py: about 38% of the first
# 312 titles had a hint of this kind, and a random sample held a tutorial, a playlist teaser and a cover.
NOT_A_SONG = re.compile(
    r"\b(how to|tutorial|playlist|news|(album |music )?review|recap|deep dive|masterclass|top ?\d+|guess|quiz|tier ?list|my (top|favou?rite)|underrated|hidden gems?|b-?sides? (of|from)|best .{0,25}(songs|bands|albums|b-?sides)|compilation|megamix|full album|non-?stop|karaoke|cover(ed)?|tribute|type beat|"
    r"instrumental|reaction|trailer|podcast|asmr|interview|nightcore|slowed|sped ?up|bass boosted|mashup|bootleg|"
    r"\d+ ?(hours?|hrs?)|1 ?h(our)?|mix|explained|breakdown|play-?through|drum cover|bass cover)\b"
    r"|\bwhy\b.{0,60}\b(is|are|works?|genius|slaps)\b|\bon (drums|guitar|piano|bass|keys)\b|\bvlog\b|\ube0c\uc774\ub85c\uadf8|\bteaser\b|\bbehind the\b|\blessons?\b|\u6559\u5ba4|\u5e55\u5f8c|\u82b1\u7d6e|\u65e5\u8a18|\u6559\u5b78|\u6559\u5b66|\bmaking (film|of)\b", re.I)

_last = [0.0]


def _polite(min_gap=0.2):
    gap = time.time() - _last[0]
    if gap < min_gap:
        time.sleep(min_gap - gap)
    _last[0] = time.time()


class QuotaUsed(Exception):
    pass


def _call(path, **params):
    for attempt in range(4):
        _polite(1.0 if path == "search" else 0.2)
        try:
            r = requests.get(f"{API}/{path}", params={**params, "key": os.environ["YOUTUBE_API_KEY"]}, timeout=30)
            if r.status_code == 403 and "quota" in r.text.lower():
                raise QuotaUsed()
            if r.status_code == 429:                  # "too many requests": wait and retry; after 3 waits stop like a quota stop
                if attempt == 3:
                    raise QuotaUsed()
                time.sleep(30 * (attempt + 1))
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            raise sources.safe_exc(e) from None          # the error text would otherwise contain the API key
        return r.json()


_ISO = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _seconds(iso):
    m = _ISO.fullmatch(iso or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _clean_artist(channel_title):
    """YouTube's auto-generated music channels are named '<artist> - Topic'."""
    return re.sub(r"\s*-\s*Topic$", "", channel_title or "").strip()


def search_ids(query, pages, order):
    """Video ids for a search, newest first by default (surfaces less-viewed uploads)."""
    ids, token = [], None
    for _ in range(pages):
        data = _call("search", part="snippet", q=query, type="video", videoCategoryId=MUSIC_CATEGORY,
                     order=order, maxResults=50, **({"pageToken": token} if token else {}))
        ids += [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def video_details(ids):
    """statistics + duration + licence for up to 50 ids per call (1 quota unit each)."""
    out = {}
    for i in range(0, len(ids), 50):
        data = _call("videos", part="snippet,contentDetails,statistics,status", id=",".join(ids[i:i + 50]))
        for it in data.get("items", []):
            sn, cd, st, stt = (it.get(k) or {} for k in ("snippet", "contentDetails", "statistics", "status"))
            out[it["id"]] = dict(
                title=sn.get("title"), channel=sn.get("channelTitle"), channel_id=sn.get("channelId"),
                duration=_seconds(cd.get("duration")), views=int(st.get("viewCount") or 0),
                licence="creativeCommon" if stt.get("license") == "creativeCommon" else "youtube-standard",
                embeddable=stt.get("embeddable", True))
    return out


def pick_for_genre(genre, query, per, max_views, pages, order, cc_only, taken):
    """Lowest-view music videos for one genre: 60-600 s, <= max_views, one per channel, not already in the pool."""
    ids = search_ids(query, pages, order)
    det = video_details(ids)
    cand = []
    for vid, d in det.items():
        if f"youtube_{vid}" in taken:
            continue
        if not (60 <= d["duration"] <= 600):
            continue
        if d["views"] > max_views:
            continue
        if NOT_A_SONG.search(d["title"] or ""):          # tutorials, playlists, covers, type beats ... (see check_youtube_quality.py)
            continue
        if cc_only and d["licence"] != "creativeCommon":
            continue
        cand.append((vid, d))
    cand.sort(key=lambda vd: vd[1]["views"])        # least viewed first = most "hidden"
    rows, chans = [], set()
    for vid, d in cand:
        if d["channel_id"] in chans:                 # at most one song per channel per genre (no artist floods)
            continue
        chans.add(d["channel_id"]); taken.add(f"youtube_{vid}")
        rows.append(dict(source="youtube", track_id=vid, title=d["title"], artist=_clean_artist(d["channel"]),
                         duration=d["duration"], listens=d["views"], licence=d["licence"],
                         listen=f"https://www.youtube.com/watch?v={vid}", site_genre=genre,
                         group=f"yt_{genre}", i_agree=""))
        if len(rows) >= per:
            break
    return rows


# Searches by STYLE inside the existing genres, run with yt-dlp (`--ytdlp`): no YouTube API key and no daily quota.
# Added 7 Oct after a Fujii Kaze (Japanese soul / piano pop) request found few close matches in the pool.
STYLE_QUERIES = {
    "jpop":   ["japanese piano pop original song", "j-pop piano ballad original", "japanese soul pop vocal", "j-pop soulful vocal piano live"],
    "jrnb":   ["japanese neo soul original song", "japanese r&b original new", "japanese gospel soul pop piano", "japanese soul singer songwriter"],
    "citypop": ["japanese city pop original new song", "japanese jazz pop vocal original", "japanese funk soul pop vocal"],
    "singer": ["piano singer songwriter soul original", "soulful piano ballad original song"],
    "rnb":    ["neo soul piano original song", "gospel soul pop piano vocal"],
}


# Western pop / R&B / indie-pop, the music the friends' blind-test songs come from (the pool had only ~6% pop, ~4% soul/R&B).
# Pop punk is left out on purpose (punk is an off-pool genre).
STYLE_SETS = {
    "japanese": STYLE_QUERIES,
    # aimed at the friends' blind-test songs (8 Oct): d4vd / Malcolm Todd / Rex Orange County / Peach Tree Rascals (bedroom pop and
    # indie-pop), Khalid / Fly By Midnight (R&B-pop), Faouzia (powerful-vocal pop), The 1975 / Boys Like Girls (indie / pop-rock band)
    "taste": {
        "pop":   ["bedroom pop sad boy original song", "malcolm todd similar songs", "rex orange county similar songs",
                  "peach tree rascals similar songs", "pop ballad powerful female vocals original song", "faouzia similar songs",
                  "pop rock band catchy chorus original song", "boys like girls similar songs", "acoustic pop heartbreak original song"],
        "rnb":   ["khalid similar songs", "soft r&b male vocals original song", "fly by midnight similar songs", "r&b pop chill drive original song",
                  "alternative r&b moody original song", "smooth r&b falsetto original song", "neo soul bedroom original song",
                  "d4vd similar songs", "r&b pop hits original song 2020s"],
        "indie": ["indie pop bedroom guitar original song", "lo-fi bedroom pop vocal original song", "chill indie songs for driving original",
                  "dreamy indie pop male vocal original song", "indie rock catchy original band song", "the 1975 similar songs",
                  "synthpop indie band original song", "indie pop summer original song", "mellow indie folk pop original song"],
        "alternative": ["alt pop 2020s original song", "alternative pop moody female vocals original song", "indie pop rock band 2010s original song",
                        "alternative rock radio hit 2000s original song", "dream pop vocal original song"],
    },
    "pop": {
        "pop":   ["indie pop original song vocal", "bedroom pop new song", "pop rock band original song", "soft acoustic pop original song",
                  "pop singer songwriter original song"],
        "rnb":   ["alternative r&b original song", "bedroom r&b original song", "smooth r&b slow jam original", "indie r&b new song",
                  "soulful r&b vocal original song"],
        "indie": ["bedroom indie original song", "indie pop band original song", "dreamy indie guitar vocal song"],
        "alternative": ["alternative pop original song", "indie rock pop band original song"],
    },
}


def pick_ytdlp(genre, query, per, max_views, taken, n_search=60, by_relevance=False):
    """Same rules as pick_for_genre (60-600 s, <= max_views, not a non-song title, one per channel, new), but the search
    and the details come from yt-dlp, so the YouTube API quota is not used. Least viewed first."""
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(f"ytsearch{n_search}:{query}", download=False)
    cand = []
    for e in info.get("entries", []):
        vid, dur, views = e.get("id"), e.get("duration") or 0, e.get("view_count")
        title = e.get("title") or ""
        if not vid or f"youtube_{vid}" in taken or views is None or views > max_views or not (60 <= dur <= 600):
            continue
        if NOT_A_SONG.search(title):
            continue
        cand.append((views, vid, e))
    if not by_relevance:                             # default: least viewed first (hidden gems); else keep YouTube's own order
        cand.sort(key=lambda c: c[0])
    rows, chans = [], set()
    for views, vid, e in cand:
        ch = e.get("channel_id") or e.get("uploader_id") or e.get("channel") or e.get("uploader")
        if ch in chans:
            continue
        chans.add(ch); taken.add(f"youtube_{vid}")
        rows.append(dict(source="youtube", track_id=vid, title=e.get("title"), artist=_clean_artist(e.get("channel") or e.get("uploader")),
                         duration=e.get("duration"), listens=views, licence="youtube-standard",
                         listen=f"https://www.youtube.com/watch?v={vid}", site_genre=genre, group=f"yt_{genre}", i_agree=""))
        if len(rows) >= per:
            break
    return rows


DONE_Q = os.path.join(HERE, "results", "youtube_queries_done.json")


def load_done_queries():
    """Searches that already finished, so a re-run (after a quota stop) continues instead of paying for them again."""
    import json
    try:
        with open(DONE_Q, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_done_queries(done):
    import json
    os.makedirs(os.path.dirname(DONE_Q), exist_ok=True)
    with open(DONE_Q + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sorted(done), f)
    os.replace(DONE_Q + ".tmp", DONE_Q)


def main():
    ap = argparse.ArgumentParser(description="Add lower-view YouTube songs to the pool, by genre.")
    ap.add_argument("--per", type=int, default=40, help="songs to add per genre (default 40)")
    ap.add_argument("--max-views", type=int, default=100_000, help="skip videos above this many views (default 100k)")
    ap.add_argument("--pages", type=int, default=2, help="pages of 50 results per genre search (default 2; each costs ~100 quota)")
    ap.add_argument("--order", default="date", choices=["date", "relevance", "rating", "title"],
                    help="search order (default 'date': recent uploads tend to have fewer views)")
    ap.add_argument("--genres", nargs="*", help="genre keys to build (default: all)")
    ap.add_argument("--cc-only", action="store_true", help="keep only Creative-Commons-licensed videos")
    ap.add_argument("--variety", action="store_true",
                    help="run the EXTRA_QUERIES (other sub-styles of the same genres) instead of the main search; "
                         "--per then means songs per query")
    ap.add_argument("--ytdlp", action="store_true",
                    help="run the STYLE_QUERIES with yt-dlp (no API key, no quota); --per then means songs per query")
    ap.add_argument("--style", default="japanese", choices=sorted(STYLE_SETS), help="with --ytdlp: which STYLE_SETS to search")
    ap.add_argument("--relevance", action="store_true",
                    help="with --ytdlp: take songs in YouTube's relevance order (well-played songs are fine) instead of least viewed first")
    ap.add_argument("--list-genres", action="store_true", help="print the genre searches and exit")
    a = ap.parse_args()

    if a.list_genres:
        for g, q in DEFAULT_GENRES.items():
            print(f"  {g:10s} -> {q}")
        return
    if not a.ytdlp and not os.environ.get("YOUTUBE_API_KEY"):
        raise SystemExit("Set YOUTUBE_API_KEY first (free at https://console.cloud.google.com -> YouTube Data API v3)")

    genres = {g: DEFAULT_GENRES[g] for g in a.genres} if a.genres else dict(DEFAULT_GENRES)
    out_path = os.path.join(HERE, "pool_youtube.csv")

    existing = []                                    # resume: keep what is already listed, add new songs to it
    if os.path.exists(out_path):
        import csv
        with open(out_path, encoding="utf-8-sig") as f:
            existing = list(csv.DictReader(f))
    taken = set(pool_keys())                         # songs in any pool list
    taken |= {k for k in latest_rows()}              # songs already analysed (in results/index.csv)
    taken |= {f"youtube_{r['track_id']}" for r in existing}

    added, new_rows = {}, []
    done_q = load_done_queries()

    def save():
        """Write everything found so far (called after EVERY search, so a crash or a stop loses at most one search)."""
        if new_rows:
            write_list(out_path, existing + new_rows)        # merges, keeps your i_agree marks, saves a .bak

    def run_query(g, q, order, label):
        tag = f"{q}|{order}|{a.max_views}"
        if tag in done_q:
            print(f"  {g:11s} skipped  ({label}: {q!r} was already searched)")
            return
        got = (pick_ytdlp(g, q, a.per, a.max_views, taken, by_relevance=a.relevance) if a.ytdlp
               else pick_for_genre(g, q, a.per, a.max_views, a.pages, order, a.cc_only, taken))
        new_rows.extend(got)
        added[g] = added.get(g, 0) + len(got)
        save()
        done_q.add(tag)
        save_done_queries(done_q)
        print(f"  {g:11s} +{len(got):3d}  ({label}: {q!r})")

    failed = None
    try:
        if a.ytdlp:                                  # style searches with yt-dlp, round by round (no quota)
            qset = STYLE_SETS[a.style]
            for rnd in range(max(len(v) for v in qset.values())):
                for g, qs in qset.items():
                    if rnd < len(qs):
                        run_query(g, qs[rnd], "ytdlp", f"round {rnd + 1}, yt-dlp")
        elif a.variety:                              # extra searches inside the SAME genres, round by round
            for rnd in range(max(len(v) for v in EXTRA_QUERIES.values())):
                order = ("date", "relevance", "date")[rnd % 3]
                for g in genres:
                    qs = EXTRA_QUERIES.get(g, [])
                    if rnd < len(qs):
                        run_query(g, qs[rnd], order, f"round {rnd + 1}, {order}")
        else:
            for g, q in genres.items():
                run_query(g, q, a.order, "searched")
    except QuotaUsed:
        print("\n!! YouTube daily quota used up. Everything found so far is saved; run again after it resets "
              "(midnight Pacific time); finished searches are skipped.")
    except KeyError as e:
        raise SystemExit(f"unknown genre {e}; see: python build_youtube.py --list-genres")
    except Exception as e:                           # any other failure: keep what was found, then say so loudly
        failed = e
        print(f"\n!! stopped by an error ({type(e).__name__}: {str(e)[:200]}). Everything found so far is saved.")
    save()
    if not new_rows:
        print("Nothing new to add (quota, or every match is already in the pool).")
    else:
        total = len(existing) + len(new_rows)
        print(f"\npool_youtube.csv now has {total} songs (+{len(new_rows)} new). Next:\n"
              "  nohup python -u run_tests.py --list pool_youtube.csv > pool_youtube.log 2>&1 &")
    if failed is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
