"""Are pool songs on YouTube? (a free place to listen when a song isn't on Spotify or Apple Music)

  export YOUTUBE_API_KEY=...            # once, in ~/.bashrc (never in code or screenshots)
  python check_youtube.py               # checks up to 95 more songs (YouTube's free daily allowance), then a summary
  python check_youtube.py --summary     # summary only

Why only ~95 a day: the official YouTube Data API allows about 100 searches per day on a free key, and YouTube's
rules forbid scraping its website. So this checks a RANDOM SAMPLE of the pool, a little more each day, in a fixed
random order: after 3 days (~285 songs) the share is already reliable to about +-5 points.

A song counts as "found" only if a video's title contains the song title AND the artist's name is in the channel
or video title AND the length is within 10 s (YouTube uploads often add a short intro). "other version" = right
artist and title but a different length (live, edit, extended). Channels named "<artist> - Topic" are YouTube's
automatic channels for songs sent out by a music distributor.

YouTube's developer policies allow keeping data from the API for at most 30 days, so the video links saved here
are deleted after 30 days on the next run (the found / not found result for the study is kept as a statistic).

For the app itself no API is needed: a "Search on YouTube" link
(https://www.youtube.com/results?search_query=<artist>+<title>) always works and costs nothing.
"""
import argparse, csv, datetime as dt, difflib, os, random, re, sys, time
import requests
from check_platforms import norm, same_artist
from results_index import latest_rows, pool_keys, read_meta, RES

OUT = os.path.join(RES, "youtube_links.csv")
FIELDS = ["song_key", "source", "title", "artist", "listens", "checked", "youtube", "topic_channel", "video_id"]
API = "https://www.googleapis.com/youtube/v3"
PER_DAY = 95
KEEP_DAYS = 30


class QuotaUsed(Exception):
    pass


def _call(path, **params):
    r = requests.get(f"{API}/{path}", params={**params, "key": os.environ["YOUTUBE_API_KEY"]}, timeout=20)
    if r.status_code == 403 and "quota" in r.text.lower():
        raise QuotaUsed()
    r.raise_for_status()
    return r.json()


def seconds(iso):
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    return sum(int(x or 0) * f for x, f in zip(m.groups(), (3600, 60, 1))) if m else None


def check(title, artist, dur):
    items = _call("search", part="snippet", type="video", maxResults=5, q=f"{artist} {title}").get("items", [])
    ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
    if not ids:
        return "not found", "", ""
    det = {v["id"]: v for v in _call("videos", part="contentDetails,snippet", id=",".join(ids)).get("items", [])}
    best = ("not found", "", "")
    t_norm = norm(title)
    for vid in ids:
        v = det.get(vid)
        if not v:
            continue
        vt, ch = v["snippet"].get("title", ""), v["snippet"].get("channelTitle", "")
        topic = ch.endswith(" - Topic")
        artist_ok = same_artist(artist, ch.replace(" - Topic", "")) or norm(artist) in norm(vt)
        title_ok = bool(t_norm) and (t_norm in norm(vt) or difflib.SequenceMatcher(None, t_norm, norm(vt)).ratio() >= 0.85)
        if not (artist_ok and title_ok):
            continue
        vd = seconds(v["contentDetails"].get("duration"))
        if dur and vd and abs(dur - vd) <= 10:
            return "found", "y" if topic else "n", vid
        best = ("other version", "y" if topic else "n", vid)
    return best


