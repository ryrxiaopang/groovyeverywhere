"""Checks that need no internet and no model files:
  1. Rhythm edge cases on generated drum patterns with a KNOWN speed
  2. Quiet-start/end trimming and the 3-part windows
  3. Scoring rules (percentiles, half/double speed, every-feature minimum,
     best part chosen after combining, honest short lists)

  python synthetic_tests.py
"""
import os, tempfile
import numpy as np
import scoring, analyze

SR = 44100
rng = np.random.default_rng(0)


def hit(kind, n):
    t = np.arange(n) / SR
    if kind == "kick":
        return np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    if kind == "snare":
        return rng.normal(size=n) * np.exp(-t * 25) * 0.6
    return rng.normal(size=n) * np.exp(-t * 90) * 0.25        # hat


def drum_loop(bpm, seconds=40, swing=0.0, drift_to=None, jitter=0.0, half_time=False):
    """Kick on 1 & 3, snare on 2 & 4, hats on 8ths. Optional swing, tempo drift, timing jitter."""
    out = np.zeros(int(seconds * SR)); t = 0.0; beat = 0
    while t < seconds - 0.5:
        cur = bpm if drift_to is None else bpm + (drift_to - bpm) * t / seconds
        spb = 60.0 / cur
        for eighth in range(2):
            pos = t + eighth * spb / 2 + (swing * spb / 2 if eighth else 0) + rng.normal(0, jitter)
            i = int(max(pos, 0) * SR); n = int(0.25 * SR)
            if i + n >= len(out): break
            out[i:i + n] += hit("hat", n)
            if eighth == 0:
                if half_time:   # kick on 1, snare on 3 -> sounds half speed
                    out[i:i + n] += hit("kick" if beat % 4 == 0 else ("snare" if beat % 4 == 2 else "hat"), n)
                else:
                    out[i:i + n] += hit("kick" if beat % 2 == 0 else "snare", n)
        t += spb; beat += 1
    return (out / np.abs(out).max() * 0.8).astype(np.float32)


def pad(seconds=40):
    """Slow swelling chord, no beat at all."""
    t = np.arange(int(seconds * SR)) / SR
    env = 0.5 + 0.5 * np.sin(2 * np.pi * t / 9)
    sig = sum(np.sin(2 * np.pi * f * t) for f in (220, 277.2, 329.6, 440)) * env
    return (sig / np.abs(sig).max() * 0.5).astype(np.float32)


def rhythm_tests():
    print("\n1. RHYTHM on generated drums (known answer)")
    cases = [
        ("steady 120", drum_loop(120), 120),
        ("steady 90", drum_loop(90), 90),
        ("steady 174 (drum & bass speed)", drum_loop(174), 174),
        ("steady 60 (slow)", drum_loop(60), 60),
        ("half-time feel at 140", drum_loop(140, half_time=True), 140),
        ("swing 100", drum_loop(100, swing=0.33), 100),
        ("tempo drift 100->130", drum_loop(100, drift_to=130), None),
        ("sloppy timing 110 (±25 ms)", drum_loop(110, jitter=0.025), 110),
        ("no beat (pad)", pad(), None),
    ]
    rows = []
    for name, audio, true in cases:
        r, _ = analyze.rhythm_features(audio)
        ok = ""
        if true:
            d = scoring.tempo_distance(true, np.array([r["bpm"]]), half_double_penalty=0)[0]
            exact = abs(np.log2(r["bpm"] / true)) < 0.03
            ok = "exact" if exact else ("half/double" if d < 0.03 else "WRONG")
        rows.append((name, r["bpm"], r["confidence"], r["steadiness"], r["busyness"], ok))
        print(f"   {name:32s} bpm={r['bpm']:6.1f}  conf={r['confidence']:.2f}  steadiness={r['steadiness']:.3f}  "
              f"busyness={r['busyness']:.2f}/s  {ok}")
    return rows


def trim_and_parts_tests():
    print("\n2. TRIMMING and 3 PARTS")
    sr = analyze.SR_MODEL
    song = np.concatenate([np.zeros(8 * sr), 0.3 * rng.normal(size=180 * sr), np.zeros(12 * sr)]).astype(np.float32)
    s, e = analyze.trim_bounds(song)
    print(f"   8 s silence + 180 s sound + 12 s silence -> kept {s:.1f}s .. {e:.1f}s  ({'OK' if abs(s-8)<1 and abs(e-188)<1 else 'CHECK'})")
    for d in (25, 60, 95, 180, 420):
        w = analyze.part_windows(d)
        print(f"   {d:4d} s song -> parts " + ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in w))
    assert all(b - a <= 30.01 and a >= 0 and b <= 180 for a, b in analyze.part_windows(180))


