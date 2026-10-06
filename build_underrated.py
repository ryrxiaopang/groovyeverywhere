"""Find songs by artists the web calls underrated, and keep the ones whose songs listeners actually like.

Views alone only measure obscurity. This adds two things: EVIDENCE (the artist is named as underrated or overlooked on a
web list; underrated_artists.csv records the source for each) and a QUALITY signal that does not depend on reach:
the LIKE RATE (likes per view) of their songs, i.e. how much the people who did find the song enjoyed it.

  python build_underrated.py                     # search YouTube (yt-dlp, no API quota), write underrated_selected.csv
  python build_underrated.py --add               # ... and add the chosen songs to pool_youtube.csv
  python build_underrated.py --genres rnb hiphop --limit 5     # a quick trial

Per artist: search YouTube, keep results that are really by that artist (their channel, an "- Topic" channel, or their
name in the title), 90 to 480 s long, not a tutorial / playlist / cover (build_youtube.NOT_A_SONG). Reach = the
channel's follower count (kept: up to --max-followers) and each song's views (kept: up to --max-song-views).
Per genre the --top artists with the highest median like rate win; up to --songs songs each, best like rate first.
Everything fetched is cached in results/underrated_cache.json, so a stopped run resumes.
"""
import argparse, csv, json, os, re, statistics, sys, time, unicodedata
import numpy as np
import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_youtube import NOT_A_SONG
from results_index import RES, latest_rows, pool_keys, write_list

ARTISTS = os.path.join(HERE, "underrated_artists.csv")
SELECTED = os.path.join(HERE, "underrated_selected.csv")
CACHE = os.path.join(RES, "underrated_cache.json")
POOL = os.path.join(HERE, "pool_youtube.csv")
MIN_VIEWS = 500          # below this a like rate means nothing


def norm(s):
    """Lower case, no accents (Monae = Mon\u00e1e), no punctuation."""
    s = unicodedata.normalize("NFKD", (s or "").replace("\u00f8", "o").replace("\u00d8", "O")).encode("ascii", "ignore").decode() or (s or "")
    return re.sub(r"[^\w]+", " ", s.lower(), flags=re.UNICODE).strip()


def own_channel(channel, artist):
    """Is this the artist's own channel (or their automatic '- Topic' channel), not a label's?"""
    an, ch = norm(artist), norm(channel)
    return ch in (an, an + " topic") or (len(an) >= 5 and an in ch)


_PLAIN = {"topic", "official", "music", "records", "channel", "vevo", "label"}


def strict_by(channel, title, artist):
    """For common-word names: the channel is the artist's own (the name plus only non-Latin words such as a Korean
    spelling, or 'Topic'), or the title is 'Name - Song'. 'Ginger Root' is not 'Ginger'; a song called 'Seya' is
    not the artist seya."""
    ch = norm(channel)
    for name in [artist] + ALIASES.get(artist, []):          # aliases: spellings the user's artist is known by
        an = norm(name)
        if an and an in ch:
            rest = ch.replace(an, " ").split()
            if all(t in _PLAIN or not re.search(r"[a-z]", t) for t in rest):
                return True
    return re.match(r"^[\W_]*" + re.escape(artist) + r"\s*[-\u2013\u2014]\s", (title or "").strip(), re.I) is not None


ALIASES = {"Shi Shi": ["Shi Shi Sun", "\u5b6b\u76db\u5e0c", "\u5b59\u76db\u5e0c"]}   # Taiwanese-Korean R&B singer Sun Shengxi
STRICT = set()          # artists whose names are common words (the user's own list): match the channel or "Name - Title" only


def is_by(entry, artist):
    """Is this search result really by the artist? Short or common names need their own channel."""
    an = norm(artist)
    chan = norm(entry.get("channel") or entry.get("uploader") or "")
    title = norm(entry.get("title"))
    chan_ok = chan in (an, an + " topic") or (len(an) >= 5 and an in chan)
    if artist in STRICT:
        return strict_by(entry.get("channel") or entry.get("uploader"), entry.get("title"), artist)
    title_ok = (len(an) >= 5 and an in title) or title.startswith(an + " ")
    return chan_ok or title_ok


def ydl(flat):
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": flat,
                             "ignoreerrors": True, "socket_timeout": 30, "retries": 2, "noplaylist": True})


