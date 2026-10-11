"""Find covers and fan-made lyric videos in the pool and propose the original artist's own upload instead.

  python find_official_versions.py                    # 1. SCAN, offline: counts and examples -> results/cover_candidates.csv
  python find_official_versions.py --search           # 2. SEARCH YouTube for each one (yt-dlp, no API quota, resumable) -> results/official_proposals.csv
  python find_official_versions.py --search --limit 50 --deezer     # a first small batch; --deezer also asks Deezer who the original artist of a cover is
  (open results/official_proposals.csv, put  y  in the `approve` column of every row you accept, then)
  python replace_songs.py --proposals results/official_proposals.csv            # preview
  python replace_songs.py --proposals results/official_proposals.csv --apply    # make the changes, then analyse the new videos

What counts as a candidate (title and channel only, no audio):
  * fan lyric video : the title says lyrics / lyric video / visualiser / subtitles (or the channel name says Lyrics) and does NOT say "official"
  * cover           : the title says cover / covered by / tribute / karaoke / instrumental / piano version / originally by ...
An "Official Lyric Video" on the artist's own channel is kept: it is the original.

How the original is found: the artist and song name come from the title ("Artist - Song (Lyrics)") or, for songs added from Spotify, from the pool's own
artist field; for a cover with no artist in the title, --deezer asks Deezer. Then YouTube is searched for "artist song" and a result is accepted only
when the title matches the song, the artist's name is in the channel or title, the length is within a few seconds of the old one, and it is not itself
a cover / lyric video / remix / live version. An upload from the artist's own channel (or an "- Topic" channel) is marked official = yes and ranked
first; fan lyric videos with official = yes are pre-approved, everything else, and every cover, is left for you to decide.
Nothing in the pool changes until replace_songs.py --apply.
"""
import argparse, collections, csv, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES

CACHE = os.path.join(RES, "official_search_cache.json")
CANDIDATES = os.path.join(RES, "cover_candidates.csv")
PROPOSALS = os.path.join(RES, "official_proposals.csv")

FAN_LYRIC = re.compile(r"\blyrics?\b|lyric video|lyrical|visuali[sz]er|\bwith lyrics\b|vietsub|engsub|sub espa|\blirik\b|\bletra\b|"
                       r"가사|歌詞|歌词|動態|动态", re.I)
COVER = re.compile(r"\bcover(ed|s)?\b|covered by|\btribute\b|\bkaraoke\b|\binstrumental\b|piano version|acoustic version|reimagin|originally (performed|by)|"
                   r"\bremake\b|카버|カバー|翻唱", re.I)
OFFICIAL = re.compile(r"official", re.I)
LYRIC_CHANNEL = re.compile(r"lyrics?|lyric|letras|lirik|가사", re.I)
CHANNELLIKE = re.compile(r"\b(music|records?|radio|tv|lyrics?|vibes?|sounds?|studio|network|official|topic|channel|collective|nation)\b", re.I)


def kind_of(title, channel=""):
    """'cover', 'fan lyric video' or None."""
    t, c = title or "", channel or ""
    if COVER.search(t):
        return "cover"
    if (FAN_LYRIC.search(t) or LYRIC_CHANNEL.search(c)) and not OFFICIAL.search(t):
        return "fan lyric video"
    return None


_BRACKETS = re.compile(r"[\(\[\{【《「『（][^\)\]\}】》」』）]*[\)\]\}】》」』）]")
_NOISE = re.compile(r"\blyrics?( video)?\b|\bvisuali[sz]er\b|\bofficial\b|\bm/?v\b|\baudio\b|\bcover\b|\bfull\b|//.*$|⚜.*$", re.I)


