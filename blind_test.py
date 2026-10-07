"""Blind listening test: Sound only vs Sound + one chosen feature vs random same-genre songs.

How it is used (see README, "Blind listening test"):
  1. python capture_server.py, open http://localhost:8765, choose "Blind test": for each friend's song, type
     the friend's initials, the song name and what they like about it (overall sound / mood / rhythm /
     instruments), and let it listen through the microphone for 30 s. The audio is deleted after analysis.
     Each capture makes 3 lists of 3 pool songs and stores them in results/blind/.
  2. python blind_test.py --sheets   -> one listening sheet per friend in blind_sheets/ (CSV, opens in Excel or
     Google Sheets). Songs from the three lists are mixed and unlabelled. Don't look at results/blind/ yourself.
  3. Each friend listens (30-60 s per song is enough) and fills: would_add (y/n), heard_before (y/n), rating (1-5).
  4. python blind_test.py --score blind_sheets/*.csv  -> results per list, with a 95% range.
"""
import argparse, csv, glob, json, os, random, time
import numpy as np
import scoring
from results_index import latest_rows, RES

HERE = os.path.dirname(os.path.abspath(__file__))
BLIND = os.path.join(RES, "blind")
FEATURES = ("sound", "mood", "rhythm", "instruments")


def valid_feature(feature):
    """One feature, or several joined by + (e.g. mood+rhythm)."""
    parts = feature.split("+")
    return bool(parts) and all(f in FEATURES for f in parts)
LISTS = ("A", "B", "C")          # A = Sound only, B = Sound + chosen feature, C = random from the same genre
K = 3                            # songs per list
_pool = None


def _cls(head, name, default):
    try:
        from evaluate import cls_index
        return cls_index(head, name, default)
    except Exception:
        return default


def mood_both(d):
    """(happiness, energy) from both mood models: VGGish -> emoMusic (the chosen one; NaN if this song has no
    output from it yet) and the original MusiCNN -> emoMusic. The caller uses ONE of them for every song."""
    v = np.asarray(d["emomusic_whole"], float)
    mc = np.array([v[_cls("emomusic", "valence", 0)], v[_cls("emomusic", "arousal", 1)]])
    vg = np.array([np.nan, np.nan])
    if "cand_emomusic_vggish_whole" in d:
        g = np.asarray(d["cand_emomusic_vggish_whole"], float)
        vg = np.array([g[_cls("emomusic_vggish", "valence", 0)], g[_cls("emomusic_vggish", "arousal", 1)]])
    return vg, mc


def pool():
    """Every analysed song in a pool list (not marked i_agree = n), with the numbers the lists need.
    Read from PostgreSQL (the app's store); the results/ files are only a fallback if the database is down."""
    global _pool
    if _pool is not None:
        return _pool
    import pool_db
    P = pool_db.load(pool_only=True)
    if P is None:
        P = _pool_from_files()
        P["from"] = "files"
    print(f"  pool: {len(P['key'])} songs (from the {P['from']})")
    _attach_parts(P)
    import match
    P["scale"] = match.sound_scale()                       # Sound is compared after rescaling (scoring.fit_sound_scale)
    P["whole_z"] = scoring.scale_sound(P["whole"], P["scale"])
    P["parts_z"] = scoring.scale_sound(P["parts"], P["scale"])
    _pool = _finish(P)
    return _pool


def parts3(a, whole):
    """(k, d) per-part numbers -> exactly 3 rows. A short song has fewer parts: the missing ones repeat the whole song."""
    a = np.asarray(a, float)
    a = a[None] if a.ndim == 1 else a
    return a[:3] if len(a) >= 3 else np.vstack([a, np.repeat(np.asarray(whole, float)[None], 3 - len(a), 0)])