def scoring_tests():
    print("\n3. SCORING RULES")
    sim = np.array([0.9, 0.5, 0.7, 0.1, 0.3])
    pct = scoring.to_percentile(sim, exclude=np.array([False] * 5))
    print("   percentiles of [0.9 .5 .7 .1 .3] ->", np.round(pct).astype(int), "(expect 100 50 75 0 25)")
    assert np.allclose(pct, [100, 50, 75, 0, 25])

    d = scoring.tempo_distance(120, np.array([120, 60, 240, 126, 90]))
    print("   speed distance 120 vs [120 60 240 126 90] ->", np.round(d, 3), "(half/double close, 90 far)")
    assert d[0] == 0 and d[1] < d[4] and d[2] < d[4] and d[3] < 0.1

    # beatless query: a made-up 112 BPM must not match a real 112 BPM drum song over another beatless song
    pool = {"bpm": np.array([112., 80.]), "confidence": np.array([3.6, 1.0]),
            "steadiness": np.array([0.01, 0.03]), "busyness": np.array([4.0, 0.3])}
    med, iqr = np.array([0.02, 2.0]), np.array([0.02, 2.0])
    r = scoring.rhythm_similarity({"bpm": 112, "confidence": 1.1, "steadiness": 0.023, "busyness": 0.25}, pool, med, iqr)
    print(f"   beatless pad vs [drum song at same 'speed', other pad] -> {np.round(r, 2)} (other pad must win)")
    assert r[1] > r[0]

    # every-feature minimum: song 0 is great on sound+instruments but bad on mood
    pp = [{"sound": np.array([99., 80.]), "mood": np.array([20., 78.]), "instruments": np.array([99., 75.])}]
    match, raw, _, passes = scoring.combine(pp, ["sound", "mood", "instruments"], feature_floor=65)
    print(f"   one bad feature: song A avg={raw[0]:.0f} passes={passes[0]}, song B avg={raw[1]:.0f} passes={passes[1]}  (A must fail)")
    assert not passes[0] and passes[1]

    # best part chosen AFTER combining: per-feature best would mix part 0 (sound) with part 1 (mood)
    pp = [{"sound": np.array([95.]), "mood": np.array([40.])},
          {"sound": np.array([40.]), "mood": np.array([95.])},
          {"sound": np.array([80.]), "mood": np.array([80.])}]
    _, raw, pair, _ = scoring.combine(pp, ["sound", "mood"])
    print(f"   best part after combining -> pair {pair[0]} with score {raw[0]:.0f} (per-feature max would wrongly give 95)")
    assert pair[0] == 2 and raw[0] == 80

    # missing feature (no singing) -> weights renormalised, not counted as 0
    pp = [{"sound": np.array([90.]), "voice": np.array([np.nan])}]
    _, raw, _, ok = scoring.combine(pp, ["sound", "voice"])
    print(f"   instrumental song with Voice chosen -> score {raw[0]:.0f} from Sound only, passes={ok[0]}")
    assert raw[0] == 90 and ok[0]

    # honest short list
    match = np.array([95, 93, 72, 60, 50.]); passes = np.array([True, True, True, True, True])
    idx, bar = scoring.pick_hidden_gems(match, passes, obscurity=np.arange(5.), same_artist_or_dup=np.zeros(5, bool), k=10)
    print(f"   only 3 songs ≥70% -> returns {len(idx)} songs (bar lowered to {bar:.0f}%), no padding")
    assert len(idx) == 3
    print("   all scoring checks passed")


def make_dry_run_files(folder):
    """Synthetic 'songs' named group__name.wav so run_tests.py --local-dir can exercise the whole pipeline."""
    import essentia.standard as es
    os.makedirs(folder, exist_ok=True)
    specs = {"rhythm_fast": [174, 170, 180, 165], "rhythm_no_steady_beat": [None] * 4,
             "inst_full_band": [120, 110, 128, 100], "rhythm_half_double_trap": [140, 70, 150, 75]}
    n = 0
    for g, bpms in specs.items():
        for i, b in enumerate(bpms):
            body = pad(90) if b is None else drum_loop(b, 90) + 0.3 * pad(90)
            audio = np.concatenate([np.zeros(SR * 2, np.float32), body, np.zeros(SR * 3, np.float32)])
            es.MonoWriter(filename=os.path.join(folder, f"{g}__{i}.wav"), sampleRate=SR, format="wav")(audio.astype(np.float32))
            n += 1
    # filler songs so percentile tests have a pool
    for i in range(16):
        b = float(rng.integers(70, 180))
        es.MonoWriter(filename=os.path.join(folder, f"filler__{i}.wav"), sampleRate=SR, format="wav")(
            (drum_loop(b, 80) * rng.uniform(.3, 1) + rng.uniform(0, .5) * pad(80)).astype(np.float32))
        n += 1
    return n


if __name__ == "__main__":
    rhythm_tests()
    trim_and_parts_tests()
    scoring_tests()
