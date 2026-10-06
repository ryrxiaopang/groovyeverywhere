"""Turn ONE song into Voice numbers. The audio and the separated vocals are never saved.

Runs in the separate GPU environment (`.venv-voice`, see VOICE_PIPELINE.md section 3):
  decode -> trim silence (same rule as analyze.py) -> Demucs (vocals stem, in memory, GPU)
  -> per-second singing level -> windows with the most singing
  -> five Sony singer-identity models on every window, on the vocal stem AND on the original mix (control).

What is kept (numbers only), in results/voice/<key>.npz:
  emb_stem  (n_windows, 5 models, 1000) float16   embeddings of the separated vocals
  emb_mix   (n_windows, 5 models, 1000) float16   same windows of the original mix (control arm)
  win_start (n_windows,)                          seconds from the start of the file
  vocal_db / mix_db (n_seconds,) float16          loudness per second of the vocal stem / the mix (the singing gate is
                                                  tuned later on development songs, so the raw levels are kept)
  models, win_s, duration, trimmed_start/end, voice_version

Use FAKE_VOICE=1 to dry-run without a GPU or the models (random numbers; for the offline tests only).
"""
from __future__ import annotations
import os, subprocess, sys, time
import numpy as np

FAKE = os.environ.get("FAKE_VOICE") == "1"
SR = 44100
MODELS = ["byol", "contrastive", "contrastive-vc", "unif-align", "vicreg"]   # 'unif-align' = the uniformity model
WIN_S = 5.0            # window length given to the singer models (development compares shorter / longer by averaging)
MAX_WINDOWS = 8        # non-overlapping windows with the most singing
VOICE_VERSION = 1
SONY_DIR = os.environ.get("SONY_SINGER_DIR", os.path.expanduser("~/ssl-singer-identity"))

_cache = {}


