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
}

_last = [0.0]


def _polite(min_gap=0.2):
    gap = time.time() - _last[0]
    if gap < min_gap:
        time.sleep(min_gap - gap)
    _last[0] = time.time()


class QuotaUsed(Exception):
    pass


def _call(path, **params):
    _polite()
    try:
        r = requests.get(f"{API}/{path}", params={**params, "key": os.environ["YOUTUBE_API_KEY"]}, timeout=30)
        if r.status_code == 403 and "quota" in r.text.lower():
            raise QuotaUsed()
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


def main():
    ap = argparse.ArgumentParser(description="Add lower-view YouTube songs to the pool, by genre.")
    ap.add_argument("--per", type=int, default=40, help="songs to add per genre (default 40)")
    ap.add_argument("--max-views", type=int, default=100_000, help="skip videos above this many views (default 100k)")
    ap.add_argument("--pages", type=int, default=2, help="pages of 50 results per genre search (default 2; each costs ~100 quota)")
    ap.add_argument("--order", default="date", choices=["date", "relevance", "rating", "title"],
                    help="search order (default 'date': recent uploads tend to have fewer views)")
    ap.add_argument("--genres", nargs="*", help="genre keys to build (default: all)")
    ap.add_argument("--cc-only", action="store_true", help="keep only Creative-Commons-licensed videos")
    ap.add_argument("--list-genres", action="store_true", help="print the genre searches and exit")
    a = ap.parse_args()

    if a.list_genres:
        for g, q in DEFAULT_GENRES.items():
            print(f"  {g:10s} -> {q}")
        return
    if not os.environ.get("YOUTUBE_API_KEY"):
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
    try:
        for g, q in genres.items():
            got = pick_for_genre(g, q, a.per, a.max_views, a.pages, a.order, a.cc_only, taken)
            new_rows += got
            added[g] = len(got)
            print(f"  {g:10s} +{len(got):3d}  (searched: {q!r})")
    except QuotaUsed:
        print("\n!! YouTube daily quota used up. Saving what was found; run again tomorrow to add more.")
    except KeyError as e:
        raise SystemExit(f"unknown genre {e}; see: python build_youtube.py --list-genres")

    if not new_rows:
        print("Nothing new to add (quota, or every match is already in the pool).")
        return
    write_list(out_path, existing + new_rows)        # merges, keeps your i_agree marks, saves a .bak
    total = len(existing) + len(new_rows)
    print(f"\npool_youtube.csv now has {total} songs (+{len(new_rows)} new). Next:\n"
          "  nohup python -u run_tests.py --list pool_youtube.csv > pool_youtube.log 2>&1 &")


if __name__ == "__main__":
    main()
