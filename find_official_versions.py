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
UNRESOLVED = os.path.join(RES, "official_unresolved.csv")

FAN_LYRIC = re.compile(r"\blyrics?\b|lyric video|lyrical|visuali[sz]er|\bwith lyrics\b|vietsub|engsub|sub espa|\blirik\b|\bletra\b|"
                       r"가사|歌詞|歌词|動態|动态", re.I)
COVER = re.compile(r"\bcover(ed|s)?\b|covered by|\btribute\b|\bkaraoke\b|\binstrumental\b|piano version|acoustic version|reimagin|originally (performed|by)|"
                   r"\bremake\b|카버|カバー|翻唱", re.I)
OFFICIAL = re.compile(r"official", re.I)
LYRIC_CHANNEL = re.compile(r"lyrics?|lyric|letras|lirik|가사", re.I)
# a recording that is NOT the studio original (live, session, translation, dated fan recording): never proposed as the replacement
ALTERED = re.compile(r"\b(session|sessions|concert|tour|performance|fancam|traducci\w*|tradu[c\u00e7][a\u00e3]o|espa[n\u00f1]ol|subtitulad\w*|legendado|vietsub|engsub|"
                     r"live|unplugged|remix|sped|slowed|8d|nightcore|reaction)\b|\d{1,2}[./]\d{1,2}[./]\d{2,4}|\b\d{6}\b", re.I)
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
_NOISE = re.compile(r"\blyrics?( video)?\b|\bvisuali[sz]er\b|\bofficial\b|\bm/?v\b|\baudio\b|\bcover\b|\bfull\b|\bvietsub\b|\bengsub\b|\bmusic video\b|\bpinyin\b|\btranslation\b|\btranslated\b|\bromani[sz]ation\b|\beng(lish)? ?subs?\b|歌词版|歌詞版|歌词|歌詞|動態歌詞|动态歌词|/\s*english\b|//.*$|⚜.*$", re.I)


def clean_name(t):
    t = _BRACKETS.sub(" ", t or "")
    t = _NOISE.sub(" ", t)
    t = re.sub(r"(^|\s)#.*$", " ", t)                    # hashtags are nearly always at the end ("... #Esme Rose"): cut from the first one
    t = re.sub(r"[\u201c\u201d\"'`\u2018\u2019\U0001F300-\U0001FAFF\u2600-\u27BF]+", " ", t)
    parts = [re.sub(r"\s+", " ", x).strip(" -\u2013\u2014|:.") for x in t.split("|")]
    parts = [x for x in parts if x]
    if len(parts) > 1:                                   # "Vietsub | Song - Artist | Lyrics Video": keep the part that looks like "A - B"
        parts = [next((x for x in parts if re.search(r"\s[-\u2013\u2014]\s", x)), parts[0])]
    return parts[0] if parts else ""


_TAIL = re.compile(r"(vevo|official|topic|records|music)+$")


def _sq(s):
    """A name squashed for comparing: no spaces or punctuation, and no trailing 'VEVO' / 'Official' / 'Topic' / 'Records' / 'Music'."""
    from tag_ai import norm_name
    return _TAIL.sub("", norm_name(s).replace(" ", ""))


def channel_matches(channel, *names):
    """True when the channel's name is (part of) one of the names or the other way round: 'JastinMartinVEVO' ~ 'Jastin Martin', 'Aioz - Topic' ~ 'Aioz'."""
    c = _sq(channel)
    if len(c) < 3:
        return False
    return any(len(n) >= 3 and (n in c or c in n) for n in (_sq(x) for x in names))


