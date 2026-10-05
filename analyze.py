"""Turn ONE audio file into numbers. The audio itself is never saved.

For each song we keep:
  * EffNet chunk embeddings (~1 per second, float16) -> Sound, plus the clip test
  * per-chunk outputs of: instruments (40), mood yes/no heads, genre400 (top 5 only)
  * MusiCNN -> emoMusic / DEAM (valence, arousal) per chunk
  * whole-song averages AND 3 x 30 s part averages (centred at 25/50/75 % of the
    trimmed song) for every chunk-based feature
  * rhythm on the whole trimmed song: bpm, confidence, steadiness, busyness,
    danceability (+ loudness, only as a baseline to beat)
  * timings, so you know how long the laptop takes per step

Use FAKE_MODELS=1 to dry-run without model files (random numbers, for testing code only).
"""
from __future__ import annotations
import os, time
import numpy as np

FAKE = os.environ.get("FAKE_MODELS") == "1"
SR_MODEL, SR_RHYTHM = 16000, 44100
EFFNET_HOP_S = 62 * 256 / SR_MODEL      # 0.992 s between EffNet chunks (patch = 2.048 s)
EFFNET_LEN_S = 128 * 256 / SR_MODEL
MUSICNN_HOP_S = 93 * 256 / SR_MODEL     # 1.488 s between MusiCNN chunks (patch = 2.992 s)
MUSICNN_LEN_S = 187 * 256 / SR_MODEL
PART_LEN_S = 30.0
PART_CENTRES = (0.25, 0.50, 0.75)
ANALYSIS_VERSION = 2          # 2 = adds the candidate Mood/Rhythm models

_cache = {}


def _es():
    import essentia
    essentia.log.warningActive = False
    essentia.log.infoActive = False
    import essentia.standard as es
    return es


def _model(key):
    """Load each TensorFlow model once per process."""
    if key in _cache:
        return _cache[key]
    es = _es()
    import models as M
    if key == "effnet":
        inp, out = M.node("effnet", "embeddings")
        m = es.TensorflowPredictEffnetDiscogs(graphFilename=M.paths("effnet")[0], output=out)
    elif key == "musicnn":
        try:
            inp, out = M.node("musicnn", "embeddings")
        except KeyError:
            out = "model/dense/BiasAdd"
        m = es.TensorflowPredictMusiCNN(graphFilename=M.paths("musicnn")[0], output=out)
    else:
        inp, out = M.node(key, "predictions")
        m = es.TensorflowPredict2D(graphFilename=M.paths(key)[0], input=inp, output=out)
    _cache[key] = m
    return m


# ------------------------------------------------------------------ audio helpers
def load(path):
    es = _es()
    a16 = es.MonoLoader(filename=path, sampleRate=SR_MODEL, resampleQuality=1)()
    a44 = es.MonoLoader(filename=path, sampleRate=SR_RHYTHM, resampleQuality=1)()
    return a16, a44


def trim_bounds(a16, frame_s=0.5, rel_db=45.0, abs_db=-60.0):
    """Start/end (seconds) after cutting quiet lead-in and fade-out.
    A frame counts as 'sound' if louder than max(-60 dBFS, loudest frame - 45 dB)."""
    n = int(frame_s * SR_MODEL)
    frames = a16[: len(a16) // n * n].reshape(-1, n)
    if len(frames) == 0:
        return 0.0, len(a16) / SR_MODEL
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-10)
    thr = max(abs_db, db.max() - rel_db)
    loud = np.where(db > thr)[0]
    if len(loud) == 0:
        return 0.0, len(a16) / SR_MODEL
    return loud[0] * frame_s, (loud[-1] + 1) * frame_s


def part_windows(duration_s):
    """3 windows of 30 s centred at 25/50/75 % (clamped inside the song).
    Songs shorter than 30 s get one window = whole song."""
    if duration_s <= PART_LEN_S:
        return [(0.0, duration_s)]
    out = []
    for c in PART_CENTRES:
        s = min(max(c * duration_s - PART_LEN_S / 2, 0.0), duration_s - PART_LEN_S)
        out.append((s, s + PART_LEN_S))
    return out


def chunk_centres(n, hop, length):
    return np.arange(n) * hop + length / 2


def window_mean(values, centres, win):
    m = (centres >= win[0]) & (centres < win[1])
    if not m.any():                       # very short window: take nearest chunk
        m = np.zeros(len(centres), bool); m[np.argmin(np.abs(centres - (win[0] + win[1]) / 2))] = True
    return values[m].mean(axis=0)


