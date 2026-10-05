"""Add songs from the Free Music Archive (FMA) research dataset to the pool, the same number per focus genre.

Why the dataset and not the FMA website: FMA shut its API down and its terms forbid scraping the site. The
research dataset (github.com/mdeff/fma, EPFL) is the sanctioned route: 106,574 full-length Creative Commons
tracks from FMA, with metadata (CC BY 4.0) and each track under the licence its artist chose.

We never download the whole 879 GB archive. Each song is read out of the remote zip on its own (an HTTP
'range' read), analysed in a temporary folder and deleted, exactly like Jamendo and Audius songs.

  pip install remotezip                     # once (reads single songs out of the remote zip)
  python fma_pool.py --setup                # once: metadata only (342 MB download, ~20 MB kept)
  python fma_pool.py --check                # can we read single songs from the archive? (reads 1 song)
  python fma_pool.py --survey               # how many usable songs each focus genre has
  python fma_pool.py --per-genre 50         # adds 50 per focus genre to pool_fma.csv (run again = 50 more each)
  python fma_pool.py --sung 50              # aims for +50 SUNG songs per genre: adds more where singing is rarer
                                            # (rates measured on the FMA songs analysed so far); skips electronic
  python -u run_tests.py --list pool_fma.csv

Rules: Creative Commons licences only (licence and artist kept for credits); 90 s to 10 min long; no track
from the "Instrumental" genre (we want singing); at most 2 songs per artist across pool_fma.csv; songs
already in pool_fma.csv are never picked twice. Each song is counted under ONE focus genre, rarest first,
so a "Soul-RnB + Pop" song counts for R&B.
"""
import argparse, ast, csv, io, os, random, sys, zipfile
import numpy as np
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
FMA_DIR = os.path.join(HERE, "fma")
META_URL = "https://os.unil.cloud.switch.ch/fma/fma_metadata.zip"
FULL_URL = "https://os.unil.cloud.switch.ch/fma/fma_full.zip"
OUT = os.path.join(HERE, "pool_fma.csv")
COLS = ["group", "source", "track_id", "jamendo_id", "title", "artist", "album", "duration", "listens", "licence",
        "listen", "fma_genres", "i_agree"]

# focus genre -> words that must appear in one of the track's FMA genre names (lower case). Rarest first:
# a song is counted for the first focus genre it matches.
FOCUS = [
    ("rnb", ("soul-rnb", "rnb", "r&b", "soul")),
    ("singer-songwriter", ("singer-songwriter",)),
    # FMA has no plain "Alternative" genre; these rock styles are what's usually called alternative.
    # "Alternative Hip-Hop" is left to hip-hop (see NOT).
    ("alternative", ("alternative", "post-punk", "shoegaze", "noise-rock", "grunge", "no wave")),
    ("indie", ("indie",)),
    ("pop", ("pop",)),
    ("hiphop", ("hip-hop", "rap")),
    ("rock", ("rock",)),
    ("electronic", ("electronic",)),
]
NOT = {"alternative": ("hip-hop",), "rock": ("post-rock",)}   # names that look like a match but aren't one
MAX_PER_ARTIST = 2


def setup():
    import requests
    os.makedirs(FMA_DIR, exist_ok=True)
    tmp = os.path.join(FMA_DIR, "fma_metadata.zip.part")
    print(f"downloading {META_URL} (342 MB, metadata only, no audio) ...")
    with requests.get(META_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0); got = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk); got += len(chunk)
                if total and got % (50 << 20) < (1 << 20):
                    print(f"  {got >> 20} / {total >> 20} MB")
    with zipfile.ZipFile(tmp) as z:
        for name in ("tracks.csv", "genres.csv"):
            member = next(m for m in z.namelist() if m.endswith("/" + name) or m == name)
            with z.open(member) as src, open(os.path.join(FMA_DIR, name), "wb") as dst:
                dst.write(src.read())
        # song page links (for credits) come from raw_tracks.csv; only id -> link is kept
        member = next((m for m in z.namelist() if m.endswith("raw_tracks.csv")), None)
        if member:
            csv.field_size_limit(10 ** 8)
            with z.open(member) as src, open(os.path.join(FMA_DIR, "links.csv"), "w", newline="", encoding="utf-8") as dst:
                rd = csv.DictReader(io.TextIOWrapper(src, encoding="utf-8"))
                w = csv.writer(dst); w.writerow(["track_id", "url"])
                for r in rd:
                    w.writerow([r.get("track_id"), r.get("track_url") or ""])
    os.remove(tmp)
    print(f"ok: {FMA_DIR}/tracks.csv and genres.csv (the zip was deleted)")