def _attach_parts(P):
    """Per-part Instruments (n,3,40) and Mood (n,3,2; the original MusiCNN model, the only one that has parts) from
    the results/ files - the database keeps whole-song numbers only. A song whose file is missing uses its whole-song
    numbers for every part."""
    n = len(P["key"])
    P["inst_parts"] = np.repeat(P["inst"][:, None, :], 3, axis=1)
    P["va_mc_parts"] = np.repeat(P["va_mc"][:, None, :], 3, axis=1)
    vi, ai = _cls("emomusic", "valence", 0), _cls("emomusic", "arousal", 1)
    missing = 0
    for i, k in enumerate(P["key"]):
        try:
            with np.load(os.path.join(RES, f"{k}.npz")) as d:
                P["inst_parts"][i] = parts3(d["instruments_parts"], d["instruments_whole"])
                ep = parts3(d["emomusic_parts"], d["emomusic_whole"])
                P["va_mc_parts"][i] = np.column_stack([ep[:, vi], ep[:, ai]])
        except Exception:
            missing += 1
    if missing:
        print(f"  note: {missing} of {n} pool songs have no readable results file, so their parts reuse whole-song numbers")


def _pool_from_files():
    from results_index import pool_keys
    rows = latest_rows(RES)
    members = pool_keys()
    P = {k: [] for k in ("key", "artist", "artist_name", "group", "title", "link", "listens", "source", "whole", "parts",
                         "va_vg", "va_mc", "inst", "bpm", "confidence", "steadiness", "busyness")}
    for k, r in rows.items():
        p = os.path.join(RES, f"{k}.npz")
        if r["status"] != "done" or k not in members or not os.path.exists(p):
            continue
        try:
            with np.load(p) as d:
                d = dict(d)
        except Exception:
            print(f"  skipped a damaged file: {os.path.basename(p)} (run python check_results.py)")
            continue
        vg, mc = mood_both(d)
        parts = np.asarray(d["effnet_parts"], float)
        P["key"].append(k); P["artist"].append((r.get("artist") or k).lower()); P["artist_name"].append(r.get("artist") or "")
        P["group"].append(r["group"])
        P["title"].append(r.get("title", "")); P["source"].append(k.split("_")[0])
        P["link"].append(r.get("page") or (f"https://www.jamendo.com/track/{k.split('_', 1)[1]}" if k.startswith("jamendo_") else ""))
        lst = r.get("listens")
        P["listens"].append(float(lst) if lst not in (None, "", "None") else np.nan)
        P["whole"].append(np.asarray(d["effnet_whole"], float))
        P["parts"].append(parts[:3] if len(parts) >= 3 else np.vstack([parts, np.repeat(d["effnet_whole"][None], 3 - len(parts), 0)]))
        P["va_vg"].append(vg); P["va_mc"].append(mc)
        P["inst"].append(np.asarray(d["instruments_whole"], float))
        for f in ("bpm", "confidence", "steadiness", "busyness"):
            v = float(d[f"rhythm_{f}"]); P[f].append(v if np.isfinite(v) else 0.0)
    if not P["key"]:
        raise RuntimeError("no analysed pool songs yet: finish the pool runs first")
    for k in ("whole", "parts", "va_vg", "va_mc", "inst", "bpm", "confidence", "steadiness", "busyness", "listens"):
        P[k] = np.array(P[k], float)
    return P


def _finish(P):
    # obscurity = share of songs on the SAME site that are more popular (popularity is only comparable within a site)
    ob = np.full(len(P["key"]), 50.0)
    src = np.array(P["source"])
    for s in set(src):
        m = (src == s) & ~np.isnan(P["listens"])
        v = P["listens"][m]
        ob[np.where(m)[0]] = [100.0 * np.mean(v > x) for x in v]
    P["obscurity"] = ob
    # one mood model for every song: the chosen one only if EVERY pool song has it
    if not np.isnan(P["va_vg"]).any():
        P["va"], P["mood_kind"] = P["va_vg"], "vggish"
    else:
        P["va"], P["mood_kind"] = P["va_mc"], "musicnn"
        print(f"  note: {int(np.isnan(P['va_vg'][:, 0]).sum())} pool songs lack the new mood model, so the original one "
              "is used for all. Run: python -u run_tests.py --list <that pool list> --upgrade")
    P["va_mean"], P["va_std"] = P["va"].mean(0), P["va"].std(0) + 1e-9
    P["rh_med"], P["rh_iqr"] = scoring.robust_scale_stats(np.column_stack([P["steadiness"], P["busyness"]]))
    return P


