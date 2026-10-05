"""Does the hidden-gem quality guard cost match quality?

Takes random pool songs as starting songs, builds the blind-test lists A (Sound only) and B (Sound + a chosen feature)
with the guard off and on (least-played 0 / 10 / 20 % of each site skipped) and compares, per setting:
  * sound %   mean Sound percentile of the picks (how alike they sound)        - should not drop
  * feature % mean percentile of the features chosen for list B                 - should not drop
  * genre     share of picks in the same genre as the starting song             - should not drop
  * lowest 10% share of picks from the least-played 10% of their site            - should fall (that is the point)
  * length    mean songs per list (3 = full): a guard that empties lists is not free

  python gem_guard_check.py                         # 60 starting songs, mood+rhythm for list B
  python gem_guard_check.py --n 150 --feature instruments --favourites
"""
import argparse
import numpy as np
import scoring
import blind_test
from results_index import genre_of


def query_of(P, i):
    return dict(whole=P["whole"][i], va_vg=P["va_vg"][i], va_mc=P["va_mc"][i], inst=P["inst"][i],
                **{f: float(P[f][i]) for f in ("bpm", "confidence", "steadiness", "busyness")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="starting songs")
    ap.add_argument("--feature", default="mood+rhythm")
    ap.add_argument("--levels", default="0,10,20", help="percent of each site skipped (0 = guard off)")
    ap.add_argument("--favourites", action="store_true", help="keep FMA songs that were favourited")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    P = blind_test.pool()
    n = len(P["key"])
    rng = np.random.default_rng(a.seed)
    starts = rng.choice(n, min(a.n, n), replace=False)
    levels = [float(x) for x in a.levels.split(",")]
    index = {k: i for i, k in enumerate(P["key"])}
    rows = {}
    for lv in levels:
        lowest = scoring.least_played(P["listens"], P["source"], 10.0)      # the same fixed yardstick for every level
        stats = {L: dict(sound=[], feat=[], genre=[], low=[], size=[]) for L in "AB"}
        for i in starts:
            out = blind_test.make_lists(query_of(P, i), a.feature, seed=1, skip_least=lv, use_favourites=a.favourites)
            g0 = genre_of(P["group"][i])
            for L in "AB":
                picks = out[L]
                stats[L]["size"].append(len(picks))
                for s in picks:
                    j = index[s["key"]]
                    stats[L]["sound"].append(s["sound_pct"]); stats[L]["feat"].append(s["feature_pct"])
                    stats[L]["genre"].append(genre_of(P["group"][j]) == g0); stats[L]["low"].append(bool(lowest[j]))
        rows[lv] = stats
    print(f"\n{len(starts)} starting songs from a pool of {n}; list B = Sound + {a.feature}\n")
    print(f"{'list':5s}{'skip %':>7s}{'sound %':>9s}{'feature %':>10s}{'same genre':>11s}{'lowest 10%':>11s}{'length':>8s}")
    for L in "AB":
        for lv in levels:
            s = rows[lv][L]
            print(f"{L:5s}{lv:7.0f}{np.mean(s['sound']):9.1f}{np.mean(s['feat']):10.1f}"
                  f"{100 * np.mean(s['genre']):10.0f}%{100 * np.mean(s['low']):10.0f}%{np.mean(s['size']):8.2f}")
    print("\nRead it like this: from the first row (guard off) down, sound %, feature %, same genre and length should "
          "stay about the same while 'lowest 10%' falls. A drop of a point or two is noise with this few songs.")


if __name__ == "__main__":
    main()