# ------------------------------------------------------------------ features
def rhythm_features(a44):
    es = _es()
    t = time.time()
    bpm, beats, conf, estimates, intervals = es.RhythmExtractor2013(method="multifeature")(a44)
    intervals = np.asarray(intervals)
    steadiness = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 2 else np.nan
    onsets, onset_rate = es.OnsetRate()(a44)
    dance, _ = es.Danceability()(a44)
    loud_db = float(20 * np.log10(np.sqrt(np.mean(a44 ** 2)) + 1e-10))
    return dict(bpm=float(bpm), confidence=float(conf), steadiness=steadiness,
                busyness=float(onset_rate), danceability=float(dance),
                loudness_db=loud_db, n_beats=int(len(beats))), time.time() - t


def _fake(n, d, seed):
    return np.random.default_rng(seed).normal(size=(n, d)).astype(np.float32)


def analyse(path, listed_duration=None):
    """Return (features dict of numpy arrays/scalars, timings dict)."""
    T = {}
    t = time.time()
    a16, a44 = load(path)
    T["decode"] = time.time() - t
    file_dur = len(a16) / SR_MODEL
    s, e = trim_bounds(a16)
    a16t = a16[int(s * SR_MODEL): int(e * SR_MODEL)]
    a44t = a44[int(s * SR_RHYTHM): int(e * SR_RHYTHM)]
    dur = len(a16t) / SR_MODEL
    out = dict(file_duration=file_dur, trim_start=s, trim_end=e, trimmed_duration=dur,
               full_length_ok=(abs(file_dur - listed_duration) <= 3.0) if listed_duration else np.nan)
    seed = int(abs(hash(os.path.basename(path))) % 2**31)

    # ---- Sound: EffNet chunk embeddings
    t = time.time()
    emb = _fake(max(int(dur / EFFNET_HOP_S), 1), 1280, seed) if FAKE else np.asarray(_model("effnet")(a16t))
    T["effnet"] = time.time() - t
    ec = chunk_centres(len(emb), EFFNET_HOP_S, EFFNET_LEN_S)

    # ---- heads on EffNet chunks
    t = time.time()
    heads = {}
    for k, d in (("instruments", 40), ("mood_happy", 2), ("mood_sad", 2), ("mood_aggressive", 2),
                 ("mood_relaxed", 2), ("genre400", 400)):
        heads[k] = (np.abs(_fake(len(emb), d, seed + d)) % 1) if FAKE else np.asarray(_model(k)(emb))
    T["effnet_heads"] = time.time() - t

    # ---- Mood: MusiCNN -> emoMusic / DEAM
    t = time.time()
    mcn = _fake(max(int(dur / MUSICNN_HOP_S), 1), 200, seed + 1) if FAKE else np.asarray(_model("musicnn")(a16t))
    mc = chunk_centres(len(mcn), MUSICNN_HOP_S, MUSICNN_LEN_S)
    va = {}
    for k in ("emomusic", "deam"):
        va[k] = (5 + 2 * np.tanh(_fake(len(mcn), 2, seed + 7))) if FAKE else np.asarray(_model(k)(mcn))
    T["mood"] = time.time() - t

    # ---- whole + parts
    wins = part_windows(dur)
    out["parts"] = np.array(wins)
    out["effnet_chunks"] = emb.astype(np.float16)
    out["effnet_whole"] = emb.mean(axis=0)
    out["effnet_parts"] = np.stack([window_mean(emb, ec, w) for w in wins])
    for k, v in heads.items():
        if k == "genre400":
            whole = v.mean(axis=0)
            top = np.argsort(-whole)[:5]
            out["genre_top5_idx"], out["genre_top5_p"] = top, whole[top]
            continue
        out[f"{k}_whole"] = v.mean(axis=0)
        out[f"{k}_parts"] = np.stack([window_mean(v, ec, w) for w in wins])
        if k == "instruments":
            out["instruments_chunks"] = v.astype(np.float16)
    for k, v in va.items():                       # columns: valence, arousal (see model .json)
        out[f"{k}_whole"] = v.mean(axis=0)
        out[f"{k}_parts"] = np.stack([window_mean(v, mc, w) for w in wins])
        out[f"{k}_chunks"] = v.astype(np.float16)
    out["musicnn_whole"] = mcn.mean(axis=0)

    # ---- Rhythm (whole trimmed song, 44.1 kHz)
    r, T["rhythm"] = rhythm_features(a44t)
    for k, v in r.items():
        out[f"rhythm_{k}"] = v
    # ---- candidates (tested, not yet used by the app). Each is optional and isolated.
    t = time.time()
    out.update(candidates(a16t, a44t, emb, mcn, seed))
    T["candidates"] = time.time() - t
    out["analysis_version"] = ANALYSIS_VERSION
    T["total"] = sum(T.values())
    return out, T