def clean_name(t):
    t = _BRACKETS.sub(" ", t or "")
    t = _NOISE.sub(" ", t)
    t = re.sub(r"[“”\"'`‘’\U0001F300-\U0001FAFF☀-➿]+", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -–—|:.")


def candidate_pairs(title, pool_artist, channel):
    """[(artist, song)] guesses for the original: 'Artist - Song' in the title, and the pool's artist field when it is not just the uploader's name."""
    t = clean_name(title)
    pairs = []
    m = re.match(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$", t)
    if m:
        pairs.append((m.group(1).strip(), m.group(2).strip()))
    pa = (pool_artist or "").strip()
    if t and pa and pa.lower() != (channel or "").strip().lower() and not CHANNELLIKE.search(pa):
        pairs.append((pa, t))
    seen, out = set(), []
    for a, s in pairs:
        if a and s and (a.lower(), s.lower()) not in seen:
            seen.add((a.lower(), s.lower())); out.append((a, s))
    return out


def load_channels(res=RES):
    p = os.path.join(res, "ai_tags.csv")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8-sig") as f:
        return {r["key"]: r.get("channel") or "" for r in csv.DictReader(f)}


def scan(here=HERE, res=RES, rows=None):
    """Candidate dicts from the pool lists: key, kind, title, channel, pool artist, views, duration, link."""
    if rows is None:
        from pool_summary import read_pool
        rows = read_pool(here)
    ch = load_channels(res)
    out = []
    for r in rows:
        if r["site"] != "youtube":
            continue
        channel = ch.get(r["key"], "")
        kind = kind_of(r.get("title"), channel)
        if kind:
            vid = r["key"].split("_", 1)[1]
            out.append(dict(key=r["key"], kind=kind, title=r.get("title") or "", channel=channel, pool_artist=r.get("artist") or "",
                            views=r.get("listens") or "", duration=r.get("duration") or "", link=r.get("listen") or f"https://www.youtube.com/watch?v={vid}"))
    return out


def deezer_original(query, get=None):
    """(artist, song, seconds) of the best Deezer match for a cover's name, or None. A match must contain most of the query's words."""
    import requests
    get = get or (lambda q: requests.get("https://api.deezer.com/search", params={"q": q, "limit": 5}, timeout=15).json())
    try:
        data = get(query).get("data") or []
    except Exception:
        return None
    from build_from_spotify import norm
    qw = set(norm(query))
    for d in data:
        tw = set(norm(d.get("title_short") or d.get("title")))
        if tw and len(tw & qw) >= max(1, int(0.8 * len(tw) + 0.5)):
            return (d["artist"]["name"], d.get("title_short") or d.get("title"), float(d.get("duration") or 0))
    return None


def find_official(c, search, deezer=None):
    """Best replacement for candidate c, or None. search(query, n) -> list of yt-dlp style entries (id, title, channel, duration, view_count)."""
    import build_from_spotify as bs
    pairs = candidate_pairs(c["title"], c["pool_artist"], c["channel"])
    note = ""
    if not pairs and c["kind"] == "cover" and deezer:
        got = deezer(clean_name(c["title"]))
        if got:
            pairs, note = [(got[0], got[1])], "original artist from Deezer: check it"
    old_id = c["key"].split("_", 1)[1]
    try:
        dur = float(c["duration"] or 0)
    except ValueError:
        dur = 0.0
    for artist, song in pairs:
        cands = []
        for e in search(f"{artist} {bs.clean_title(song)}", 8):
            if e.get("id") == old_id or kind_of(e.get("title"), e.get("channel") or e.get("uploader")):
                continue                                              # not the old video, not another cover / fan lyric video
            if bs.verify(e, song, artist, dur):
                cands.append(e)
        if cands:
            cands.sort(key=lambda e: bs.official_rank(e, artist), reverse=True)
            best = cands[0]
            return dict(artist=artist, song=song, entry=best, official=bool(bs.official_rank(best, artist)[0]), note=note)
    return None


def write_proposals(path, cands, found):
    cols = ["approve", "kind", "old_key", "old_title", "old_channel", "old_views", "old_link", "artist", "song",
            "new_link", "new_title", "new_channel", "new_views", "new_seconds", "official_channel", "note"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cols)
        for c, g in found:
            e = g["entry"]
            pre = "y" if (g["official"] and c["kind"] == "fan lyric video") else ""
            w.writerow([pre, c["kind"], c["key"], c["title"], c["channel"], c["views"], c["link"], g["artist"], g["song"],
                        f"https://www.youtube.com/watch?v={e['id']}", e.get("title"), e.get("channel") or e.get("uploader"),
                        e.get("view_count") or "", int(e.get("duration") or 0), "yes" if g["official"] else "no", g["note"]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true", help="look for the official version of every candidate on YouTube")
    ap.add_argument("--limit", type=int, default=0, help="only the first N candidates (a first small batch)")
    ap.add_argument("--deezer", action="store_true", help="for covers with no artist in the title, ask Deezer who the original artist is")
    a = ap.parse_args()
    cands = scan()
    by = collections.Counter(c["kind"] for c in cands)
    print(f"{len(cands)} suspected covers / fan lyric videos in the pool: " + ", ".join(f"{k} {v}" for k, v in by.items()))
    os.makedirs(RES, exist_ok=True)
    with open(CANDIDATES, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["kind", "key", "title", "channel", "pool_artist", "views", "link"])
        for c in cands:
            w.writerow([c["kind"], c["key"], c["title"], c["channel"], c["pool_artist"], c["views"], c["link"]])
    for kind in by:
        print(f"\n  e.g. {kind}:")
        for c in [x for x in cands if x["kind"] == kind][:8]:
            print(f"     {c['title'][:58]:58s} | {c['channel'][:22]}")
    print(f"\nlist: {CANDIDATES}")
    if not a.search:
        print("(scan only. Next: python find_official_versions.py --search --limit 50)")
        return
    import yt_dlp
    from build_from_spotify import flat_search
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True})
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    def search(q, n):
        k = f"{n}|{q}"
        if k not in cache:
            time.sleep(0.6)
            cache[k] = [{x: e.get(x) for x in ("id", "title", "channel", "uploader", "duration", "view_count", "is_live")} for e in flat_search(ydl, q, n)]
            json.dump(cache, open(CACHE, "w", encoding="utf-8"))
        return cache[k]

    todo = cands[:a.limit] if a.limit else cands
    found, none = [], 0
    for i, c in enumerate(todo, 1):
        g = find_official(c, search, deezer_original if a.deezer else None)
        if g:
            found.append((c, g))
        else:
            none += 1
        if i % 25 == 0:
            print(f"  {i} / {len(todo)} searched, {len(found)} proposals", flush=True)
    write_proposals(PROPOSALS, todo, found)
    off = sum(1 for _, g in found if g["official"])
    print(f"\n{len(found)} proposals ({off} from the artist's own or a Topic channel, {len(found) - off} from other channels); {none} with no verified original.")
    print(f"Review {PROPOSALS}: put y in `approve` for rows you accept (rows from the artist's own channel are pre-approved for fan lyric videos), then\n"
          f"  python replace_songs.py --proposals results/official_proposals.csv")


if __name__ == "__main__":
    main()