def candidate_pairs(title, pool_artist, channel):
    """[(artist, song)] guesses for the original: 'Artist - Song' in the title, and the pool's artist field when it is not just the uploader's name."""
    t = clean_name(title)
    pairs = []
    m = re.match(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$", t)
    if m:
        pairs.append((m.group(1).strip(), m.group(2).strip()))
    if not pairs:
        mb = re.match(r"^\s*(.+?)\s+by\s+(.+?)\s*$", t, re.I)                 # "Song by Artist"
        if mb:
            pairs.append((mb.group(2).strip(" .*"), mb.group(1).strip(" *")))
    pa = (pool_artist or "").strip()
    if not pairs and t and pa and pa.lower() != (channel or "").strip().lower() and not CHANNELLIKE.search(pa):   # the title's own "A - B" beats the pool's artist field
        pairs.append((pa, t))
    seen, out = set(), []
    for a, s in pairs:
        if a and s and (a.lower(), s.lower()) not in seen:
            seen.add((a.lower(), s.lower())); out.append((a, s))
    return out


def is_candidate(title, channel="", pool_artist=""):
    """kind_of(), except that a visualizer / lyric video on the ARTIST'S OWN channel is the original and is never a candidate (covers keep their kind)."""
    kind = kind_of(title, channel)
    if kind == "fan lyric video" and not LYRIC_CHANNEL.search(channel or ""):
        names = [x for pr in candidate_pairs(title, pool_artist, channel) for x in pr]
        if names and channel_matches(channel, *names):
            return None
    return kind


def load_channels(res=RES):
    p = os.path.join(res, "ai_tags.csv")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8-sig") as f:
        return {r["key"]: r.get("channel") or "" for r in csv.DictReader(f)}


def scan(here=HERE, res=RES, rows=None, stats=None):
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
        kind = is_candidate(r.get("title"), channel, r.get("artist"))
        if stats is not None and kind is None and kind_of(r.get("title"), channel) == "fan lyric video":
            stats["own_channel"] = stats.get("own_channel", 0) + 1     # an artist's own visualizer / lyric video: it IS the original
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


GENERIC = {"official", "mv", "music", "video", "audio", "lyrics", "lyric", "live", "feat", "ft", "the", "a", "and"}


def length_ok(old, new, official):
    """Fan videos are often cut or padded, so a match from the artist's own channel may differ a lot (0.5x to 2x); any other match only a little."""
    if not old or not new:
        return True
    if official:
        return 0.5 <= new / old <= 2.0
    return abs(new - old) <= max(15.0, 0.12 * old)


def why_rejected(e, song, artist, dur):
    """None when search result e really is this song by this artist, else the reason it is not (so --explain can show it)."""
    import build_from_spotify as bs
    from build_youtube import NOT_A_SONG
    title, ch = e.get("title") or "", e.get("channel") or e.get("uploader") or ""
    if NOT_A_SONG.search(title) or e.get("is_live"):
        return "not a song / live stream"
    k = kind_of(title, ch)
    if k:
        return f"it is itself a {k}"
    if ALTERED.search(title) and not ALTERED.search(song):
        return "live / session / translation / dated recording"
    ct, cc = bs.norm(title), bs.norm(ch)
    t, first = bs.norm(bs.clean_title(song)), bs.norm(artist.split(",")[0])
    if not t or not first:
        return "no song or artist to compare"
    if sum(w in ct for w in t) < max(1, int(0.8 * len(t) + 0.5)):
        return "title does not match the song"
    if sum(w in (ct + cc) for w in first) < max(1, int(0.7 * len(first) + 0.5)):
        return "artist is not in the channel or title"
    d = e.get("duration") or 0
    if not 60 <= d <= 600:
        return f"length {int(d)} s is outside 60-600 s"
    official = channel_matches(ch, artist, song) or bs.official_rank(e, artist)[0]
    if dur and not length_ok(dur, d, official):
        return f"length {int(d)} s against the old {int(dur)} s"
    return None


def fallback_by_channel(c, search, dur, explain=None):
    """A title with no artist in it ('謝安琪 Kay Tse 囍帖街 ...'): search the cleaned title and accept only a video from a channel whose NAME is in the
    old title (so the artist's own channel), sharing song words with it. Never pre-approved."""
    import build_from_spotify as bs
    q = clean_name(c["title"])[:60].strip()
    if len(bs.norm(q)) < 2:
        return None
    old_tokens, old_id = set(bs.norm(c["title"])), c["key"].split("_", 1)[1]
    good = []
    for e in search(q, 8):
        ch, t, d = e.get("channel") or e.get("uploader") or "", e.get("title") or "", e.get("duration") or 0
        shared = (set(bs.norm(t)) & old_tokens) - set(bs.norm(ch)) - GENERIC
        if e.get("id") == old_id:
            why = "the old video itself"
        elif kind_of(t, ch):
            why = f"it is itself a {kind_of(t, ch)}"
        elif ALTERED.search(t) and not ALTERED.search(c["title"]):
            why = "live / session / translation / dated recording"
        elif not channel_matches(ch, c["title"]):
            why = "the channel name is not in the old title"
        elif not shared:
            why = "no song words in common"
        elif not 60 <= d <= 600:
            why = f"length {int(d)} s is outside 60-600 s"
        elif dur and not length_ok(dur, d, True):
            why = f"length {int(d)} s against the old {int(dur)} s"
        else:
            why = None
        if explain is not None:
            explain.append((q, e, why))
        if why is None:
            good.append(e)
    if not good:
        return None
    best = max(good, key=lambda e: e.get("view_count") or 0)
    return dict(artist=best.get("channel") or best.get("uploader") or "", song=q, entry=best, official=True, fallback=True,
                note="no artist in the title: matched because the channel's name is in the old title; check it")


def find_official(c, search, deezer=None, explain=None):
    """Best replacement for candidate c, or None. search(query, n) -> list of yt-dlp style entries (id, title, channel, duration, view_count).
    explain (a list) collects (query, result, reason it was rejected or None) for every result looked at."""
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
            why = "the old video itself" if e.get("id") == old_id else why_rejected(e, song, artist, dur)
            if explain is not None:
                explain.append((f"{artist} / {song}", e, why))
            if why is None:
                cands.append(e)
        if cands:
            # "Song - Artist" titles are common: the uploader may be named after either part, so the artist's own channel is recognised under both readings
            def rank(e):
                ch = e.get("channel") or e.get("uploader") or ""
                return (bool(channel_matches(ch, artist, song) or bs.official_rank(e, artist)[0]), e.get("view_count") or 0)
            cands.sort(key=rank, reverse=True)
            best = cands[0]
            if not channel_matches(best.get("channel") or best.get("uploader") or "", artist) and rank(best)[0]:
                note = (note + "; " if note else "") + "title looked like 'Song - Artist': check the artist"
            return dict(artist=artist, song=song, entry=best, official=rank(best)[0], fallback=False, note=note)
    if not pairs:
        return fallback_by_channel(c, search, dur, explain)
    return None


def write_unresolved(path, cands, found):
    """The candidates that got no proposal, with the artist / song guesses that were searched, so the rules can be judged."""
    done = {c["key"] for c, _ in found}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["kind", "key", "title", "channel", "old_seconds", "guesses searched", "link"])
        for c in cands:
            if c["key"] not in done:
                guesses = "; ".join(f"{a} / {s}" for a, s in candidate_pairs(c["title"], c["pool_artist"], c["channel"])) or "(no artist guess)"
                w.writerow([c["kind"], c["key"], c["title"], c["channel"], c["duration"], guesses, c["link"]])