def decode_stereo(path):
    """Whole file -> float32 (2, n) at 44.1 kHz through a pipe (nothing written to disk)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-f", "f32le", "-acodec", "pcm_f32le",
           "-ac", "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return a[: len(a) // 2 * 2].reshape(-1, 2).T.copy()


def trim_bounds(mono, sr=SR, frame_s=0.5, rel_db=45.0, abs_db=-60.0):
    """Same rule as analyze.trim_bounds: cut quiet lead-in and fade-out (a frame is 'sound' if it is louder than
    max(-60 dBFS, loudest frame - 45 dB))."""
    n = int(frame_s * sr)
    frames = mono[: len(mono) // n * n].reshape(-1, n)
    if len(frames) == 0:
        return 0.0, len(mono) / sr
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-10)
    thr = max(abs_db, db.max() - rel_db)
    loud = np.where(db > thr)[0]
    if len(loud) == 0:
        return 0.0, len(mono) / sr
    return loud[0] * frame_s, (loud[-1] + 1) * frame_s


def per_second_db(x, sr=SR):
    """Loudness (dBFS, RMS) of every full second of a (channels, n) signal."""
    m = x.mean(axis=0) if x.ndim == 2 else x
    n = len(m) // sr
    if n == 0:
        return np.zeros(0, np.float32)
    f = m[: n * sr].reshape(n, sr)
    return (20 * np.log10(np.sqrt((f.astype(np.float64) ** 2).mean(axis=1)) + 1e-10)).astype(np.float32)


def pick_windows(vocal_db, n_seconds, win_s=WIN_S, max_windows=MAX_WINDOWS):
    """Deterministic: the non-overlapping windows with the highest mean vocal level (ties -> earlier window).
    A re-run on the same numbers picks the same windows."""
    w = int(round(win_s))
    if n_seconds < w:
        return []
    starts = np.arange(0, n_seconds - w + 1)
    csum = np.concatenate([[0.0], np.cumsum(vocal_db[:n_seconds].astype(np.float64))])
    score = (csum[starts + w] - csum[starts]) / w
    order = np.lexsort((starts, -score))          # best score first, earlier start breaks ties
    chosen = []
    for i in order:
        s = int(starts[i])
        if all(abs(s - c) >= w for c in chosen):
            chosen.append(s)
            if len(chosen) == max_windows:
                break
    return sorted(chosen)


# ------------------------------------------------------------------ models (loaded once, GPU)
def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _demucs():
    if "demucs" not in _cache:
        from demucs.pretrained import get_model
        _cache["demucs"] = get_model("htdemucs").to(_device()).eval()
    return _cache["demucs"]


def _singers():
    if "singers" not in _cache:
        if SONY_DIR not in sys.path:
            sys.path.insert(0, SONY_DIR)
        cwd = os.getcwd()
        os.chdir(SONY_DIR)                 # the Sony loader keeps its downloaded files in ./pretrained_models
        try:
            from singer_identity import load_model
            _cache["singers"] = [load_model(n).eval().to(_device()) for n in MODELS]
        finally:
            os.chdir(cwd)
    return _cache["singers"]


def separate_vocals(stereo):
    """(2, n) float32 -> vocals (2, n) float32, in memory, on the GPU."""
    import torch
    from demucs.apply import apply_model
    model = _demucs()
    dev = _device()
    x = torch.from_numpy(stereo).to(dev)[None]
    ref = x.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        out = apply_model(model, (x - mean) / std, device=dev, split=True, overlap=0.25, progress=False)
    v = (out[0, model.sources.index("vocals")] * std + mean).cpu().numpy().astype(np.float32)
    del x, out
    return v


def embed_windows(mono, starts, win_s=WIN_S):
    """mono (n,) float32 at 44.1 kHz -> (len(starts), n_models, 1000) float16."""
    import torch
    if not starts:
        return np.zeros((0, len(MODELS), 1000), np.float16)
    n = int(win_s * SR)
    batch = torch.from_numpy(np.stack([mono[int(s * SR): int(s * SR) + n] for s in starts])).to(_device())
    outs = []
    with torch.no_grad():
        for m in _singers():
            outs.append(m(batch).float().cpu().numpy())
    return np.stack(outs, axis=1).astype(np.float16)


# ------------------------------------------------------------------ the song
def analyse(path, separate=None, embed=None):
    """One audio file -> (feature dict, timings). `separate` / `embed` can be swapped for fakes in offline tests."""
    separate = separate or (_fake_separate if FAKE else separate_vocals)
    embed = embed or (_fake_embed if FAKE else embed_windows)
    T = {}
    t0 = time.time()
    st = decode_stereo(path)
    T["decode"] = time.time() - t0
    mono = st.mean(axis=0)
    a, b = trim_bounds(mono)
    st = st[:, int(a * SR): int(b * SR)]
    mono = st.mean(axis=0)
    t = time.time()
    voc = separate(st)
    T["separate"] = time.time() - t
    vocal_db, mix_db = per_second_db(voc), per_second_db(st)
    starts = pick_windows(vocal_db, len(vocal_db))
    t = time.time()
    emb_stem = embed(voc.mean(axis=0), starts)
    emb_mix = embed(mono, starts)
    T["embed"] = time.time() - t
    T["total"] = time.time() - t0
    feats = dict(emb_stem=emb_stem, emb_mix=emb_mix, win_start=np.asarray(starts, np.float32),
                 vocal_db=vocal_db.astype(np.float16), mix_db=mix_db.astype(np.float16),
                 models=np.asarray(MODELS), win_s=np.float32(WIN_S), duration=np.float32(len(mono) / SR),
                 trimmed_start=np.float32(a), trimmed_end=np.float32(b), voice_version=np.int32(VOICE_VERSION))
    return feats, T


def _fake_separate(stereo):
    return stereo * 0.5


def _fake_embed(mono, starts, win_s=WIN_S):
    rng = np.random.default_rng(len(mono) + len(starts))
    return rng.normal(size=(len(starts), len(MODELS), 1000)).astype(np.float16)


if __name__ == "__main__":
    import json
    f, T = analyse(sys.argv[1])
    print(json.dumps({k: (list(np.shape(v)) if hasattr(v, "shape") else str(v)) for k, v in f.items()}))
    print({k: round(v, 2) for k, v in T.items()})
