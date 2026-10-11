"""Find new artists for the pool through Deezer (public API, no key): start from artists the friends and you like, walk Deezer's
"related artists" outward, keep the ones that pass the filters, and write a sources file for build_from_spotify.py.

  python deezer_discover.py --target 60 --out deezer_artists1.json          # dry run first: add --dry-run to only print the choice
  nohup bash boost_artists.sh deezer_artists1.json > boost_deezer1.log 2>&1 &     # adds their songs, analyses, audits, quality pass

How artists are chosen
  1. Seeds: the artists in friends_inputs.csv, the artists in spotify_artists*.json, and any --seed "Name" (repeatable).
  2. Candidates: each seed's related artists, then theirs (--depth 2 by default). An artist that several seeds / candidates point
     at ranks higher (that count is `votes`: a crude "people who like these also like that").
  3. Filters (all printable with --dry-run):
       fans    --min-fans 5000 .. --max-fans 1500000 (Deezer fans). Under the minimum: mostly uploaders, AI acts and demos; over the
               maximum: the artists the friends already know (the project is no longer hidden-gems-only, but this keeps it discovery).
       albums  at least --min-albums 2.
       genre   Deezer gives genres per album, not per artist: the majority genre of the artist's top tracks' albums, mapped to a pool genre
               (GENRE_MAP below). Genres the pool leaves out (metal, jazz, classical, latin ...) and unmapped ones are skipped.
               'Asian Music' is split by writing (Hangul = kpop, kana = jpop, Chinese characters = cpop); Latin-script ones are skipped.
       pool    artists already in a pool list are skipped (by name).
       quota   at most --quota genre=N per genre (defaults below), so one genre cannot take the whole run.
  4. Output: the sources file (artist, pool genre, their Deezer top tracks, `more` = own-channel songs wanted) and
     results/deezer_selected.csv (who, why, fans, votes) to read before you start the long run. Remove an artist by deleting its entry in
     the JSON, or add its name to deezer_skip.txt (one per line) and run again.

Everything fetched is cached in results/deezer_cache.json, so a rerun (or a changed filter) costs almost no requests.
"""
import argparse, csv, glob, json, os, re, time, unicodedata
import requests

from results_index import POOL_LISTS, HERE, RES, genre_of, OFF_POOL_GENRES

API = "https://api.deezer.com"
CACHE = os.path.join(RES, "deezer_cache.json")

# Deezer album genre name (lower case) -> pool genre. Anything not here is skipped (so metal, jazz, classical, latin, kids ... stay out).
GENRE_MAP = {"pop": "pop", "rock": "rock", "alternative": "alternative", "rap/hip hop": "hiphop", "r&b": "rnb", "electro": "electro",
             "folk": "indiefolk", "singer & songwriter": "singer", "indie pop/folk": "indiepop", "indie rock": "indierock"}
DEFAULT_QUOTA = {"pop": 12, "rnb": 12, "alternative": 12, "rock": 4, "indiepop": 8, "indierock": 8, "indiefolk": 8, "singer": 8,
                 "electro": 6, "hiphop": 6, "kpop": 4, "jpop": 4, "cpop": 4}


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w]+", " ", s.replace("_", " ")).split())


