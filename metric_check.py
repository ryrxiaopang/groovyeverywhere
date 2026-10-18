"""Is cosine similarity the best way to find similar-sounding songs?  (nothing is downloaded; reads results/*.npz)

The Sound feature is a list of 1,280 numbers per song. This script ranks the whole library for a starting song using
different ways to measure "closeness" and checks each against two answers we know without asking anyone:
  * same artist   - for songs whose artist has another song in the library, how high does that other song rank?
                    (hit@10 = it is in the top 10; MRR = how near the top it is on average)
  * same genre    - for songs with a genre label, how many of the top 10 (not counting the same artist) share it?
Neither is "what a listener enjoys", but a distance that cannot find the same artist's other song is not measuring
sound well. Differences are shown with a 95% range over the starting songs, and "vs cosine" is a PAIRED comparison.

  python metric_check.py                 # up to 1500 starting songs per test
  python metric_check.py --n 3000
"""
import argparse
import numpy as np
from results_index import latest_rows, RES, genre_of
import os


def load(keys_wanted=("effnet_whole", "musicnn_whole", "cand_vggish_whole")):
    rows = latest_rows(RES)
    from evaluate import mtg_test_ids
    sealed = mtg_test_ids()                  # rule 2: the sealed test songs never help choose how Sound is measured
    rows = {k: r for k, r in rows.items() if k not in sealed}
    out = {"key": [], "artist": [], "group": []}
    emb = {k: [] for k in keys_wanted}
    for k, r in sorted(rows.items()):
        p = os.path.join(RES, f"{k}.npz")
        if r["status"] != "done" or not os.path.exists(p):
            continue
        try:
            with np.load(p) as d:
                if "effnet_whole" not in d.files:
                    continue
                for e in keys_wanted:
                    emb[e].append(np.asarray(d[e], np.float32) if e in d.files else None)
        except Exception:
            continue
        out["key"].append(k); out["artist"].append((r.get("artist") or "").strip().lower()); out["group"].append(r.get("group") or "")
    return out, emb


# ---------------------------------------------------------------- the ways to measure closeness
def unit(X):
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)


def transforms(X):
    """name -> (matrix, kind). kind: cos / dot / euclid / manhattan. Fitted on the whole library (no labels used)."""
    mu = X.mean(0); sd = X.std(0) + 1e-6
    Xc = X - mu
    _, s, Vt = np.linalg.svd(Xc, full_matrices=False)
    def whiten(k):
        return Xc @ Vt[:k].T / (s[:k] / np.sqrt(len(X)) + 1e-9)
    return {
        "cosine (what we use)": (X, "cos"),
        "dot product": (X, "dot"),
        "Euclidean distance": (X, "euclid"),
        "Euclidean on length-1 vectors": (unit(X), "euclid"),
        "Manhattan distance": (X, "manhattan"),
        "cosine after subtracting the average song": (Xc, "cos"),
        "cosine after rescaling each number (z-score)": ((X - mu) / sd, "cos"),
        "cosine on 64 main directions (PCA)": (Xc @ Vt[:64].T, "cos"),
        "cosine on 64 directions, whitened": (whiten(64), "cos"),
        "cosine on 256 directions, whitened": (whiten(256), "cos"),
    }


def similarity(Q, X, kind):
    """(q, n) similarity, higher = closer."""
    if kind == "cos":
        return unit(Q) @ unit(X).T
    if kind == "dot":
        return Q @ X.T
    if kind == "euclid":
        return -np.sqrt(np.maximum((Q ** 2).sum(1)[:, None] + (X ** 2).sum(1)[None] - 2 * Q @ X.T, 0))
    out = np.empty((len(Q), len(X)), np.float32)           # manhattan, a few starting songs at a time
    for i in range(0, len(Q), 3):
        out[i:i + 3] = -np.abs(Q[i:i + 3, None, :] - X[None, :, :]).sum(2)
    return out


# ---------------------------------------------------------------- the two tests
def artist_test(S, q, art):
    """Per starting song: rank of its best same-artist song, from similarities S (len(q), n)."""
    ranks = np.empty(len(q))
    for r, i in enumerate(q):
        s = S[r].copy(); s[i] = -np.inf
        pos = (art == art[i]); pos[i] = False
        best = s[pos].max()
        ranks[r] = (s > best).sum()
    return ranks