def fetch_artist(artist, hint, n_search, n_full, channel_url=""):
    """Candidate songs for one artist, each with views, likes, channel followers.
    channel_url (a YouTube channel link the user gave) bypasses the search and reads that channel's uploads."""
    out = []
    if channel_url:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True,
                               "ignoreerrors": True, "socket_timeout": 30, "playlist_items": "1:80"}) as y:
            res = y.extract_info(channel_url.rstrip("/") + "/videos", download=False) or {}
        flat = [e for e in (res.get("entries") or []) if e and e.get("id")]
        ok = [e for e in flat if 90 <= (e.get("duration") or 0) <= 480 and not NOT_A_SONG.search(e.get("title") or "")]
        ok.sort(key=lambda e: -(e.get("view_count") or 0))
        with ydl(False) as y:
            for e in ok[:n_full]:
                time.sleep(1.0)
                try:
                    d = y.extract_info(f"https://www.youtube.com/watch?v={e['id']}", download=False) or {}
                except Exception:
                    continue
                if d.get("id"):
                    out.append(dict(id=d["id"], title=d.get("title"), channel=d.get("channel") or d.get("uploader"),
                                    views=d.get("view_count"), likes=d.get("like_count"), followers=d.get("channel_follower_count"),
                                    duration=d.get("duration"), upload_date=d.get("upload_date")))
        return out
    with ydl("in_playlist") as y:
        res = y.extract_info(f"ytsearch{n_search}:{artist} {hint}", download=False) or {}
    def keep(res):
        flat = [e for e in (res.get("entries") or []) if e and e.get("id")]
        return [e for e in flat if is_by(e, artist) and 90 <= (e.get("duration") or 0) <= 480
                and not NOT_A_SONG.search(e.get("title") or "")]
    ok = keep(res)
    extra = ["official music video", "official audio", "lyrics", "MV"] if artist in STRICT else ["official music video"]
    for q in extra:
        if ok and artist not in STRICT:
            break
        with ydl("in_playlist") as y:
            more = keep(y.extract_info(f"ytsearch{n_search}:{artist} {q}", download=False) or {})
        have = {e["id"] for e in ok}
        ok += [e for e in more if e["id"] not in have]
    ok.sort(key=lambda e: -(e.get("view_count") or 0))
    with ydl(False) as y:
        for e in ok[:n_full]:
            time.sleep(1.0)
            try:
                d = y.extract_info(f"https://www.youtube.com/watch?v={e['id']}", download=False) or {}
            except Exception:
                continue
            if not d.get("id"):
                continue
            out.append(dict(id=d["id"], title=d.get("title"), channel=d.get("channel") or d.get("uploader"),
                            views=d.get("view_count"), likes=d.get("like_count"), followers=d.get("channel_follower_count"),
                            duration=d.get("duration"), upload_date=d.get("upload_date")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genres", nargs="*")
    ap.add_argument("--limit", type=int, default=0, help="artists per genre to look at (0 = all)")
    ap.add_argument("--top", type=int, default=10, help="artists kept per genre")
    ap.add_argument("--songs", type=int, default=3, help="songs kept per artist")
    ap.add_argument("--max-followers", type=int, default=1_000_000)
    ap.add_argument("--max-song-views", type=int, default=5_000_000)
    ap.add_argument("--add", action="store_true", help="add the chosen songs to pool_youtube.csv")
    a = ap.parse_args()

    with open(ARTISTS, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if not a.genres or r["genre"] in a.genres]
    if a.limit:
        seen = {}
        keep = []
        for r in rows:
            seen[r["genre"]] = seen.get(r["genre"], 0) + 1
            if seen[r["genre"]] <= a.limit:
                keep.append(r)
        rows = keep
    STRICT.update(r["artist"] for r in rows if r["source"].startswith("User playlist"))
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        key = f"{r['genre']}|{r['artist']}"
        if key in cache:
            continue
        try:
            cache[key] = fetch_artist(r["artist"], r.get("hint", ""), 15, 6 if not r.get("channel_url") else 10, r.get("channel_url") or "")
        except Exception as e:
            print(f"  !! {r['artist']}: {str(e)[:80]}"); continue
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {i:3d}/{len(rows)} {r['genre']:18s} {r['artist']:26s} {len(cache[key])} songs   ({time.time() - t0:.0f}s)", flush=True)

    # ---- score
    by_genre = {}
    for r in rows:
        songs = [s for s in cache.get(f"{r['genre']}|{r['artist']}", []) if s.get("views") and s["views"] >= MIN_VIEWS
                 and s["views"] <= a.max_song_views and s.get("likes")]
        songs = [s for s in songs if not NOT_A_SONG.search(s["title"] or "")]     # also for results fetched earlier
        if r["artist"] in STRICT and not r.get("channel_url"):
            songs = [s for s in songs if strict_by(s.get("channel"), s.get("title"), r["artist"])]
        # the same song uploaded as a video and as a visualiser counts once (best like rate wins)
        best = {}
        for s in songs:
            k = norm(re.sub(r"[\(\[].*?[\)\]]", " ", s["title"] or "")).replace(norm(r["artist"]), "").strip()
            if k not in best or s["likes"] / s["views"] > best[k]["likes"] / best[k]["views"]:
                best[k] = s
        songs = list(best.values())
        if len(songs) < 2:
            continue
        # reach = followers of the ARTIST'S OWN channel. A song hosted on a label's channel says nothing about the artist
        # (the same 3 to 5 million followers showed up for unrelated artists), so those are ignored.
        fol = [s["followers"] for s in songs if s.get("followers") and (r.get("channel_url") or own_channel(s.get("channel"), r["artist"]))]
        followers = max(fol) if fol else None
        if followers is not None and followers > a.max_followers:
            continue
        for s in songs:
            # likes per view, nudged toward a typical 2% so a handful of fans cannot win on a tiny sample
            # (equivalent to adding 500 views with 2% likes): 757 views with 5% likes counts as about 3.5%
            s["like_rate"] = (s["likes"] + 10) / (s["views"] + 500)
        by_genre.setdefault(r["genre"], []).append(dict(
            artist=r["artist"], source=r["source"], why=r["why"], followers=followers,
            median_like_rate=statistics.median(s["like_rate"] for s in songs),
            songs=sorted(songs, key=lambda s: -s["like_rate"])[:a.songs]))
    taken = set(pool_keys()) | set(latest_rows())
    chosen = []
    for g, arts in by_genre.items():
        arts.sort(key=lambda x: -x["median_like_rate"])
        for rank, art in enumerate(arts if g == "playlist" else arts[:a.top], 1):      # the user's own list is kept whole
            for s in art["songs"]:
                chosen.append(dict(genre=g, rank=rank, artist=art["artist"], followers=art["followers"] or "",
                                   median_like_pct=round(100 * art["median_like_rate"], 2), title=s["title"], views=s["views"],
                                   like_pct=round(100 * s["like_rate"], 2), seconds=s["duration"], id=s["id"],
                                   link=f"https://www.youtube.com/watch?v={s['id']}", evidence=art["source"],
                                   already=f"youtube_{s['id']}" in taken))
    with open(SELECTED, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(chosen[0].keys())); w.writeheader(); w.writerows(chosen)
    print(f"\n{len({(c['genre'], c['artist']) for c in chosen})} artists, {len(chosen)} songs -> {SELECTED}")
    for g, arts in by_genre.items():
        n_ok = min(len(arts), a.top)
        print(f"  {g:18s} {n_ok:2d} artists kept of {sum(1 for r in rows if r['genre'] == g)} listed "
              f"(the rest were too big, had fewer than 2 usable songs, or could not be matched)")
    if a.add:
        existing = list(csv.DictReader(open(POOL, encoding="utf-8-sig"))) if os.path.exists(POOL) else []
        have = {f"youtube_{r['track_id']}" for r in existing}
        new = []
        for c in chosen:
            if f"youtube_{c['id']}" in have or c["already"]:
                continue
            new.append(dict(source="youtube", track_id=c["id"], title=c["title"], artist=c["artist"], duration=c["seconds"],
                            listens=c["views"], licence="youtube-standard", listen=c["link"], site_genre=c["genre"],
                            group=f"yt_{c['genre']}", i_agree=""))
        if new:
            write_list(POOL, existing + new)
        print(f"added {len(new)} songs to pool_youtube.csv. Next: python -u run_tests.py --list pool_youtube.csv")


if __name__ == "__main__":
    main()