class Deezer:
    """Throttled, cached Deezer API client (the free API allows about 50 requests per 5 seconds)."""
    def __init__(self, cache_path=CACHE, gap=0.15):
        self.path, self.gap, self.last, self.dirty = cache_path, gap, 0.0, 0
        self.cache = {}
        if os.path.exists(cache_path):
            try:
                self.cache = json.load(open(cache_path, encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}

    def get(self, path, **params):
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        if key in self.cache:
            return self.cache[key]
        for attempt in range(5):
            wait = self.gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = requests.get(f"{API}{path}", params=params, timeout=20)
                data = r.json()
            except (requests.RequestException, ValueError):
                time.sleep(2 * (attempt + 1)); continue
            if isinstance(data, dict) and data.get("error"):
                if data["error"].get("code") == 4:          # quota: wait and retry
                    time.sleep(5 * (attempt + 1)); continue
                data = {}
            self.cache[key] = data
            self.dirty += 1
            if self.dirty >= 25:
                self.save()
            return data
        return {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False)
        os.replace(self.path + ".tmp", self.path)
        self.dirty = 0


def seed_names(extra):
    names = list(extra)
    p = os.path.join(HERE, "friends_inputs.csv")
    if os.path.exists(p):
        names += [r["artist"] for r in csv.DictReader(open(p, encoding="utf-8-sig")) if r.get("artist")]
    for fn in sorted(glob.glob(os.path.join(HERE, "spotify_artists*.json"))):
        try:
            names += [e["name"] for e in json.load(open(fn, encoding="utf-8")) if e.get("kind") == "artist" and e.get("name")]
        except (OSError, ValueError):
            pass
    seen, out = set(), []
    for n in names:
        if norm(n) and norm(n) not in seen:
            seen.add(norm(n)); out.append(n)
    return out


def pool_artist_names(here=HERE):
    out = set()
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                out |= {norm(r.get("artist")) for r in csv.DictReader(f) if r.get("artist")}
    out.discard("")
    return out


def resolve(dz, name):
    """Deezer artist for a name: the first search hit whose name matches, else None (a wrong guess would seed the crawl badly)."""
    for a in (dz.get("/search/artist", q=name, limit=5).get("data") or []):
        if norm(a.get("name")) == norm(name):
            return a
    return None


def crawl(dz, seeds, depth):
    """{artist id: dict(name, fans, albums, votes, depth)} of related artists around the seeds (seeds themselves excluded)."""
    cand, frontier, seed_ids = {}, [], set()
    for n in seeds:
        a = resolve(dz, n)
        if a:
            seed_ids.add(a["id"]); frontier.append(a["id"])
        else:
            print(f"  seed not found on Deezer (exact name): {n}")
    print(f"  {len(frontier)} of {len(seeds)} seeds found on Deezer")
    for d in range(1, depth + 1):
        nxt = []
        for aid in frontier:
            for r in (dz.get(f"/artist/{aid}/related", limit=25).get("data") or []):
                if r["id"] in seed_ids:
                    continue
                c = cand.get(r["id"])
                if c is None:
                    c = cand[r["id"]] = dict(id=r["id"], name=r.get("name") or "", fans=r.get("nb_fan"), albums=r.get("nb_album"),
                                             votes=0, depth=d)
                    nxt.append(r["id"])
                c["votes"] += 1
        print(f"  depth {d}: {len(cand)} candidates so far")
        frontier = nxt
    return cand


def asian_genre(text):
    if re.search(r"[가-힯]", text):
        return "kpop"
    if re.search(r"[぀-ヿ]", text):
        return "jpop"
    if re.search(r"[一-鿿]", text):
        return "cpop"
    return None


def genre_map_from(dz):
    """{Deezer genre id: pool genre or 'asian' or None} from the live /genre list."""
    out = {}
    for g in (dz.get("/genre").get("data") or []):
        n = (g.get("name") or "").lower()
        out[g["id"]] = "asian" if n.startswith("asian") else GENRE_MAP.get(n)
    return out


def artist_genre_and_tracks(dz, aid, name, gmap):
    """(pool genre or None, top tracks, release years of the albums of the top 5 tracks) from the artist's top tracks: the majority album genre, mapped."""
    top = (dz.get(f"/artist/{aid}/top", limit=10).get("data") or [])
    votes, years = {}, []
    for t in top[:5]:
        alb = (t.get("album") or {}).get("id")
        if not alb:
            continue
        info = dz.get(f"/album/{alb}")
        m = re.match(r"(\d{4})", str(info.get("release_date") or ""))
        if m:
            years.append(int(m.group(1)))
        for g in ((info.get("genres") or {}).get("data") or []):
            votes[g["id"]] = votes.get(g["id"], 0) + 1
    if not votes:
        return None, top, years
    pool = gmap.get(max(votes, key=votes.get))
    if pool == "asian":
        pool = asian_genre(" ".join([name] + [t.get("title") or "" for t in top]))
    return pool, top, years


def load_overrides(path):
    """{normalised artist name: pool genre} from a file of 'Artist Name = genre' lines (# starts a comment). Deezer files most indie / singer-songwriter artists
    under 'Alternative' or 'Pop', so this is how you put an artist into the style you want it counted in (indierock, singer, indiepop ...)."""
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.split("#", 1)[0].strip()
            name, eq, g = line.rpartition("=")
            if eq and name.strip() and g.strip():
                out[norm(name)] = g.strip().lower()
    return out


def choose(dz, cand, args, taken, skip, overrides=None):
    gmap = genre_map_from(dz)
    quota = dict(DEFAULT_QUOTA)
    for q in args.quota or []:
        g, _, n = q.partition("=")
        quota[g.strip()] = int(n)
    used, picked, why = {}, [], {"fans": 0, "albums": 0, "in pool / skipped": 0, "genre": 0, "quota": 0}
    ranked = sorted(cand.values(), key=lambda c: (-c["votes"], c["depth"], c["name"]))
    for c in ranked:
        if len(picked) >= args.target:
            break
        if c["fans"] is None or c["albums"] is None:                       # a related list without counts: ask once
            full = dz.get(f"/artist/{c['id']}")
            c["fans"], c["albums"] = full.get("nb_fan"), full.get("nb_album")
        if c["fans"] is None or not (args.min_fans <= c["fans"] <= args.max_fans):
            why["fans"] += 1; continue
        if (c["albums"] or 0) < args.min_albums:
            why["albums"] += 1; continue
        if norm(c["name"]) in taken or norm(c["name"]) in skip:
            why["in pool / skipped"] += 1; continue
        genre, top, years = artist_genre_and_tracks(dz, c["id"], c["name"], gmap)
        if overrides and norm(c["name"]) in overrides:
            genre = overrides[norm(c["name"])]                # your label wins over Deezer's (it still has to be a genre with a quota)
        if genre not in quota or genre in OFF_POOL_GENRES:
            why["genre"] += 1; continue
        since = getattr(args, "since", 0) or 0
        if since and years and max(years) < since:            # the pool is for younger listeners: no top track from an album of the last few years = a legacy act
            why["age"] = why.get("age", 0) + 1; continue
        if used.get(genre, 0) >= quota[genre]:
            why["quota"] += 1; continue
        if len(top) < 3:
            why["genre"] += 1; continue
        used[genre] = used.get(genre, 0) + 1
        taken.add(norm(c["name"]))
        picked.append(dict(c, genre=genre, top=top, years=(min(years), max(years)) if years else None))
    return picked, why, used


def to_source(c, more):
    tracks = [dict(title=t.get("title_short") or t.get("title"),
                   artists=c["name"], seconds=float(t.get("duration") or 0)) for t in c["top"]]
    return dict(kind="artist", id=str(c["id"]), name=c["name"], genre=c["genre"], more=more, tracks=tracks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "deezer_artists1.json"))
    ap.add_argument("--target", type=int, default=60, help="how many artists to pick (60 artists is about 2,000 songs, about 9 hours of analysis)")
    ap.add_argument("--seed", action="append", default=[], help="an extra seed artist name (repeatable)")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--min-fans", type=int, default=5000)
    ap.add_argument("--max-fans", type=int, default=1500000)
    ap.add_argument("--min-albums", type=int, default=2)
    ap.add_argument("--quota", action="append", help="genre=N, e.g. --quota rock=20 (repeatable); defaults in DEFAULT_QUOTA")
    ap.add_argument("--more", type=int, default=20, help="extra songs per artist from their own YouTube channel (plus their top 10)")
    ap.add_argument("--since", type=int, default=0, metavar="YEAR",
                    help="skip artists none of whose top songs is on an album released in YEAR or later (e.g. --since 2018): the pool is for younger listeners, so legacy acts are left out; 0 = off")
    ap.add_argument("--dry-run", action="store_true", help="print the choice, write nothing")
    a = ap.parse_args()
    dz = Deezer()
    seeds = seed_names(a.seed)
    print(f"{len(seeds)} seed artists")
    cand = crawl(dz, seeds, a.depth)
    skip = set()
    sp = os.path.join(HERE, "deezer_skip.txt")
    if os.path.exists(sp):
        skip = {norm(x) for x in open(sp, encoding="utf-8") if x.strip()}
    taken = pool_artist_names() | {norm(s) for s in seeds}
    overrides = load_overrides(os.path.join(HERE, "deezer_genres.txt"))
    bad = sorted({g for g in overrides.values() if g not in DEFAULT_QUOTA})
    if bad:
        print(f"!! deezer_genres.txt: unknown genre(s) {', '.join(bad)}; use one of {', '.join(DEFAULT_QUOTA)}")
    if overrides:
        print(f"{len(overrides)} artist(s) with your own genre in deezer_genres.txt")
    picked, why, used = choose(dz, cand, a, taken, skip, overrides)
    dz.save()
    print(f"\n{len(picked)} artists picked of {len(cand)} candidates; skipped because: " + ", ".join(f"{k} {v}" for k, v in why.items()))
    print("by genre: " + ", ".join(f"{g} {n}" for g, n in sorted(used.items(), key=lambda x: -x[1])))
    songs = int(len(picked) * (10 + a.more) * 0.8)
    print(f"about {songs} songs to add (80% find a verified YouTube copy), about {songs * 16 / 3600:.0f} hours of analysis at ~16 s a song")
    for c in picked:
        yrs = f"{c['years'][0]}-{c['years'][1]}" if c.get("years") else "?"
        print(f"  {c['name'][:30]:30s} {c['genre']:12s} fans {c['fans']:>9,}  votes {c['votes']:>2}  depth {c['depth']}  top albums {yrs}")
    if a.dry_run:
        print("(dry run: nothing written)"); return
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump([to_source(c, a.more) for c in picked], f, ensure_ascii=False, indent=1)
    sel = os.path.join(RES, "deezer_selected.csv")
    os.makedirs(RES, exist_ok=True)
    with open(sel, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["artist", "genre", "deezer_fans", "albums", "votes", "depth", "deezer_id", "top_album_years"])
        for c in picked:
            w.writerow([c["name"], c["genre"], c["fans"], c["albums"], c["votes"], c["depth"], c["id"], f"{c['years'][0]}-{c['years'][1]}" if c.get("years") else ""])
    print(f"\nwrote {a.out} and {sel}. Next: nohup bash boost_artists.sh {os.path.basename(a.out)} > boost_deezer.log 2>&1 &")


if __name__ == "__main__":
    main()