def genre_test(S, q, art, gen):
    """Per starting song: share of its 10 closest (other artists only) that have its genre."""
    out = np.empty(len(q))
    for r, i in enumerate(q):
        s = S[r].copy(); s[i] = -np.inf; s[art == art[i]] = -np.inf
        top = np.argpartition(-s, 10)[:10]
        out[r] = np.mean(gen[top] == gen[i])
    return out


def ci(v, n=2000, seed=0):
    rg = np.random.default_rng(seed)
    m = [rg.choice(v, len(v)).mean() for _ in range(n)]
    return np.percentile(m, [2.5, 97.5])


def paired(a, b, n=2000, seed=0):
    """95% range of mean(a - b) over starting songs."""
    d = np.asarray(a, float) - np.asarray(b, float)
    return ci(d, n, seed)


def row(name, hit, mrr, gen, base):
    h, g = ci(hit), ci(gen)
    dh = paired(hit, base[0]); dg = paired(gen, base[2])
    def flag(lo_hi, v):
        return " *" if lo_hi[0] > 0 else (" ↓" if lo_hi[1] < 0 else "")
    print(f"{name:46s} {100*hit.mean():5.1f}%{flag(dh, 0):2s}  {mrr.mean():.3f}   {100*gen.mean():5.1f}%{flag(dg, 0):2s}"
          f"   ({100*h[0]:.0f}-{100*h[1]:.0f}% / {100*g[0]:.0f}-{100*g[1]:.0f}%)")