def window_sound(q, P, scaled=True):
    """Sound of the clip against the best ~30 s stretch of every pool song (None if the window cache is unavailable).
    scaled=False gives plain cosine, for the same-song / weak-capture checks whose limits were set on plain cosine."""
    try:
        import match
        lib_keys = match.library()[0]
        owner, vecs = match.windows(scaled)
        c = scoring.scale_sound(q["whole"], P.get("scale") if scaled else None).astype(np.float32)
        c = c / (np.linalg.norm(c) + 1e-9)
        best = np.full(len(lib_keys), -2.0, np.float32)
        np.maximum.at(best, owner, vecs @ c)
        pos = {k: i for i, k in enumerate(lib_keys)}
        return np.array([best[pos[k]] if k in pos else -2.0 for k in P["key"]])
    except Exception as e:
        print(f"  (sliding windows not used: {str(e)[:80]})")
        return None


def pair_similarities(q, P, win_sound=None):
    """Raw similarities as a list of pairs: the clip against pool part 0, 1 and 2, then against the whole song.
    Inside one pair every feature comes from the SAME stretch of the pool song (Sound, Instruments and Mood from
    that part; Rhythm is whole-song, so it repeats), so scoring.combine can pick the best stretch AFTER combining.
    The whole-song pair uses whole-song Instruments / Mood and the better of whole-song Sound and the sliding windows."""
    rhythm = scoring.rhythm_similarity({k: q[k] for k in ("bpm", "confidence", "steadiness", "busyness")},
                                       {k: P[k] for k in ("bpm", "confidence", "steadiness", "busyness")},
                                       P["rh_med"], P["rh_iqr"])
    qs = scoring.scale_sound(q["whole"], P.get("scale"))                # no "scale" in P = plain cosine
    whole, parts = P.get("whole_z", P["whole"]), P.get("parts_z", P["parts"])
    pairs = []
    for j in range(3):
        pv = P["va_mc_parts"][:, j]
        pairs.append({"sound": scoring.cosine(qs, parts[:, j]),
                      "instruments": scoring.cosine(q["inst"], P["inst_parts"][:, j]),
                      "mood": scoring.mood_similarity(q["va_mc"], pv, pv.mean(0), pv.std(0) + 1e-9),
                      "rhythm": rhythm})
    qva = q["va_vg"] if P["mood_kind"] == "vggish" and not np.isnan(q["va_vg"]).any() else q["va_mc"]
    pva = P["va"] if qva is q["va_vg"] or P["mood_kind"] == "musicnn" else P["va_mc"]
    sound = scoring.cosine(qs, whole)
    if win_sound is not None:
        sound = np.maximum(sound, win_sound)
    pairs.append({"sound": sound,
                  "instruments": scoring.cosine(q["inst"], P["inst"]),
                  "mood": scoring.mood_similarity(qva, pva, pva.mean(0), pva.std(0) + 1e-9),
                  "rhythm": rhythm})
    return pairs


def raw_sound(q, P):
    """Plain-cosine Sound (whole song, 3 parts, any ~30 s stretch) for the same-song and weak-capture checks:
    DUP_COSINE and WEAK_COSINE were set on plain cosine and mean something different after rescaling."""
    best = np.max([scoring.cosine(q["whole"], P["parts"][:, j]) for j in range(3)]
                  + [scoring.cosine(q["whole"], P["whole"])], axis=0)
    w = window_sound(q, P, scaled=False)
    return best if w is None else np.maximum(best, w)


def similarities(q, pairs=None):
    """Raw similarity of the starting song to every pool song, per feature (Sound = its best stretch). Used for
    list A, the same-song check and the genre of the closest match; list B uses pair_similarities."""
    P = pool()
    pairs = pairs or pair_similarities(q, P, window_sound(q, P))
    return {"sound": np.max([p["sound"] for p in pairs], axis=0), "mood": pairs[-1]["mood"],
            "rhythm": pairs[-1]["rhythm"], "instruments": pairs[-1]["instruments"]}