def load():
    """Rows of tracks.csv as dicts with 'section.field' keys (the file has a 3-line header)."""
    p = os.path.join(FMA_DIR, "tracks.csv")
    if not os.path.exists(p):
        sys.exit("no fma/tracks.csv yet: run python fma_pool.py --setup")
    with open(os.path.join(FMA_DIR, "genres.csv"), encoding="utf-8") as f:
        gname = {r["genre_id"]: r["title"] for r in csv.DictReader(f)}
    csv.field_size_limit(10 ** 8)
    links = {}
    lp = os.path.join(FMA_DIR, "links.csv")
    if os.path.exists(lp):
        with open(lp, encoding="utf-8") as f:
            links = {r["track_id"]: r["url"] for r in csv.DictReader(f)}
    with open(p, encoding="utf-8", newline="") as f:
        rd = csv.reader(f)
        top, sub, _ = next(rd), next(rd), next(rd)
        cols, last = [], ""
        for t, s in zip(top, sub):
            last = t or last
            cols.append(f"{last}.{s}" if s else "track_id")
        out = []
        for row in rd:
            d = dict(zip(cols, row))
            try:
                ids = ast.literal_eval(d.get("track.genres_all") or "[]")
            except (ValueError, SyntaxError):
                ids = []
            d["_genres"] = [gname.get(str(i), "") for i in ids]
            d["_url"] = links.get(d.get("track_id", ""), "")
            out.append(d)
    return out


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def focus_of(d):
    names = [g.lower() for g in d["_genres"]] + [(d.get("track.genre_top") or "").lower()]
    for fg, words in FOCUS:
        if any(w in n and not any(x in n for x in NOT.get(fg, ())) for n in names for w in words):
            return fg
    return None


def usable(d):
    lic = (d.get("track.license") or "").lower()
    dur = num(d.get("track.duration")) or 0
    if not ("creative commons" in lic or "attribution" in lic or "cc0" in lic or "public domain" in lic):
        return False, "licence"
    if not 90 <= dur <= 600:
        return False, "length"
    if any(g.lower() == "instrumental" for g in d["_genres"]) or (d.get("track.genre_top") or "") == "Instrumental":
        return False, "instrumental"
    return True, ""


def survey(rows):
    c, why = Counter(), Counter()
    for d in rows:
        fg = focus_of(d)
        if not fg:
            continue
        ok, reason = usable(d)
        if ok:
            c[fg] += 1
        else:
            why[reason] += 1
    print("usable FMA songs per focus genre (Creative Commons, 90 s - 10 min, not 'Instrumental'):")
    for fg, _ in FOCUS:
        print(f"  {fg:18s} {c[fg]:6d}")
    print(f"left out: {dict(why)}")


def member_name(tid):
    t = int(tid)
    return f"fma_full/{t // 1000:03d}/{t:06d}.mp3"


def check():
    try:
        from remotezip import RemoteZip
    except ImportError:
        sys.exit("run: pip install remotezip")
    print(f"opening {FULL_URL} (reads only the archive's table of contents) ...")
    with RemoteZip(FULL_URL, timeout=(15, 60)) as z:
        names = z.namelist()
        mp3 = [n for n in names if n.endswith(".mp3")]
        print(f"  ok: {len(mp3)} songs listed")
        info = z.getinfo(mp3[0])
        data = z.read(mp3[0])
        print(f"  read one song on its own: {mp3[0]}, {len(data) / 1e6:.1f} MB (nothing kept)")
        if member_name(int(os.path.basename(mp3[0])[:-4])) != mp3[0]:
            print(f"  !! unexpected folder layout ({mp3[0]}); tell Claude")