def holdout(X, art, source, seed=0, n=1500):
    """Out-of-sample check. Artists are split into two halves; the rescaling (average song, spread of each number,
    main directions) is learned on half A only and used to search half B, so nothing is tuned on the songs it is
    scored on. Also split by site, because the numbers of one site can behave differently from another's."""
    rg = np.random.default_rng(seed)
    names = np.array(sorted({x for x in art if x}))
    half = set(rg.choice(names, len(names) // 2, replace=False))
    in_a = np.array([x in half for x in art]); in_b = ~in_a
    A, B = X[in_a], X[in_b]
    mu, sd = A.mean(0), A.std(0) + 1e-6
    _, s, Vt = np.linalg.svd(A - mu, full_matrices=False)
    cand = {"cosine (what we use)": lambda M: M,
            "cosine after subtracting the average song": lambda M: M - mu,
            "cosine after rescaling each number (z-score)": lambda M: (M - mu) / sd,
            "cosine on 256 directions, whitened": lambda M: (M - mu) @ Vt[:256].T / (s[:256] / np.sqrt(len(A)) + 1e-9)}
    artB, srcB = art[in_b], source[in_b]
    cnt = {k: (artB == k).sum() for k in set(artB) if k}
    ok = np.array([bool(x) and cnt[x] >= 2 for x in artB])
    q = rg.choice(np.where(ok)[0], min(n, ok.sum()), replace=False)
    print(f"\nHOLD-OUT: rescaling learned on {in_a.sum()} songs of {len(half)} artists, tested on {in_b.sum()} songs of "
          f"{len(names) - len(half)} OTHER artists ({len(q)} starting songs)")
    res = {}
    for name, f in cand.items():
        Z = f(B)
        res[name] = (artist_test(similarity(Z[q], Z, "cos"), q, artB) < 10).astype(float)
    base = res["cosine (what we use)"]
    for name, hit in res.items():
        lo, hi = paired(hit, base)
        mark = " *" if lo > 0 else (" ↓" if hi < 0 else "")
        parts = []
        for s_ in sorted(set(srcB[q])):
            m = srcB[q] == s_
            if m.sum() >= 30:
                parts.append(f"{s_} {100 * hit[m].mean():.0f}% (n={m.sum()})")
        print(f"  {name:46s} same artist in top 10: {100 * hit.mean():5.1f}%{mark}   " + ", ".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--holdout-only", action="store_true", help="only the out-of-sample check")
    a = ap.parse_args()
    meta, emb = load()
    X = np.stack(emb["effnet_whole"]).astype(np.float32)
    art = np.array(meta["artist"])
    if a.holdout_only:
        return holdout(X, art, np.array([k.split("_")[0] for k in meta["key"]]), a.seed, a.n)
    cnt = {k: (art == k).sum() for k in set(art) if k}
    has_partner = np.array([bool(x) and cnt[x] >= 2 for x in art])
    is_pool = np.array([g.startswith("pool_") for g in meta["group"]])
    gen = np.array([genre_of(g) if p else "" for g, p in zip(meta["group"], is_pool)])
    print(f"{len(X)} songs; {has_partner.sum()} have another song by the same artist; {is_pool.sum()} carry a genre label\n")
    rng = np.random.default_rng(a.seed)

    q_art = rng.choice(np.where(has_partner)[0], min(a.n, has_partner.sum()), replace=False)
    gi = np.where(is_pool)[0]                                # genre test: library = genre-labelled songs only
    q_gen_local = rng.choice(len(gi), min(a.n, len(gi)), replace=False)

    print("Sound numbers (1,280 per song), different ways to measure closeness")
    print(f"{'measure':46s} {'same artist in top 10':>20s}  {'MRR':>5s}   {'top-10 same genre':>17s}   (95% ranges)")
    results = {}
    for name, (Z, kind) in transforms(X).items():
        S_art = similarity(Z[q_art], Z, kind)
        ranks = artist_test(S_art, q_art, art)
        Zg = Z[gi]
        S_gen = similarity(Zg[q_gen_local], Zg, kind)
        g = genre_test(S_gen, q_gen_local, art[gi], gen[gi])
        results[name] = ((ranks < 10).astype(float), 1.0 / (ranks + 1), g)
    base = results["cosine (what we use)"]
    # pair up the genre comparison against cosine's genre scores, the artist ones against cosine's hit@10
    for name, (hit, mrr, g) in results.items():
        row(name, hit, mrr, g, base)
    print("\n * = clearly better than cosine (the 95% range of the paired difference is above 0);  ↓ = clearly worse.")
    print("   No mark = no clear difference with this many songs.")

    holdout(X, art, np.array([k.split("_")[0] for k in meta["key"]]), a.seed, a.n)

    # ---- other Sound numbers (not metrics): same test, cosine only, on the songs that have every kind
    print("\nOther ways to describe a song's sound, all compared with cosine (songs that have all of them)")
    ok = np.array([v is not None for v in emb["cand_vggish_whole"]]) & np.array([v is not None for v in emb["musicnn_whole"]])
    ok &= has_partner
    idx = np.where(ok)[0]
    print(f"  {len(idx)} songs with a same-artist partner and all three kinds of numbers")
    if len(idx) >= 50:
        sets = {"EffNet 1,280 (what we use)": X,
                "MusiCNN 200 tags": np.stack([v if v is not None else np.zeros(200, np.float32) for v in emb["musicnn_whole"]]),
                "VGGish 128": np.stack([v if v is not None else np.zeros(128, np.float32) for v in emb["cand_vggish_whole"]])}
        sets["EffNet + MusiCNN joined"] = np.hstack([unit(sets["EffNet 1,280 (what we use)"]), unit(sets["MusiCNN 200 tags"])])
        sets["EffNet + VGGish joined"] = np.hstack([unit(sets["EffNet 1,280 (what we use)"]), unit(sets["VGGish 128"])])
        # the library for this test = those songs only, so every kind competes on the same footing
        art2 = art[idx]; q2 = rng.choice(len(idx), min(a.n, len(idx)), replace=False)
        res2 = {}
        for name, M in sets.items():
            M2 = M[idx]
            ranks = artist_test(similarity(M2[q2], M2, "cos"), q2, art2)
            res2[name] = ((ranks < 10).astype(float), 1.0 / (ranks + 1))
        b = res2["EffNet 1,280 (what we use)"][0]
        for name, (hit, mrr) in res2.items():
            lo, hi = paired(hit, b)
            mark = " *" if lo > 0 else (" ↓" if hi < 0 else "")
            print(f"  {name:32s} same artist in top 10: {100*hit.mean():5.1f}%{mark}   MRR {mrr.mean():.3f}")


if __name__ == "__main__":
    main()