def query_from_analysis(feats):
    vg, mc = mood_both(feats)
    return dict(whole=np.asarray(feats["effnet_whole"], float), va_vg=vg, va_mc=mc,
                inst=np.asarray(feats["instruments_whole"], float),
                **{f: float(feats[f"rhythm_{f}"]) if np.isfinite(float(feats[f"rhythm_{f}"])) else 0.0
                   for f in ("bpm", "confidence", "steadiness", "busyness")})


DUP_COSINE = 0.97    # Sound this close = the same recording (e.g. the friend's song is itself in the pool)
WEAK_COSINE = 0.45   # PROVISIONAL: below this the capture is probably mostly room noise; set it from the mic check


_fma_fav = None


def fma_favourites(keys):
    """FMA favourites count per song key (NaN for songs from other sites, or when fma/tracks.csv is not downloaded)."""
    global _fma_fav
    out = np.full(len(keys), np.nan)
    if _fma_fav is None:                             # fma/tracks.csv is large: read it once per run
        try:
            import fma_pool
            _fma_fav = {"fma_" + str(r.get("track_id")): r.get("track.favorites") for r in fma_pool.load()}
        except BaseException as e:                   # fma_pool exits (SystemExit) when the file is missing
            print(f"  (FMA favourites not used: {str(e)[:80]})")
            _fma_fav = {}
    fav = _fma_fav
    for i, k in enumerate(keys):
        try:
            out[i] = float(fav[k])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def make_lists(q, feature, seed=0, skip_least=scoring.SKIP_LEAST_PLAYED, use_favourites=False):
    """A: Sound only. B: Sound + the chosen feature (every chosen feature >= 65%). C: random songs from the
    genre group of the closest Sound match. Each list: K songs, least popular good matches first, 1 per artist.
    Quality guard: A and B never pick a song from the least-played `skip_least`% of its own site (0 = off), so the
    very least-played, often roughest, uploads do not win automatically. use_favourites keeps FMA songs that someone
    favourited even when few played them (needs fma/tracks.csv). C is the random control and is not filtered."""
    P = pool()
    skip = scoring.least_played(P["listens"], P["source"], skip_least,
                                favourites=fma_favourites(P["key"]) if use_favourites else None)
    pairs = pair_similarities(q, P, window_sound(q, P))
    sims = similarities(q, pairs)
    pct = {f: scoring.to_percentile(s) for f, s in sims.items()}
    pair_pct = [{f: scoring.to_percentile(v) for f, v in p.items()} for p in pairs]
    n = len(P["key"]); artists = np.array(P["artist"])
    # the starting song itself (or a copy of it under another site) must never be recommended back,
    # nor other songs by that artist: near-identical Sound = the same recording
    plain = raw_sound(q, P)                                 # plain cosine, for the two checks below
    dup = plain >= DUP_COSINE
    dup_artists = {artists[i] for i in np.where(dup)[0]}
    none = dup | np.isin(artists, list(dup_artists))
    a_idx, a_bar = scoring.pick_hidden_gems(pct["sound"], np.ones(n, bool), P["obscurity"], none, k=K, artists=artists,
                                              skip=skip)
    chosen = ["sound"] + [f for f in feature.split("+") if f != "sound"]    # e.g. "mood+rhythm"
    # the best stretch of each pool song is chosen AFTER combining the features (scoring.combine), so a song whose
    # Sound matches in part 1 but whose Mood matches in part 3 is not scored as if both matched the same stretch
    match, _, best_pair, passes = scoring.combine([{f: pp[f] for f in chosen} for pp in pair_pct], chosen)
    b_idx, b_bar = scoring.pick_hidden_gems(match, passes, P["obscurity"], none, k=K, artists=artists, skip=skip)
    from results_index import genre_of
    best = int(np.argmax(np.where(none, -np.inf, sims["sound"])))
    best_plain = float(np.max(np.where(none, -np.inf, plain)))
    top_group = genre_of(P["group"][best])                  # one genre across sites, not one source list
    rng = random.Random(seed)
    used = set(a_idx) | set(b_idx)
    same = [i for i in range(n) if genre_of(P["group"][i]) == top_group and i not in used and not none[i]]
    c_idx = rng.sample(same, min(K, len(same)))
    out = {}
    for name, idx, bar in (("A", a_idx, a_bar), ("B", b_idx, b_bar), ("C", c_idx, None)):
        out[name] = [dict(key=P["key"][i], title=P["title"][i], artist=P["artist_name"][i], link=P["link"][i],
                          sound_pct=round(float((pair_pct[best_pair[i]] if name == "B" else pct)["sound"][i]), 1),
                          feature_pct=round(float(np.mean([(pair_pct[best_pair[i]] if name == "B" else pct)[f][i]
                                                           for f in chosen])), 1),
                          obscurity=round(float(P["obscurity"][i]), 1))
                     for i in idx]
        out[name + "_bar"] = bar
    out["genre_group"] = top_group
    out["best_sound_cosine"] = round(best_plain, 3)         # how strong the closest real match is (plain cosine)
    out["weak_capture"] = bool(best_plain < WEAK_COSINE)
    out["skipped_least_played"] = int(skip.sum())
    out["excluded_as_same_song"] = [P["key"][i] for i in np.where(dup)[0]]
    out["mood_model"] = P["mood_kind"] if not np.isnan(q["va_vg"]).any() else "musicnn"
    return out