def load():
    if not os.path.exists(OUT):
        return []
    with open(OUT, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows):
    with open(OUT + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    os.replace(OUT + ".tmp", OUT)


def purge(rows):
    """Video links older than 30 days are removed (YouTube's storage rule); the result itself stays."""
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    n = 0
    for r in rows:
        if r.get("video_id") and (r.get("checked") or "") < cut:
            r["video_id"] = ""; n += 1
    return n


def summary(rows):
    rows = [r for r in rows if r["youtube"] != "error"]
    if not rows:
        print("nothing checked yet"); return
    pct = lambda g, v: f"{100 * sum(r['youtube'] == v for r in g) / len(g):3.0f}%"
    print(f"\n{len(rows)} pool songs checked on YouTube (a random sample of the pool)")
    print(f"  found (same artist, title, length within 10 s): {pct(rows, 'found')}   other version: {pct(rows, 'other version')}")
    topic = [r for r in rows if r["youtube"] == "found"]
    if topic:
        print(f"  of those found, on an automatic '- Topic' channel (sent out by a distributor): "
              f"{100 * sum(r['topic_channel'] == 'y' for r in topic) / len(topic):.0f}%")
    print("  by source:")
    for s in sorted({r["source"] for r in rows}):
        g = [r for r in rows if r["source"] == s]
        print(f"    {s:8s} {len(g):4d} songs   found {pct(g, 'found')}")
    # together with Apple Music / Spotify
    plat = os.path.join(RES, "platform_links.csv")
    if os.path.exists(plat):
        with open(plat, encoding="utf-8") as f:
            P = {r["song_key"]: r for r in csv.DictReader(f)}
        both = [r for r in rows if r["song_key"] in P and P[r["song_key"]]["apple"] not in ("", "error")]
        if both:
            on_ap = lambda r: "found" in (P[r["song_key"]]["apple"], P[r["song_key"]].get("spotify", ""))
            yt = lambda r: r["youtube"] == "found"
            n = len(both)
            print(f"\n  of these {n} songs: Apple/Spotify {100 * sum(map(on_ap, both)) / n:.0f}%, "
                  f"YouTube {100 * sum(map(yt, both)) / n:.0f}%, at least one of the three "
                  f"{100 * sum(on_ap(r) or yt(r) for r in both) / n:.0f}%")
            only = [r for r in both if not on_ap(r)]
            if only:
                print(f"  of the songs NOT on Apple/Spotify, YouTube has {100 * sum(map(yt, only)) / len(only):.0f}%"
                      f"  ({len(only)} songs)  <- how much a YouTube link adds")
    n = len(rows)
    print(f"\n  (with {n} songs, a share is accurate to about +-{100 * 1.96 * (0.25 / n) ** 0.5:.0f} points)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=PER_DAY)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    rows = load()
    purged = purge(rows)
    if purged:
        save(rows); print(f"removed {purged} video links older than {KEEP_DAYS} days (YouTube's storage rule)")
    if a.summary:
        return summary(rows)
    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("set YOUTUBE_API_KEY first (see the top of this file)")
    done = {r["song_key"] for r in rows if r["youtube"] != "error"}
    idx = latest_rows(RES)
    order = sorted(k for k in pool_keys() if idx.get(k, {}).get("status") == "done")
    random.Random(11).shuffle(order)                     # same random order every day -> an unbiased sample
    todo = [k for k in order if k not in done][: a.limit]
    print(f"{len(done)} checked so far; checking {len(todo)} more (pool: {len(order)} songs)")
    rows = [r for r in rows if r["song_key"] not in set(todo)]
    n = 0
    try:
        for k in todo:
            m, r = read_meta(k, RES), idx.get(k, {})
            title, artist = m.get("title") or r.get("title") or "", m.get("artist") or r.get("artist") or ""
            dur = float(m.get("duration") or r.get("duration_listed") or 0) or None
            if not title or not artist:
                continue
            try:
                yt, topic, vid = check(title, artist, dur)
            except QuotaUsed:
                raise
            except Exception as e:
                yt, topic, vid = "error", "", ""; print(f"  {k}: {e}")
            rows.append(dict(song_key=k, source=k.split("_")[0], title=title, artist=artist,
                             listens=m.get("listens") or r.get("listens") or "", checked=dt.date.today().isoformat(),
                             youtube=yt, topic_channel=topic, video_id=vid))
            n += 1
            if n % 10 == 0:
                save(rows); print(f"  {n}/{len(todo)}")
            time.sleep(0.3)
    except QuotaUsed:
        print("YouTube's daily allowance is used up: run again tomorrow (it continues where it stopped)")
    save(rows)
    summary(rows)


if __name__ == "__main__":
    main()
