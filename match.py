"""Match a short clip against every analysed song (Sound only), the way the app will for a captured song.

A clip is compared with each song's whole-song average AND its 3 parts; the best of those counts
(the clip test showed 'best of whole or parts' finds the right song most often).
"""
import hashlib, os
import numpy as np
import scoring
from results_index import latest_rows, RES

_lib = None
_scale = {}                # sites the scale is fitted on (None = every pool song of every site) -> (average, spread)
_scale_sources = None
MIN_SCALE_SONGS = 200      # fewer pool songs than this -> the average and spread come from every analysed song


def use_scale_sources(sources):
    """Fit the Sound scale only on pool songs from these sites (e.g. ("youtube",), the sites we recommend from); None / () / "all" = every
    site (the old behaviour, which evaluate.py and the sealed-test copy rely on). Called by blind_test.pool() BEFORE anything is rescaled; the
    library and the sliding windows are rescaled with the scale, so they are dropped when it changes."""
    global _scale_sources, _lib, _win
    new = None if not sources or "all" in sources else tuple(sorted(sources))
    if new != _scale_sources:
        _scale_sources, _lib, _win = new, None, None


def sound_scale():
    """(average, spread) of each of the 1,280 Sound numbers, from the recommendation pool (or, while the pool is
    tiny, from every analysed song). THE one scale every Sound comparison in this process uses (blind test, clip matching,
    evaluate.py), so they all agree. By default it is fitted on every site's pool songs (results/sound_scale.npz);
    after use_scale_sources(("youtube",)) only on that site's (results/sound_scale_youtube.npz). Refitted when the pool changes."""
    src = _scale_sources
    if src in _scale:
        return _scale[src]
    from results_index import pool_keys
    rows = latest_rows(RES)
    done = sorted(k for k, r in rows.items() if r["status"] == "done" and os.path.exists(os.path.join(RES, f"{k}.npz")))
    if src:
        done = [k for k in done if k.split("_")[0] in src]
    pk = pool_keys()
    keys, basis = [k for k in done if k in pk], "pool" + (f" ({', '.join(src)})" if src else "")
    if len(keys) < MIN_SCALE_SONGS:
        keys, basis = done, "all analysed" + (f" ({', '.join(src)})" if src else "")
    h = hashlib.md5(("\n".join(keys) + f"|power={scoring.SOUND_SPREAD_POWER}").encode()).hexdigest()   # refit if either changes
    cache = os.path.join(RES, "sound_scale.npz" if not src else "sound_scale_" + "_".join(src) + ".npz")
    if os.path.exists(cache):
        with np.load(cache) as d:
            if str(d["hash"]) == h:
                _scale[src] = (d["mu"], d["sd"]); return _scale[src]
    X = []
    for k in keys:
        try:
            with np.load(os.path.join(RES, f"{k}.npz")) as d:
                X.append(np.asarray(d["effnet_whole"], np.float64))
        except Exception:
            continue
    _scale[src] = scoring.fit_sound_scale(np.stack(X))
    np.savez(cache[:-4] + ".tmp.npz", hash=h, mu=_scale[src][0], sd=_scale[src][1], n=len(X))
    os.replace(cache[:-4] + ".tmp.npz", cache)
    print(f"  Sound scale fitted on {len(X)} {basis} songs")
    return _scale[src]


def _unit(a):
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def library():
    """(keys, rows, whole[N,1280], parts[N,3,1280]) for every analysed song, rescaled with sound_scale() and then
    L2-normalised. Loaded once."""
    global _lib
    if _lib is not None:
        return _lib
    import pool_db
    P = pool_db.load(pool_only=False)          # the database first (the app's store) ...
    if P is not None:
        sc = sound_scale()
        W = _unit(scoring.scale_sound(P["whole"], sc)).astype(np.float32)
        Pt = _unit(scoring.scale_sound(P["parts"], sc)).astype(np.float32)
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
    sc = sound_scale()
    W = _unit(scoring.scale_sound(np.stack(W), sc)).astype(np.float32)
    P = _unit(scoring.scale_sound(np.stack(P), sc)).astype(np.float32)
    _lib = (keys, meta, W, P)
    return _lib


