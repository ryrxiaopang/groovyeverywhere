"""Match a short clip against every analysed song (Sound only), the way the app will for a captured song.

A clip is compared with each song's whole-song average AND its 3 parts; the best of those counts
(the clip test showed 'best of whole or parts' finds the right song most often).
"""
import os
import numpy as np
from results_index import latest_rows, RES

_lib = None


def library():
    """(keys, rows, whole[N,1280], parts[N,3,1280]) for every analysed song, L2-normalised. Loaded once."""
    global _lib
    if _lib is not None:
        return _lib
    import pool_db
    P = pool_db.load(pool_only=False)          # the database first (the app's store) ...
    if P is not None:
        W = P["whole"].astype(np.float32); Pt = P["parts"].astype(np.float32)
        W /= np.linalg.norm(W, axis=1, keepdims=True) + 1e-9
        Pt /= np.linalg.norm(Pt, axis=2, keepdims=True) + 1e-9
        meta = [dict(title=t, artist=a, page=l) for t, a, l in zip(P["title"], P["artist_name"], P["link"])]
        _lib = (P["key"], meta, W, Pt)
        return _lib
    rows = latest_rows(RES)                     # ... the results/ files only if it is down
    keys, meta, W, P = [], [], [], []
    for k, r in rows.items():
        p = os.path.join(RES, f"{k}.npz")
        if r["status"] != "done" or not os.path.exists(p):
            continue
        try:
            with np.load(p) as d:
                w = d["effnet_whole"].astype(np.float32)
                parts = d["effnet_parts"].astype(np.float32)
        except Exception:
            print(f"  skipped a damaged file: {os.path.basename(p)} (run python check_results.py)")
            continue
        if parts.shape[0] < 3:
            parts = np.vstack([parts, np.repeat(w[None], 3 - parts.shape[0], 0)])
        keys.append(k); meta.append(r); W.append(w); P.append(parts[:3])
    W = np.stack(W); P = np.stack(P)
    W /= np.linalg.norm(W, axis=1, keepdims=True) + 1e-9
    P /= np.linalg.norm(P, axis=2, keepdims=True) + 1e-9
    _lib = (keys, meta, W, P)
    return _lib


WIN, HOP = 30, 15        # sliding windows: 30 chunks (~30 s), a new one every 15 chunks (~15 s)
_win = None


def windows():
    """(owner index per window, unit vectors [n_windows,1280] float16): every ~30 s stretch of every song, so a
    clip from ANY part of a song has a stored stretch to match, not just the 3 sampled parts.
    Built from the per-chunk numbers in results/*.npz and cached in results/windows_cache.npz."""
    global _win
    if _win is not None:
        return _win
    keys = library()[0]
    cache = os.path.join(RES, "windows_cache.npz")
    if os.path.exists(cache):
        with np.load(cache, allow_pickle=False) as d:
            if list(d["keys"]) == list(keys):
                _win = (d["owner"], d["vecs"].astype(np.float32)); return _win
    print(f"  building the sliding-window index for {len(keys)} songs (once; ~1-3 minutes) ...")
    owner, vecs = [], []
    for i, k in enumerate(keys):
        try:
            with np.load(os.path.join(RES, f"{k}.npz")) as d:
                ch = d["effnet_chunks"].astype(np.float32)
        except Exception:
            continue
        starts = range(0, max(1, len(ch) - WIN + 1), HOP)
        for st in starts:
            v = ch[st: st + WIN].mean(axis=0)
            vecs.append((v / (np.linalg.norm(v) + 1e-9)).astype(np.float16)); owner.append(i)
    owner = np.array(owner, np.int32); vecs = np.stack(vecs)
    np.savez(cache[:-4] + ".tmp.npz", keys=np.array(keys), owner=owner, vecs=vecs)
    os.replace(cache[:-4] + ".tmp.npz", cache)
    _win = (owner, vecs.astype(np.float32))
    return _win


def rank(clip_emb, exclude=None, method="both"):
    """clip_emb: [chunks,1280] or [1280]. Returns (order of song indices best-first, scores).
    method: "whole" (whole-song average only), "both" (whole or one of the 3 stored parts, the original rule),
            "windows" (whole or ANY ~30 s stretch of the song)."""
    keys, meta, W, P = library()
    c = np.asarray(clip_emb, np.float32)
    if c.ndim == 2:
        c = c.mean(axis=0)
    c = c / (np.linalg.norm(c) + 1e-9)
    s = W @ c
    if method == "both":
        s = np.maximum(s, (P @ c).max(axis=1))
    elif method == "windows":
        owner, vecs = windows()
        ws = vecs @ c
        best = np.full(len(keys), -2.0, np.float32)
        np.maximum.at(best, owner, ws)
        s = np.maximum(s, best)
    if exclude:
        s = s.copy(); s[[i for i, k in enumerate(keys) if k in exclude]] = -2
    order = np.argsort(-s)
    return order, s


def position_of(key, order):
    keys = library()[0]
    if key not in keys:
        return None
    i = keys.index(key)
    return int(np.where(order == i)[0][0]) + 1          # 1 = found first


def signal_check(a16, sr=16000):
    """Loudness and silence of a captured clip: a silent capture usually means the site blocks recording."""
    a = np.asarray(a16, np.float64)
    if a.size == 0:
        return dict(rms_db=-120.0, silent_share=1.0)
    fr = sr // 2
    n = len(a) // fr
    rms = np.sqrt(np.mean(a[: n * fr].reshape(n, fr) ** 2, axis=1)) if n else np.array([np.sqrt(np.mean(a ** 2))])
    db = 20 * np.log10(rms + 1e-12)
    return dict(rms_db=round(float(20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-12)), 1),
                silent_share=round(float(np.mean(db < -60)), 2))
