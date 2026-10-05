"""Scoring rules for Hidden Gems — the same code the app will use later.

Every feature produces a raw similarity (higher = more alike). Raw similarities are
then turned into percentiles against the pool, combined, and re-ranked.

Rules implemented here (all from the plan):
  * Sound / Instruments / Voice: cosine similarity of number lists.
  * Mood: distance on the (happiness, energy) graph after rescaling to the pool.
  * Rhythm: speed compared as a ratio with half/double allowance, weighted by beat
    confidence; steadiness and busyness rescaled (median/IQR, clipped at +-3).
    Intensity is NOT part of Rhythm any more (it double-counted Mood energy).
  * Best part is chosen AFTER combining features, never per feature.
  * Every chosen feature must clear a minimum percentile (default 65).
  * A raw-similarity cutoff per feature stops "best of a bad bunch" results.
"""
from __future__ import annotations
import numpy as np

MAX_RHYTHM_CONFIDENCE = 5.32  # RhythmExtractor2013 multifeature confidence range is 0..5.32


# ---------------------------------------------------------------- basic similarities
def cosine(query: np.ndarray, pool: np.ndarray) -> np.ndarray:
    """query (d,), pool (n, d) -> (n,) cosine similarity."""
    q = query / (np.linalg.norm(query) + 1e-9)
    p = pool / (np.linalg.norm(pool, axis=1, keepdims=True) + 1e-9)
    return p @ q


# Sound is compared AFTER rescaling each of its 1,280 numbers: minus the pool's average, divided by (spread ** 0.25),
# then cosine. Chosen on the VALIDATION data (6 Oct 2026, 1,468 scored songs; nothing from the test split):
#   rescaling                 styles apart (bar 85%)   genres   same artist in top 10 (held-out artists)
#   plain cosine                   87%                  79%         45.5%
#   centre only (power 0)          89%                  80%         47.1%
#   spread ** 0.25  <- used        88%                  80%         47.9%
#   spread ** 0.5                  85%                  79%         48.3%
#   full z-score (power 1)         79% (fails the bar)  77%         48.7%
# Full z-score finds the same artist best but blurs coarse style differences (classical vs electronic) and drops below the
# pre-set bar; 0.25 keeps nearly all of the same-artist gain and beats plain cosine on every measure.
SOUND_SPREAD_POWER = 0.25


def fit_sound_scale(X: np.ndarray, power: float = SOUND_SPREAD_POWER) -> tuple[np.ndarray, np.ndarray]:
    """(average, spread ** power) of each Sound number over a library of songs (n, 1280). Fitted once per pool version.
    power=1 is the full z-score (every number ends with spread 1); the default is the compromise above."""
    X = np.asarray(X, float)
    return X.mean(axis=0), (X.std(axis=0) + 1e-6) ** power


def scale_sound(x: np.ndarray, scale) -> np.ndarray:
    """Rescale Sound numbers (1280,) or (n, 1280) with a scale from fit_sound_scale (None = leave as they are).
    The rescaling is a straight-line change, so the mean of rescaled chunks = the rescaled mean."""
    return np.asarray(x, float) if scale is None else (np.asarray(x, float) - scale[0]) / scale[1]


