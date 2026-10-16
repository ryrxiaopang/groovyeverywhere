"""What is in the recommendation pool: songs by site, genre and language (and how many are AI-tagged / analysed).

  python pool_summary.py                 # the round-2 pool (YouTube only, HG_POOL_SOURCES), counted from the pool lists
  python pool_summary.py --all-sites     # every site, to see what round 2 leaves out

Counts come from the pool lists (pool_*.csv, minus i_agree = n, minus OFF_POOL_GENRES, like results_index.pool_keys()),
results/index.csv (analysed or not), results/pool_links.csv (working link) and results/ai_tags.csv. Nothing is downloaded.

Language is a best guess, in this order: (1) the search a song was found with (the group name: kpop, krnb, ... = Korean,
cpop, mrnb, ... = Mandarin, cantopop = Cantonese, jpop, jrnb, citypop = Japanese); (2) the writing in the title and artist
(Hangul, kana, Chinese characters); (3) otherwise "English / other Latin-script" (a romanised Korean title lands here).
Cantonese and Mandarin cannot be told apart from characters alone, so songs found by script only are "Chinese (not split)".
"""
import argparse, collections, csv, os, re

from results_index import POOL_LISTS, HERE, RES, OFF_POOL_GENRES, genre_of, list_key, latest_rows

GROUP_LANGUAGE = {
    "kpop": "Korean", "krnb": "Korean", "khiphop": "Korean", "kindie": "Korean", "kballad": "Korean", "klofi": "Korean",
    "cpop": "Mandarin", "mrnb": "Mandarin", "chiphop": "Mandarin", "twindie": "Mandarin",
    "cantopop": "Cantonese",
    "jpop": "Japanese", "jrnb": "Japanese", "citypop": "Japanese", "jindie": "Japanese", "jrock": "Japanese", "jhiphop": "Japanese",
    "mrock": "Mandarin",
}


def script_language(text):
    if re.search(r"[가-힯ᄀ-ᇿ]", text):
        return "Korean"
    if re.search(r"[぀-ヿ]", text):
        return "Japanese"
    if re.search(r"[一-鿿]", text):
        return "Chinese (not split)"
    return None


def language_of(row):
    g = (row.get("group") or "").lower()
    for p in ("yt_", "pool_vocal_", "pool_audius_", "pool_jamendo_", "pool_fma_", "pool_"):
        if g.startswith(p):
            g = g[len(p):]; break
    return (GROUP_LANGUAGE.get(g) or script_language(f"{row.get('title') or ''} {row.get('artist') or ''}")
            or "English / other Latin-script")


def read_pool(here=HERE):
    """One dict per pool song (a song in two lists counts once)."""
    out, seen = [], set()
    excluded = set()
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = list_key(r)
                if (r.get("i_agree") or "").strip().lower() in ("n", "no"):
                    excluded.add(k)
                if k in seen or genre_of(r.get("group")) in OFF_POOL_GENRES:
                    continue
                seen.add(k)
                out.append(dict(r, key=k, site=k.split("_")[0]))
    return [r for r in out if r["key"] not in excluded]


def summarise(rows, analysed=None, bad_link=None, ai=None):
    """rows from read_pool(); analysed / bad_link / ai are sets of keys (or None = unknown). Returns {table name: Counter}."""
    T = collections.defaultdict(collections.Counter)
    for r in rows:
        T["site"][r["site"]] += 1
        T["genre"][genre_of(r.get("group"))] += 1
        g = (r.get("group") or "?").lower()
        T["search / sub-style"][g[3:] if g.startswith("yt_") else g] += 1
        T["language"][language_of(r)] += 1
        if analysed is not None:
            T["analysed"]["yes" if r["key"] in analysed else "not yet"] += 1
        if bad_link is not None:
            T["link"]["no working link" if r["key"] in bad_link else "ok / unchecked"] += 1
        if ai is not None:
            T["AI tag"][ai.get(r["key"], "none")] += 1
    return T


def show(T, n):
    for name, c in T.items():
        print(f"\n{name}  ({n} songs)")
        for k, v in c.most_common(40):
            print(f"  {k:32s} {v:6d}  {100 * v / n:5.1f}%")


def cross(rows, printer=print):
    """Genre x language: songs per cell, plus how many different artists each genre has (a genre of 300 songs by 20 artists is thinner than it looks).
    Returns {genre: Counter(language)}."""
    langs = ["English / other Latin-script", "Mandarin", "Cantonese", "Korean", "Japanese", "Chinese (not split)"]
    short = {"English / other Latin-script": "Eng/Latin", "Chinese (not split)": "Chinese?"}
    T = collections.defaultdict(collections.Counter)
    artists = collections.defaultdict(set)
    for r in rows:
        g = genre_of(r.get("group"))
        T[g][language_of(r)] += 1
        artists[g].add((r.get("artist") or "").strip().lower())
    head = f"{'genre':16s}{'songs':>7s}{'artists':>8s}" + "".join(f"{short.get(l, l):>11s}" for l in langs)
    printer("\ngenre x language (songs), most songs first")
    printer(head)
    for g, c in sorted(T.items(), key=lambda x: -sum(x[1].values())):
        printer(f"{str(g)[:16]:16s}{sum(c.values()):7d}{len(artists[g]):8d}" + "".join(f"{c.get(l, 0):11d}" for l in langs))
    tot = collections.Counter()
    for c in T.values():
        tot.update(c)
    printer(f"{'ALL':16s}{sum(tot.values()):7d}{len(set().union(*artists.values())) if artists else 0:8d}" + "".join(f"{tot.get(l, 0):11d}" for l in langs))
    return T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-sites", action="store_true", help="count every site, not only HG_POOL_SOURCES (default youtube)")
    ap.add_argument("--cross", action="store_true", help="also print a genre x language table with the number of artists per genre (where to grow the pool)")
    a = ap.parse_args()
    import blind_test as bt                      # for POOL_SOURCES; importing it does not load the pool
    rows = read_pool()
    if not a.all_sites and "all" not in bt.POOL_SOURCES:
        rows = [r for r in rows if r["site"] in bt.POOL_SOURCES]
        print(f"sites counted: {', '.join(bt.POOL_SOURCES)} (use --all-sites for everything)")
    idx = latest_rows(RES)
    analysed = {k for k, r in idx.items() if r["status"] == "done" and os.path.exists(os.path.join(RES, f"{k}.npz"))}
    lp = os.path.join(RES, "pool_links.csv")
    bad = None
    if os.path.exists(lp):
        links = {r["key"]: r["status"] for r in csv.DictReader(open(lp, encoding="utf-8-sig"))}
        bad = {r["key"] for r in rows if links.get(r["key"], "ok") != "ok"}
    import tag_ai
    tags = tag_ai.load_tags()
    show(summarise(rows, analysed, bad, {k: v[0] for k, v in tags.items()} if tags else None), len(rows))
    if a.cross:
        cross(rows)


if __name__ == "__main__":
    main()
