"""Recommendations from the pool for one analysed song ("hidden gems": good matches few people have played).

  python recommend_song.py youtube_OodEsjZ88TQ                    # 10 per list: Sound only, and all four features
  python recommend_song.py youtube_OodEsjZ88TQ --k 15 --features mood+rhythm

The starting song must already be analysed (results/<key>.npz). Same rules as the blind test lists
(blind_test.make_lists): the song itself, copies of it and other songs by the same artist are never recommended,
the least-played 10% of each site are skipped, up to ceil(k/4) songs per artist (HG_MAX_PER_ARTIST), best match first.
"""
import argparse, os
import numpy as np
import blind_test as bt
import scoring
from results_index import RES


pick_best = scoring.pick_best      # moved to scoring.py so blind_test.make_lists can use it too


def recommend(key, k=10, features="mood+rhythm+instruments", rank="match", only=None):
    """Recommendations for a song that is already analysed (results/<key>.npz)."""
    with np.load(os.path.join(RES, f"{key}.npz")) as d:
        q = bt.query_from_analysis(dict(d))
    from results_index import read_meta
    return recommend_query(q, read_meta(key) or {}, k, features, rank, only)   # its own title / artist: re-uploads, covers and the artist are not recommended


def recommend_query(q, meta, k=10, features="mood+rhythm+instruments", rank="match", only=None, languages=None):
    """Recommendations for a query made by bt.query_from_analysis (a stored song, a pasted link or a captured clip).
    meta = {'title': ..., 'artist': ...} of the starting song if known ({} otherwise).
    languages = labels to keep (english, chinese, korean, japanese, other; song_languages.py); None = every song. Songs without a label are always kept."""
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
    none = none | bt.near_copy_mask(P, plain, meta.get("title") or "", meta.get("artist") or "")
    if only:                                # only songs from these pool groups (e.g. yt_jpop yt_jrnb yt_citypop): the rest is left out
        none = none | ~np.isin(np.array(P["group"]), list(only))
        print(f"  only {', '.join(only)}: {int((~none).sum())} candidate songs")
    if languages:                           # the language filter (16 Oct): leave out songs whose label is not chosen; unlabelled songs stay
        import song_languages
        lab, allowed = song_languages.load(), set(languages) | {"unknown"}
        none = none | ~np.array([lab.get(k, "unknown") in allowed for k in P["key"]], bool)
    # a recommendation must not be the song's own artist even when the copy is not in the pool: also match by artist name
    chosen = ["sound"] + [f for f in features.split("+") if f != "sound"]
    match, _, best_pair, passes = scoring.combine([{f: pp[f] for f in chosen} for pp in pair_pct], chosen)
    cap = scoring.max_per_artist(k)          # songs by one artist allowed in a list of k: 3 of 9-10 (HG_MAX_PER_ARTIST overrides)
    if rank == "match":          # best matches first; well-played songs are fine (7 Oct: the project is not only hidden gems)
        a_idx, a_bar = pick_best(pct["sound"], np.ones(n, bool), none, skip, artists, k, max_per_artist=cap)
        b_idx, b_bar = pick_best(match, passes, none, skip, artists, k, max_per_artist=cap)
    else:                        # "obscure": the original hidden-gem rule, least played good match first
        a_idx, a_bar = scoring.pick_hidden_gems(pct["sound"], np.ones(n, bool), P["obscurity"], none, k=k, artists=artists, skip=skip,
                                                max_per_artist=cap)
        b_idx, b_bar = scoring.pick_hidden_gems(match, passes, P["obscurity"], none, k=k, artists=artists, skip=skip, max_per_artist=cap)

    def rows(idx, name):
        out = []
        for i in idx:
            bp = pair_pct[best_pair[i]] if name == "B" else pct
            out.append(dict(key=P["key"][i], title=P["title"][i], artist=P["artist_name"][i], link=P["link"][i],
                            ai=bt.ai_note(P["ai"][i]) if "ai" in P else "",
                            sound=round(float(bp["sound"][i]), 1), mood=round(float(bp.get("mood", pct["mood"])[i]), 1),     # percentiles against the pool, 1 decimal
                            rhythm=round(float(bp.get("rhythm", pct["rhythm"])[i]), 1),                                       # (the top matches all round to 100 otherwise)
                            instruments=round(float(bp.get("instruments", pct["instruments"])[i]), 1),
                            match=round(float(match[i] if name == "B" else pct["sound"][i]), 1),
                            popularity=("rarely played" if P["obscurity"][i] >= 80 else "few plays" if P["obscurity"][i] >= 50 else "well played")))
        return out
    return dict(A=rows(a_idx, "A"), B=rows(b_idx, "B"), A_bar=a_bar, B_bar=b_bar, features=chosen, pool=n, languages=list(languages) if languages else None,
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