def save_capture(friend, song, feature, q, lists, signal):
    os.makedirs(BLIND, exist_ok=True)
    rec = dict(time=time.strftime("%Y-%m-%d %H:%M"), friend=friend, song=song, feature=feature, signal=signal, **lists)
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}_{''.join(c for c in friend if c.isalnum())[:12]}"
    fn, n = os.path.join(BLIND, stem + ".json"), 1
    while os.path.exists(fn):                       # never overwrite an earlier capture
        n += 1; fn = os.path.join(BLIND, f"{stem}_{n}.json")
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    return fn


def sheets(out_dir=os.path.join(HERE, "blind_sheets")):
    """Shuffled, unlabelled listening sheets. Only NEW captures go into new sheets: a sheet already made is never
    rewritten (a friend may be filling it in). A friend recorded again later gets a second sheet (_2, _3, ...).
    The answer key (results/blind/key.csv) only grows; it records which capture each item came from."""
    recs = []
    for p in sorted(glob.glob(os.path.join(BLIND, "*.json"))):
        with open(p, encoding="utf-8") as f:
            recs.append((os.path.basename(p), json.load(f)))
    if not recs:
        raise SystemExit("no blind-test captures yet (results/blind/ is empty)")
    os.makedirs(out_dir, exist_ok=True)
    kp = os.path.join(BLIND, "key.csv")
    key_rows = []
    if os.path.exists(kp):
        with open(kp, encoding="utf-8") as f:
            key_rows = list(csv.DictReader(f))
    done_caps = {c for r in key_rows for c in (r.get("capture") or "").split("|") if c}   # an item can come from several captures
    safe_of = {r["friend"]: r["safe"] for r in key_rows if r.get("safe")}
    # ONE row per song per friend: a song that is recommended for two of a friend's own songs is rated once (their ratings of
    # the same song twice would be double work for them), and counts for every list it was in (lists = e.g. "AC")
    merged = {}
    for fn, r in recs:
        if fn in done_caps:
            continue
        fr = merged.setdefault(r["friend"], {})
        for L in LISTS:
            for s in r[L]:
                it = fr.get(s["key"])
                if it is None:
                    it = fr[s["key"]] = dict(s, lists=set(), starts=[], captures=[], liked=r["feature"])
                it["lists"].add(L)
                if r["song"] not in it["starts"]:
                    it["starts"].append(r["song"])
                if fn not in it["captures"]:
                    it["captures"].append(fn)
    by_friend = {}
    for friend, d in merged.items():
        order = list(d.values()); random.Random(friend).shuffle(order)
        for it in order:
            it["start_song"] = " | ".join(it["starts"]); it["capture"] = "|".join(it["captures"])
        by_friend[friend] = order
    if not by_friend:
        print("no new captures since the last sheets: nothing written"); return
    new_rows = []
    for friend, items in by_friend.items():
        if friend not in safe_of:                       # unique file name per friend, even "JK" vs "J.K."
            base = "".join(c for c in friend if c.isalnum()) or "friend"
            safe, n = base, 2
            while safe in safe_of.values():
                safe = f"{base}{n}"; n += 1
            safe_of[friend] = safe
        safe = safe_of[friend]
        n = 1
        while os.path.exists(os.path.join(out_dir, f"sheet_{safe}{'' if n == 1 else f'_{n}'}.csv")):
            n += 1
        name = f"sheet_{safe}{'' if n == 1 else f'_{n}'}.csv"
        with open(os.path.join(out_dir, name), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["item", "your_song", "listen_here", "title", "artist", "would_add (y/n)", "heard_before (y/n)", "rating (1-5)"])
            for i, s in enumerate(items, 1):
                item = f"{safe}-{n}-{i:02d}"
                w.writerow([item, s["start_song"], s["link"], s["title"], s["artist"], "", "", ""])
                new_rows.append(dict(item=item, friend=friend, safe=safe, sheet=name, capture=s["capture"],
                                     start_song=s["start_song"], liked=s["liked"], key=s["key"],
                                     lists="".join(sorted(s["lists"]))))
        print(f"  {name}: {len(items)} songs for {friend}")
    cols = ["item", "friend", "safe", "sheet", "capture", "start_song", "liked", "key", "lists"]
    with open(kp + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(key_rows + new_rows)
    os.replace(kp + ".tmp", kp)
    print(f"sheets are in {out_dir}/. Answer key: results/blind/key.csv (don't open it before scoring)")


def _boot(vals, n=2000, seed=0):
    v = np.asarray(vals, float)
    if len(v) < 3:
        return (np.nan, np.nan)
    r = np.random.default_rng(seed)
    return tuple(np.percentile([r.choice(v, len(v)).mean() for _ in range(n)], [2.5, 97.5]))


def score(paths):
    with open(os.path.join(BLIND, "key.csv"), encoding="utf-8") as f:
        key = {r["item"]: r for r in csv.DictReader(f)}
    yes = lambda s: str(s).strip().lower() in ("y", "yes", "1", "true")
    res = {L: {"add": [], "heard": [], "rating": []} for L in LISTS}
    by_feature = {}
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = key.get(r["item"])
                add = r.get("would_add (y/n)", ""); heard = r.get("heard_before (y/n)", ""); rt = r.get("rating (1-5)", "")
                if not k or (not add and not rt):
                    continue
                for L in k["lists"]:
                    if add: res[L]["add"].append(1.0 if yes(add) else 0.0)
                    if heard: res[L]["heard"].append(1.0 if yes(heard) else 0.0)
                    if rt.strip().isdigit(): res[L]["rating"].append(float(rt))
                    if add:
                        by_feature.setdefault((k["liked"], L), []).append(1.0 if yes(add) else 0.0)
    names = {"A": "Sound only", "B": "Sound + chosen feature", "C": "Random, same genre"}
    print(f"{'list':24s} {'would add':>22s} {'rating':>18s} {'heard before':>13s}")
    for L in LISTS:
        a, rt, h = res[L]["add"], res[L]["rating"], res[L]["heard"]
        if not a:
            continue
        lo, hi = _boot(a); rlo, rhi = _boot(rt) if rt else (np.nan, np.nan)
        print(f"{names[L]:24s} {100*np.mean(a):5.0f}% ({100*lo:3.0f}-{100*hi:3.0f}%)  "
              + (f"{np.mean(rt):4.2f} ({rlo:.2f}-{rhi:.2f})" if rt else "        -         ")
              + (f"  {100*np.mean(h):6.0f}%" if h else ""))
    print("\nwould add, by what the friend liked about their song:")
    for (liked, L), v in sorted(by_feature.items()):
        print(f"  {liked:12s} {names[L]:24s} {100*np.mean(v):4.0f}%  (n={len(v)})")
    print("\nRead it like this: A and B should beat C clearly (the matching works). B beating A means the chosen")
    print("feature adds something. Overlapping ranges = no clear difference with this many ratings.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--score", nargs="*")
    a = ap.parse_args()
    if a.sheets:
        sheets()
    elif a.score is not None:
        score(a.score or glob.glob(os.path.join(HERE, "blind_sheets", "*.csv")))
    else:
        ap.print_help()
