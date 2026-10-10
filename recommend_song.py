"""Recommendations from the pool for one analysed song ("hidden gems": good matches few people have played).

  python recommend_song.py youtube_OodEsjZ88TQ                    # 10 per list: Sound only, and all four features
  python recommend_song.py youtube_OodEsjZ88TQ --k 15 --features mood+rhythm

The starting song must already be analysed (results/<key>.npz). Same rules as the blind test lists
(blind_test.make_lists): the song itself, copies of it and other songs by the same artist are never recommended,
the least-played 10% of each site are skipped, one song per artist, least popular good match first.
"""
import argparse, csv, os
import numpy as np
import blind_test as bt
import scoring
from results_index import latest_rows, RES


def pick_best(match, passes, none, skip, artists, k, bar=80.0):
    """Best matches first (popularity ignored): songs at or above `bar` that pass every rule, one per artist, highest match first.
    The bar is lowered in steps of 5 (down to 65) until k songs are found; fewer than k is returned rather than padding."""
    while True:
        ok = (match >= bar) & passes & ~none & ~skip
        idx = np.where(ok)[0]
        idx = idx[np.argsort(-match[idx])]
        seen, keep = set(), []
        for i in idx:
            if artists[i] not in seen:
                seen.add(artists[i]); keep.append(i)
        if len(keep) >= k or bar - 5 < 65:
            return np.array(keep[:k], dtype=int), bar
        bar -= 5


def recommend(key, k=10, features="mood+rhythm+instruments", rank="match", only=None):
    with np.load(os.path.join(RES, f"{key}.npz")) as d:
        q = bt.query_from_analysis(dict(d))
    P = bt.pool()
    n = len(P["key"]); artists = np.array(P["artist"])
    skip = scoring.least_played(P["listens"], P["source"], scoring.SKIP_LEAST_PLAYED)
    pairs = bt.pair_similarities(q, P, bt.window_sound(q, P))
    sims = bt.similarities(q, pairs)
    pct = {f: scoring.to_percentile(s) for f, s in sims.items()}
    pair_pct = [{f: scoring.to_percentile(v) for f, v in p.items()} for p in pairs]
    plain = bt.raw_sound(q, P)
    dup = plain >= bt.DUP_COSINE
    none = dup | np.isin(artists, list({artists[i] for i in np.where(dup)[0]}))
    from results_index import read_meta
    meta = read_meta(key) or {}                  # the song's own title / artist: its re-uploads, covers and artist are not recommended
    none = none | bt.near_copy_mask(P, plain, meta.get("title") or "", meta.get("artist") or "")
    if only:                                # only songs from these pool groups (e.g. yt_jpop yt_jrnb yt_citypop): the rest is left out
        none = none | ~np.isin(np.array(P["group"]), list(only))
        print(f"  only {', '.join(only)}: {int((~none).sum())} candidate songs")
    # a recommendation must not be the song's own artist even when the copy is not in the pool: also match by artist name
    chosen = ["sound"] + [f for f in features.split("+") if f != "sound"]
    match, _, best_pair, passes = scoring.combine([{f: pp[f] for f in chosen} for pp in pair_pct], chosen)
    if rank == "match":          # best matches first; well-played songs are fine (7 Oct: the project is not only hidden gems)
        a_idx, a_bar = pick_best(pct["sound"], np.ones(n, bool), none, skip, artists, k)
        b_idx, b_bar = pick_best(match, passes, none, skip, artists, k)
    else:                        # "obscure": the original hidden-gem rule, least played good match first
        a_idx, a_bar = scoring.pick_hidden_gems(pct["sound"], np.ones(n, bool), P["obscurity"], none, k=k, artists=artists, skip=skip)
        b_idx, b_bar = scoring.pick_hidden_gems(match, passes, P["obscurity"], none, k=k, artists=artists, skip=skip)

    def rows(idx, name):
        out = []
        for i in idx:
            bp = pair_pct[best_pair[i]] if name == "B" else pct
            out.append(dict(key=P["key"][i], title=P["title"][i], artist=P["artist_name"][i], link=P["link"][i],
                            ai=bt.ai_note(P["ai"][i]) if "ai" in P else "",
                            sound=round(float(bp["sound"][i])), mood=round(float(bp.get("mood", pct["mood"])[i])),
                            rhythm=round(float(bp.get("rhythm", pct["rhythm"])[i])),
                            instruments=round(float(bp.get("instruments", pct["instruments"])[i])),
                            match=round(float(match[i] if name == "B" else pct["sound"][i])),
                            popularity=("rarely played" if P["obscurity"][i] >= 80 else "few plays" if P["obscurity"][i] >= 50 else "well played")))
        return out
    return dict(A=rows(a_idx, "A"), B=rows(b_idx, "B"), A_bar=a_bar, B_bar=b_bar, features=chosen, pool=n,
                best_sound=round(float(np.max(np.where(none, -np.inf, plain))), 2))


def show(res, name, label):
    print(f"\n## {label}")
    print(f"{'#':>2} {'match':>5} {'sound':>5} {'mood':>5} {'beat':>5} {'inst':>5}  {'plays':14s} {'title':44s} artist / link")
    for i, r in enumerate(res[name], 1):
        print(f"{i:>2} {r['match']:>4}% {r['sound']:>4}% {r['mood']:>4}% {r['rhythm']:>4}% {r['instruments']:>4}%  "
              f"{r['popularity']:14s} {r['title'][:44]:44s} {r['artist'][:24]} | {r['link']}" + (f"   [{r['ai']}]" if r.get("ai") else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--features", default="mood+rhythm+instruments")
    ap.add_argument("--rank", choices=["match", "obscure"], default="match",
                    help="match = best matches first, popularity ignored (default); obscure = least played good match first")
    ap.add_argument("--only", nargs="*", help="only songs from these pool groups, e.g. yt_jpop yt_jrnb yt_citypop")
    a = ap.parse_args()
    res = recommend(a.key, a.k, a.features, a.rank, a.only)
    print(f"pool {res['pool']} songs; closest plain Sound match {res['best_sound']}")
    show(res, "A", f"Sound only (match bar {res['A_bar']:.0f}%)")
    show(res, "B", f"Sound + {' + '.join(res['features'][1:])} (every feature >= 65%, match bar {res['B_bar']:.0f}%)")
