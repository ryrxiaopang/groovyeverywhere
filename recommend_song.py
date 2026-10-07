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


def recommend(key, k=10, features="mood+rhythm+instruments"):
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
    # a recommendation must not be the song's own artist even when the copy is not in the pool: also match by artist name
    a_idx, a_bar = scoring.pick_hidden_gems(pct["sound"], np.ones(n, bool), P["obscurity"], none, k=k, artists=artists, skip=skip)
    chosen = ["sound"] + [f for f in features.split("+") if f != "sound"]
    match, _, best_pair, passes = scoring.combine([{f: pp[f] for f in chosen} for pp in pair_pct], chosen)
    b_idx, b_bar = scoring.pick_hidden_gems(match, passes, P["obscurity"], none, k=k, artists=artists, skip=skip)

    def rows(idx, name):
        out = []
        for i in idx:
            bp = pair_pct[best_pair[i]] if name == "B" else pct
            out.append(dict(key=P["key"][i], title=P["title"][i], artist=P["artist_name"][i], link=P["link"][i],
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
              f"{r['popularity']:14s} {r['title'][:44]:44s} {r['artist'][:24]} | {r['link']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--features", default="mood+rhythm+instruments")
    a = ap.parse_args()
    res = recommend(a.key, a.k, a.features)
    print(f"pool {res['pool']} songs; closest plain Sound match {res['best_sound']}")
    show(res, "A", f"Sound only (match bar {res['A_bar']:.0f}%)")
    show(res, "B", f"Sound + {' + '.join(res['features'][1:])} (every feature >= 65%, match bar {res['B_bar']:.0f}%)")