def robust_scale_stats(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median and IQR per column, computed once per pool version and stored."""
    med = np.median(values, axis=0)
    iqr = np.percentile(values, 75, axis=0) - np.percentile(values, 25, axis=0)
    return med, np.where(iqr < 1e-9, 1.0, iqr)


def robust_scale(values: np.ndarray, med, iqr, clip: float = 3.0) -> np.ndarray:
    return np.clip((values - med) / iqr, -clip, clip)


def mood_similarity(query_va: np.ndarray, pool_va: np.ndarray, mean, std) -> np.ndarray:
    """(valence, arousal) points; rescaled with pool mean/std; similarity = -distance."""
    q = (query_va - mean) / std
    p = (pool_va - mean) / std
    return -np.linalg.norm(p - q, axis=1)


def tempo_distance(bpm_a: float, bpm_b: np.ndarray, half_double_penalty: float = 0.15) -> np.ndarray:
    """Distance in octaves (|log2 ratio|), allowing half/double speed with a small penalty.
    0.0 = identical speed; 0.1 ~= 7% faster/slower."""
    bpm_b = np.asarray(bpm_b, dtype=float)
    same = np.abs(np.log2(bpm_b / bpm_a))
    double = np.abs(np.log2(bpm_b / (bpm_a * 2))) + half_double_penalty
    half = np.abs(np.log2(bpm_b / (bpm_a / 2))) + half_double_penalty
    return np.minimum(same, np.minimum(double, half))


# Beat-confidence range where speed goes from "ignore" to "fully trusted" (0-5.32 scale).
# Calibrated on REAL songs (1 Oct 2026 test): solo piano ~0.5 and quiet sad songs ~0.35 had no
# usable beat; full bands ~2.3 and fast/hip-hop songs ~1.7-2.0 did. (Generated drum loops scored
# 3-4, which is why the first guess of 1.06-3.19 was too strict for real music.)
CONF_IGNORE, CONF_TRUST = 0.8, 2.0


def rhythm_similarity(q: dict, pool: dict, med, iqr, tempo_unit: float = 0.1) -> np.ndarray:
    """q: {'bpm','confidence','steadiness','busyness'} scalars; pool: same keys as arrays.
    med/iqr: robust stats for [steadiness, busyness].
    Speed AND steadiness count less when either song's beat is unclear: the synthetic
    test showed the beat tracker invents a regular 112 BPM 'beat' for a beatless pad
    (confidence 1.1 vs 3-4 for real beats), so both numbers are meaningless there.
    Busyness (notes per second) is always used."""
    t = tempo_distance(q["bpm"], pool["bpm"]) / tempo_unit
    t = np.minimum(t, 3.0)
    conf = np.minimum(q["confidence"], np.asarray(pool["confidence"]))
    w = np.clip((conf - CONF_IGNORE) / (CONF_TRUST - CONF_IGNORE), 0.0, 1.0)
    qs = robust_scale(np.array([q["steadiness"], q["busyness"]]), med, iqr)
    ps = robust_scale(np.column_stack([pool["steadiness"], pool["busyness"]]), med, iqr)
    diff = np.abs(ps - qs)
    return -(w * t + w * diff[:, 0] + diff[:, 1]) / (2 * w + 1.0)


# ---------------------------------------------------------------- percentiles
def to_percentile(sim: np.ndarray, exclude: np.ndarray | None = None) -> np.ndarray:
    """Share of the pool that is LESS similar (0..100). Ties count half.
    `exclude` = boolean mask of pool rows that must not count (the query itself)."""
    sim = np.asarray(sim, dtype=float)
    valid = np.ones_like(sim, bool) if exclude is None else ~exclude
    ref = np.sort(sim[valid])
    n = len(ref)
    lo = np.searchsorted(ref, sim, side="left")
    hi = np.searchsorted(ref, sim, side="right")
    below = lo + (hi - lo - 1).clip(min=0) / 2.0   # don't count the song against itself
    return 100.0 * below / max(n - 1, 1)


# ---------------------------------------------------------------- combining
WHOLE_SONG_WEIGHTS = {"sound": 30, "mood": 25, "voice": 20, "rhythm": 15, "instruments": 10}


def combine(per_pair_percentiles: list[dict[str, np.ndarray]],
            chosen: list[str],
            raw_ok: dict[str, np.ndarray] | None = None,
            weights: dict[str, float] | None = None,
            feature_floor: float = 65.0,
            sound_guard: float | None = 50.0,
            sound_percentiles: list[np.ndarray] | None = None,
            exclude: np.ndarray | None = None):
    """Combine features into one match score per pool song.

    per_pair_percentiles: one dict per part-pair (e.g. 9 for 3x3 parts, or 3 for a clip
        against 3 parts), each mapping feature -> (n,) percentiles. Features that are not
        part-based (rhythm) simply repeat the same array in every dict.
    chosen: features the user picked. Missing features (e.g. voice for instrumental
        songs) are dropped and the weights re-normalised per song (NaN = missing).
    raw_ok: feature -> (n,) bool, False when raw similarity is below the absolute cutoff.
    Returns (match_percentile, combined_raw, best_pair_index, passes_rules)
    """
    w = {f: (weights or {}).get(f, 1.0) for f in chosen}
    n = len(next(iter(per_pair_percentiles[0].values())))
    best = np.full(n, -np.inf)
    best_pair = np.zeros(n, int)
    passes = np.zeros(n, bool)
    for k, pp in enumerate(per_pair_percentiles):
        num = np.zeros(n); den = np.zeros(n); ok = np.ones(n, bool)
        for f in chosen:
            v = pp[f]
            have = ~np.isnan(v)
            num += np.where(have, v * w[f], 0.0)
            den += np.where(have, w[f], 0.0)
            ok &= ~have | (v >= feature_floor)          # every chosen feature must clear the floor
        score = np.where(den > 0, num / np.maximum(den, 1e-9), -np.inf)
        # best part chosen AFTER combining. A part that clears every floor beats one that doesn't, however high the
        # other scores: a song must not be turned down when some part of it passes all the rules.
        better = (ok & ~passes) | ((ok == passes) & (score > best))
        best = np.where(better, score, best)
        best_pair = np.where(better, k, best_pair)
        passes = np.where(better, ok, passes)
    if raw_ok:
        for f in chosen:
            if f in raw_ok:
                passes &= raw_ok[f]
    if sound_guard is not None and "sound" not in chosen and sound_percentiles is not None:
        sp = np.max(np.stack(sound_percentiles), axis=0)
        passes &= sp >= sound_guard                       # keeps results in a related musical world
    match = to_percentile(np.where(np.isfinite(best), best, -1e9), exclude)
    return match, best, best_pair, passes


# ---------------------------------------------------------------- favourite instrument
# What the user can pick, in plain words -> the instrument model's own class names (40 classes).
# Chosen with instrument_check.py on 1,088 songs with human instrument labels (rule: top 2 or top 5% of pool):
#   piano 64% right when it says yes, acoustic guitar 58%, strings 53%, synth 45%, electric guitar 39%.
# Human tags only list the most noticeable instruments, so these are lower bounds: many "wrong" yeses are songs
# that do feature the instrument but weren't tagged for it.
INSTRUMENT_CHOICES = {
    "piano":           ("piano", "electricpiano", "rhodes", "keyboard"),
    "acoustic guitar": ("acousticguitar", "classicalguitar"),
    "electric guitar": ("electricguitar",),
    "synth":           ("synthesizer", "pad"),
    "strings":         ("strings", "violin", "viola", "cello", "orchestra"),
}
# "Only songs with it" is offered where the detector is right at least about half the time.
ONLY_OK = {"piano", "acoustic guitar"}
# The weaker "somewhere in the top 5 instruments" sign is used only where it is right often enough (piano 47%,
# acoustic guitar 42%, strings 40%); for electric guitar (26%) and synth (36%, and in most songs anyway) it isn't.
SOME_OK = {"piano", "acoustic guitar", "strings"}
# Left out, with the reason (instrument_check.py, 2026-10-04):
#   saxophone, brass, woodwind, organ, harp, accordion / harmonica, bells: right 3-21% of the time - the model
#     rarely ranks them high, so the rule falls back to "top of the pool", which is mostly other songs;
#   drums, bass: in most songs anyway (1,000+ of 2,454 pool songs), so as a favourite they barely steer;
#   beat, computer, sampler, voice: not instruments a listener asks for (singing has its own Voice feature).


def instrument_presence(inst: np.ndarray, class_names: list[str], choice: str,
                        top: int = 2, pct: float = 95.0):
    """Does each song clearly feature the chosen instrument?

    inst: (n, 40) instrument likelihoods (whole song). A song counts as featuring it when one of the choice's
    classes is among the song's `top` strongest instruments, OR the choice's likelihood is in the top
    (100 - pct)% of the pool for that instrument (catches songs where it is clear but not the lead).
    Returns (present: bool (n,), strength: (n,) likelihood, for showing / tie-breaking).
    The detector puts the right instrument near the top for 78% of single-instrument songs (evaluate.py)."""
    if choice not in INSTRUMENT_CHOICES:
        raise ValueError(f"unknown instrument {choice!r}; choose from: {', '.join(INSTRUMENT_CHOICES)}")
    cols = [class_names.index(c) for c in INSTRUMENT_CHOICES[choice] if c in class_names]
    if not cols:
        raise ValueError(f"the instrument model has no class for {choice!r}")
    inst = np.asarray(inst, float)
    strength = inst[:, cols].max(axis=1)
    top_idx = np.argsort(-inst, axis=1)[:, :top]
    in_top = np.isin(top_idx, cols).any(axis=1)
    cutoff = np.nanpercentile(strength, pct) if len(strength) else np.inf
    return in_top | (strength >= cutoff), strength


def instrument_somewhere(inst: np.ndarray, class_names: list[str], choice: str, top: int = 5) -> np.ndarray:
    """Weaker sign: the chosen instrument is among the song's `top` strongest instruments. Used only to order
    songs when none of the close matches clearly feature it (e.g. piano in a guitar band), never for 'only'."""
    cols = [class_names.index(c) for c in INSTRUMENT_CHOICES[choice] if c in class_names]
    return np.isin(np.argsort(-np.asarray(inst, float), axis=1)[:, :top], cols).any(axis=1)


# ---------------------------------------------------------------- hidden-gem quality guard
SKIP_LEAST_PLAYED = 10.0     # percent of each site's songs (the least played) that cannot win as a "hidden gem"


def least_played(listens, source, pct: float = SKIP_LEAST_PLAYED, favourites=None, min_songs: int = 20,
                 min_favourites: float = 3) -> np.ndarray:
    """(n,) bool, True = among the least-played `pct`% of the songs of its OWN site, so it must not win only
    because almost nobody has played it (the very least-played uploads are often the roughest).
    Play counts only compare within one site (a YouTube view is not a Jamendo listen), so each source is
    treated alone. Ties at the cut count as inside it, so a site where many songs have the same low count loses all
    of them. A site with fewer than `min_songs` known counts is left alone, and so is a site where every song would
    be flagged (nothing to choose from). Songs with an unknown count are never flagged.
    favourites: optional (n,) counts (NaN = unknown, e.g. FMA's favourites). A song with at least `min_favourites`
    favourites is kept even when few have played it: few plays but liked is exactly a hidden gem. The bar is 3, not 1:
    on FMA 69% of all songs have a favourite and so do 31% of the least played, and those exempt songs would just
    rise to the top of the list again (measured with gem_guard_check.py --favourites)."""
    listens = np.asarray(listens, float)
    source = np.asarray(source)
    out = np.zeros(len(listens), bool)
    if pct <= 0:
        return out
    for s in set(source):
        m = (source == s) & ~np.isnan(listens)
        if m.sum() < min_songs:
            continue
        cut = np.percentile(listens[m], pct)
        flagged = m & (listens <= cut)
        if flagged.sum() == m.sum():
            continue
        out |= flagged
    if favourites is not None:
        out &= ~(np.nan_to_num(np.asarray(favourites, float), nan=0.0) >= min_favourites)
    return out


def pick_hidden_gems(match, passes, obscurity, same_artist_or_dup, k=10,
                     start=90.0, step=5.0, floor=70.0, artists=None, max_per_artist=1,
                     favour=None, favour_mode="prefer", skip=None):
    """Keep match >= start, drop same artist / duplicates, sort least popular first.
    At most `max_per_artist` songs by any one artist in the list (pass `artists`, one label per song), so an
    artist with many songs in the pool can't fill the list. Lower the bar by `step` down to `floor` if fewer
    than k. May return fewer than k: an honest short list beats padding with poor matches.

    favour: optional (n,) bool, e.g. from instrument_presence() for the user's favourite instrument.
      favour_mode "prefer": songs with it come first (each group least popular first); the rest fill the list.
                  "only":   songs without it are left out (the list may then be shorter).
    The match bar is never lowered just to find favoured songs: the instrument steers, Sound still decides.

    skip: optional (n,) bool, e.g. from least_played(): those songs are never picked (the quality guard)."""
    if skip is not None:
        passes = passes & ~np.asarray(skip, bool)
    if favour is not None and favour_mode == "only":
        passes = passes & np.asarray(favour, bool)
    def capped(idx):
        if artists is None:
            return idx
        seen, keep = {}, []
        for i in idx:
            a = artists[i]
            if seen.get(a, 0) < max_per_artist:
                keep.append(i); seen[a] = seen.get(a, 0) + 1
        return np.array(keep, dtype=int)
    bar = start
    while True:
        ok = (match >= bar) & passes & ~same_artist_or_dup
        idx = np.where(ok)[0]
        if favour is not None:                            # favoured first, then least popular first
            idx = idx[np.lexsort((-obscurity[idx], ~np.asarray(favour, bool)[idx]))]
        else:
            idx = idx[np.argsort(-obscurity[idx])]
        idx = capped(idx)
        if len(idx) >= k or bar - step < floor:
            break
        bar -= step
    return idx[:k], bar