def write_proposals(path, cands, found):
    cols = ["approve", "kind", "old_key", "old_title", "old_channel", "old_views", "old_link", "artist", "song",
            "new_link", "new_title", "new_channel", "new_views", "new_seconds", "old_seconds", "official_channel", "note"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cols)
        for c, g in found:
            e = g["entry"]
            pre = "y" if (g["official"] and c["kind"] == "fan lyric video" and not g.get("fallback")) else ""
            w.writerow([pre, c["kind"], c["key"], c["title"], c["channel"], c["views"], c["link"], g["artist"], g["song"],
                        f"https://www.youtube.com/watch?v={e['id']}", e.get("title"), e.get("channel") or e.get("uploader"),
                        e.get("view_count") or "", int(e.get("duration") or 0), c["duration"], "yes" if g["official"] else "no", g["note"]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true", help="look for the official version of every candidate on YouTube")
    ap.add_argument("--limit", type=int, default=0, help="only the first N candidates (a first small batch)")
    ap.add_argument("--explain", type=int, default=0, metavar="N", help="after the search, show why every search result was rejected for the first N unresolved songs")
    ap.add_argument("--deezer", action="store_true", help="for covers with no artist in the title, ask Deezer who the original artist is")
    a = ap.parse_args()
    stats = {}
    cands = scan(stats=stats)
    by = collections.Counter(c["kind"] for c in cands)
    print(f"{len(cands)} suspected covers / fan lyric videos in the pool: " + ", ".join(f"{k} {v}" for k, v in by.items()))
    print(f"({stats.get('own_channel', 0)} visualizers / lyric videos were skipped because they are on the artist's own channel: they are the original)")
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
    found, none, lost = [], 0, []
    for i, c in enumerate(todo, 1):
        g = find_official(c, search, deezer_original if a.deezer else None)
        if g:
            found.append((c, g))
        else:
            none += 1; lost.append(c)
        if i % 25 == 0:
            print(f"  {i} / {len(todo)} searched, {len(found)} proposals", flush=True)
    write_proposals(PROPOSALS, todo, found)
    write_unresolved(UNRESOLVED, todo, found)
    off = sum(1 for _, g in found if g["official"])
    print(f"\n{len(found)} proposals ({off} from the artist's own or a Topic channel, {len(found) - off} from other channels); {none} with no verified original.")
    print(f"The {none} without a verified original are listed in {UNRESOLVED} with the guesses searched.")
    top = collections.Counter(c["channel"] for c in lost if c["channel"]).most_common(10)
    if top and top[0][1] > 1:
        print("channels with the most unresolved songs (often AI-made originals with no official video: candidates for ai_block.txt):\n  "
              + "\n  ".join(f"{n:3d}  {ch}" for ch, n in top if n > 1))
    for c in lost[:a.explain]:
        log = []
        find_official(c, search, deezer_original if a.deezer else None, explain=log)
        print(f"\n-- {c['title'][:70]} | {c['channel'][:20]} | {c['duration']} s")
        for q, e, why in log:
            print(f"     [{q[:34]}] {str(e.get('title'))[:46]:46s} | {str(e.get('channel') or e.get('uploader'))[:16]:16s} | {int(e.get('duration') or 0)} s -> {why or 'ACCEPTED'}")
        if not log:
            print("     (no search was made: no artist or song could be read from the title)")
    print(f"Review {PROPOSALS}: put y in `approve` for rows you accept (rows from the artist's own channel are pre-approved for fan lyric videos), then\n"
          f"  python replace_songs.py --proposals results/official_proposals.csv")


if __name__ == "__main__":
    main()