def candidates(a16t, a44t, emb, mcn, seed):
    """Candidate Mood and Rhythm models, all on the same downloaded file.
    Stored with a cand_ prefix. A model that is missing or fails is simply left out."""
    import models as M
    es = _es(); out = {}
    def ok(name):
        return FAKE or M.available(name)
    rngf = np.random.default_rng(seed + 99)
    # Mood: emoMusic and DEAM learned through a different 'ear' (VGGish)
    try:
        if ok("vggish") and (ok("emomusic_vggish") or ok("deam_vggish")):
            if FAKE:
                vg = rngf.normal(size=(max(int(len(a16t) / SR_MODEL / 0.96), 1), 128)).astype(np.float32)
            else:
                if "vggish" not in _cache:
                    inp, outn = M.node("vggish", "embeddings")
                    _cache["vggish"] = es.TensorflowPredictVGGish(graphFilename=M.paths("vggish")[0], output=outn)
                vg = np.asarray(_cache["vggish"](a16t))
            out["cand_vggish_whole"] = vg.mean(axis=0)
            for k in ("emomusic_vggish", "deam_vggish"):
                if ok(k):
                    v = (5 + 2 * np.tanh(rngf.normal(size=(len(vg), 2)))) if FAKE else np.asarray(_model(k)(vg))
                    out[f"cand_{k}_whole"] = v.mean(axis=0)
    except Exception as ex:
        out["cand_error_vggish"] = str(ex)[:200]
    # Mood: yes/no happy & sad through MusiCNN
    for k in ("mood_happy_musicnn", "mood_sad_musicnn"):
        try:
            if ok(k):
                v = (np.abs(rngf.normal(size=(len(mcn), 2))) % 1) if FAKE else np.asarray(_model(k)(mcn))
                out[f"cand_{k}_whole"] = v.mean(axis=0)
        except Exception as ex:
            out[f"cand_error_{k}"] = str(ex)[:200]
    # Rhythm: danceable yes/no on the Sound model's numbers
    try:
        if ok("danceability"):
            v = (np.abs(rngf.normal(size=(len(emb), 2))) % 1) if FAKE else np.asarray(_model("danceability")(emb))
            out["cand_danceability_whole"] = v.mean(axis=0)
    except Exception as ex:
        out["cand_error_danceability"] = str(ex)[:200]
    # Rhythm: TempoCNN (a model trained only to find tempo), 11,025 Hz
    try:
        if ok("tempocnn"):
            if FAKE:
                g = float(rngf.uniform(70, 170)); loc = np.full(10, g); pr = rngf.uniform(0.2, 0.9, size=(10, 256))
            else:
                a11 = es.Resample(inputSampleRate=SR_RHYTHM, outputSampleRate=11025, quality=1)(a44t)
                if "tempocnn" not in _cache:
                    _cache["tempocnn"] = es.TempoCNN(graphFilename=M.paths("tempocnn")[0])
                g, loc, pr = _cache["tempocnn"](a11)
                loc, pr = np.asarray(loc), np.asarray(pr)
            out["cand_tempocnn_bpm"] = float(g)
            if len(loc):
                out["cand_tempocnn_conf"] = float(np.mean(np.max(pr, axis=1))) if pr.ndim == 2 else float(np.mean(pr))
                out["cand_tempocnn_agree"] = float(np.mean(np.abs(np.log2(np.maximum(loc, 1) / max(g, 1))) < 0.06))
    except Exception as ex:
        out["cand_error_tempocnn"] = str(ex)[:200]
    # Rhythm: a second classic tempo estimator (Percival), 44.1 kHz
    try:
        if FAKE:
            out["cand_percival_bpm"] = float(rngf.uniform(70, 170))
        else:
            out["cand_percival_bpm"] = float(es.PercivalBpmEstimator()(a44t))
    except Exception as ex:
        out["cand_error_percival"] = str(ex)[:200]
    return out


if __name__ == "__main__":
    import sys, json
    f, T = analyse(sys.argv[1])
    print(json.dumps({k: (float(v) if np.ndim(v) == 0 else list(np.shape(v))) for k, v in f.items()}, indent=1))
    print("timings (s):", {k: round(v, 2) for k, v in T.items()})