WIN, HOP = 30, 15        # sliding windows: 30 chunks (~30 s), a new one every 15 chunks (~15 s)
_win = None
_win_plain = None
_win_error = None                       # set when the index cannot be built here (e.g. a demo laptop whose cut-down files have no per-chunk numbers): not retried per request


def window_means(ch):
    """The raw (unrescaled) average of every sliding stretch of one song's per-chunk Sound numbers, [n_windows, 1280] float16."""
    ch = np.asarray(ch, np.float32)
    return np.stack([ch[st: st + WIN].mean(axis=0).astype(np.float16) for st in range(0, max(1, len(ch) - WIN + 1), HOP)])


def windows(scaled=True):
    """(owner index per window, rescaled unit vectors [n_windows,1280]): every ~30 s stretch of every song, so a
    clip from ANY part of a song has a stored stretch to match, not just the 3 sampled parts.
    Built from the per-chunk numbers in results/*.npz; the raw window averages are cached in
    results/windows_cache.npz and rescaled with sound_scale() when loaded."""
    global _win, _win_plain, _win_error
    if _win_error:
        raise RuntimeError(_win_error)
    if not scaled:                      # plain (unrescaled) unit vectors, for checks calibrated on plain cosine
        if _win_plain is None:
            windows()                   # makes sure the cache file exists and is current
            with np.load(os.path.join(RES, "windows_cache.npz"), allow_pickle=False) as d:
                _win_plain = (d["owner"], _unit(d["vecs"].astype(np.float32)).astype(np.float32))
        return _win_plain
    if _win is not None:
        return _win
    keys = library()[0]
    cache = os.path.join(RES, "windows_cache.npz")
    sc = sound_scale()
    if os.path.exists(cache):
        with np.load(cache, allow_pickle=False) as d:
            if "raw" in d.files and list(d["keys"]) == list(keys):          # (older caches held unit vectors: rebuilt)
                _win = (d["owner"], _unit(scoring.scale_sound(d["vecs"].astype(np.float32), sc)).astype(np.float32))
                return _win
    print(f"  building the sliding-window index for {len(keys)} songs (once; ~1-3 minutes) ...")
    owner, vecs = [], []
    for i, k in enumerate(keys):
        try:
            with np.load(os.path.join(RES, f"{k}.npz")) as d:
                ch = d["effnet_chunks"].astype(np.float32)
        except Exception:
            continue
        for v in window_means(ch):
            vecs.append(v); owner.append(i)                                                    # raw means
    if not vecs:
        _win_error = ("the sliding-window index does not match these songs and cannot be rebuilt here (no per-chunk numbers: a demo bundle?). "
                      "Make a new bundle on the desktop, or delete results/windows_cache.npz on the machine that has the full files")
        raise RuntimeError(_win_error)
    owner = np.array(owner, np.int32); vecs = np.stack(vecs)
    np.savez(cache[:-4] + ".tmp.npz", keys=np.array(keys), owner=owner, vecs=vecs, raw=np.array(1))
    os.replace(cache[:-4] + ".tmp.npz", cache)
    _win = (owner, _unit(scoring.scale_sound(vecs.astype(np.float32), sc)).astype(np.float32))
    return _win


def rank(clip_emb, exclude=None, method="both", prepared=False):
    """clip_emb: [chunks,1280] or [1280] of raw Sound numbers (they are rescaled here). prepared=True when it is
    already a library row (library()[2] / [3]), which is rescaled and unit length already.
    Returns (order of song indices best-first, scores).
    method: "whole" (whole-song average only), "both" (whole or one of the 3 stored parts, the original rule),
            "windows" (whole or ANY ~30 s stretch of the song)."""
    keys, meta, W, P = library()
    c = np.asarray(clip_emb, np.float32)
    if c.ndim == 2:
        c = c.mean(axis=0)
    if not prepared:
        c = scoring.scale_sound(c, sound_scale()).astype(np.float32)
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