def sung_rates():
    """Share of already-analysed pool_fma songs with singing, per focus genre (None if fewer than 10 analysed)."""
    try:
        import pool_mix
        db_rows, sung, *_ = pool_mix.singing()
    except Exception as e:
        print(f"  (couldn't read singing scores from the database: {str(e)[:100]}; using 60% for every genre)")
        return {}
    got, tot = Counter(), Counter()
    for r, s in zip(db_rows, sung):
        g = r[1]
        if g.startswith("pool_fma_"):
            fg = g[len("pool_fma_"):]
            tot[fg] += 1; got[fg] += bool(s)
    return {fg: got[fg] / tot[fg] for fg in tot if tot[fg] >= 10}


def plan_sung(target, skip):
    rates = sung_rates()
    plan = {}
    print(f"aiming for +{target} songs WITH SINGING per focus genre (skipping: {', '.join(skip) or 'none'}):")
    for fg, _ in FOCUS:
        if fg in skip:
            continue
        rate = rates.get(fg, 0.6)
        n = min(3 * target, int(np.ceil(target / max(rate, 0.25))))
        plan[fg] = n
        how = "sung so far" if fg in rates else "(a guess: under 10 analysed yet)"
        print(f"  {fg:18s} {100 * rate:3.0f}% {how} -> add {n}")
    return plan


def build(rows, per_genre, seed):
    """per_genre: one number for every focus genre, or a dict genre -> number (genres left out get none)."""
    from results_index import write_list
    have = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig") as f:
            have = list(csv.DictReader(f))
    taken = {r["track_id"] for r in have}
    per_artist = Counter(r["artist"] for r in have)
    rng = random.Random(seed)
    by = {fg: [] for fg, _ in FOCUS}
    for d in rows:
        fg = focus_of(d)
        if fg and usable(d)[0] and d["track_id"] not in taken:
            by[fg].append(d)
    new = []
    plan = per_genre if isinstance(per_genre, dict) else {fg: per_genre for fg, _ in FOCUS}
    print("adding songs per focus genre:")
    for fg, _ in FOCUS:
        if fg not in plan:
            continue
        want = plan[fg]
        cand = by[fg]; rng.shuffle(cand)
        got = 0
        for d in cand:
            a = d.get("artist.name") or ""
            if got >= want:
                break
            if per_artist[a] >= MAX_PER_ARTIST:
                continue
            per_artist[a] += 1; got += 1; taken.add(d["track_id"])
            new.append(dict(group=f"pool_fma_{fg}", source="fma", track_id=d["track_id"], jamendo_id="",
                            title=d.get("track.title", ""), artist=a, album=d.get("album.title", ""),
                            duration=d.get("track.duration", ""), listens=d.get("track.listens", ""),
                            licence=d.get("track.license", ""),
                            listen=d["_url"],
                            fma_genres="; ".join(g for g in d["_genres"] if g), i_agree=""))
        total = sum(r["group"] == f"pool_fma_{fg}" for r in have) + got
        print(f"  {fg:18s} +{got:3d}  (now {total}; {len(cand)} were available)" +
              ("   <- ran out" if got < want else ""))
    if not new:
        print("\nnothing new to add"); return
    write_list(OUT, have + new)
    print(f"\n{len(new)} songs added to pool_fma.csv ({len(have) + len(new)} in total). Next:\n"
          "  python -u run_tests.py --list pool_fma.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--survey", action="store_true")
    ap.add_argument("--per-genre", type=int, default=0)
    ap.add_argument("--sung", type=int, default=0,
                    help="aim for this many more songs WITH SINGING per genre (adds more where singing is rarer)")
    ap.add_argument("--skip", default="electronic", help="with --sung: genres to leave out, comma-separated "
                    "(default: electronic, which is mostly instrumental; use --skip '' for none)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.setup:
        return setup()
    if a.check:
        return check()
    rows = load()
    if a.survey:
        return survey(rows)
    if a.sung:
        return build(rows, plan_sung(a.sung, [s.strip() for s in a.skip.split(",") if s.strip()]), a.seed)
    if a.per_genre:
        return build(rows, a.per_genre, a.seed)
    ap.print_help()


if __name__ == "__main__":
    main()
