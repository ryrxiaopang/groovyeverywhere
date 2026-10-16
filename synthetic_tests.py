"""Checks that need no internet and no model files:
  1. Rhythm edge cases on generated drum patterns with a KNOWN speed
  2. Quiet-start/end trimming and the 3-part windows
  3. Scoring rules (percentiles, half/double speed, every-feature minimum,
     best part chosen after combining, honest short lists)

  python synthetic_tests.py
"""
import os
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

    # the highest-scoring part fails a floor, a slightly lower part clears them all: the song must pass on that part
    pp = [{"sound": np.array([99.]), "mood": np.array([60.])},     # average 79.5 but mood is under the 65 floor
          {"sound": np.array([78.]), "mood": np.array([78.])}]     # average 78 and every feature is above it
    _, raw, pair, ok = scoring.combine(pp, ["sound", "mood"], feature_floor=65)
    print(f"   top part fails a floor, a lower one passes -> uses pair {pair[0]}, score {raw[0]:.0f}, passes={ok[0]}")
    assert ok[0] and pair[0] == 1 and raw[0] == 78

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
    # hidden-gem quality guard: the least-played 10% of each site cannot win
    listens = np.concatenate([np.arange(1., 101.), [1., 2., 3., 4., 5.], np.full(30, 7.)])
    source = np.array(["a"] * 100 + ["b"] * 5 + ["c"] * 30)
    sk = scoring.least_played(listens, source, 10.0)
    print(f"   quality guard: site a flags {sk[:100].sum()} of 100, small site b flags {sk[100:105].sum()}, "
          f"site c (all tied) flags {sk[105:].sum()}")
    assert sk[:100].sum() == 10 and sk[:10].all() and not sk[10:100].any()     # exactly the 10 least played
    assert not sk[100:].any()                                                  # too small / nothing to choose from
    fav = np.full(len(listens), np.nan); fav[0] = 3                            # least played, but someone favourited it
    assert not scoring.least_played(listens, source, 10.0, favourites=fav)[0]
    assert scoring.least_played(listens, source, 10.0, favourites=fav)[1]      # no favourite -> still skipped
    assert not scoring.least_played(listens, source, 0).any()                  # 0 = guard off
    n = 100
    ob = 100.0 * np.mean(listens[:n, None] > listens[None, :n], axis=0)        # share of songs MORE played
    free, _ = scoring.pick_hidden_gems(np.full(n, 99.), np.ones(n, bool), ob, np.zeros(n, bool), k=3)
    guarded, _ = scoring.pick_hidden_gems(np.full(n, 99.), np.ones(n, bool), ob, np.zeros(n, bool), k=3, skip=sk[:n])
    print(f"   least-played songs picked without the guard: {sorted(free)}; with it: {sorted(guarded)} (must avoid 0-9)")
    assert set(free) == {0, 1, 2} and not (set(guarded) & set(range(10)))
    print("   all scoring checks passed")


def sound_scale_test():
    """Sound is compared after rescaling every number by the pool's average and spread."""
    print("\n3b. SOUND RESCALING (z-score before cosine)")
    r = np.random.default_rng(3)
    n, d = 300, 20
    sig = r.normal(size=(n, d))
    X = sig.copy()
    X[:, 0] = 100 * r.normal(size=n) + 500          # one big, meaningless number that plain cosine would follow
    X[:, 1:] += 5.0                                  # and a shared offset that makes every song look alike
    # song 1 is a noisy copy of song 0 in the meaningful numbers only
    X[1] = X[0].copy(); X[1, 1:] += 0.3 * r.normal(size=d - 1); X[1, 0] = 100 * r.normal() + 500
    plain = (scoring.cosine(X[0], X) > scoring.cosine(X[0], X)[1]).sum() - 0
    sc1 = scoring.fit_sound_scale(X, power=1.0)                 # the full z-score
    Z1 = scoring.scale_sound(X, sc1)
    full = (scoring.cosine(Z1[0], Z1) > scoring.cosine(Z1[0], Z1)[1]).sum()
    sc = scoring.fit_sound_scale(X)                             # the setting in use (spread ** 0.25)
    Z = scoring.scale_sound(X, sc)
    scaled = (scoring.cosine(Z[0], Z) > scoring.cosine(Z[0], Z)[1]).sum()
    print(f"   song 1 is the true neighbour of song 0: plain cosine #{plain}, full z-score #{full}, "
          f"spread**{scoring.SOUND_SPREAD_POWER} #{scaled} (counts the songs ranked above it; song 0 itself is one)")
    assert full <= 1 and full < plain                           # (the mild default is deliberately weaker than this)
    assert scoring.cosine(Z[0], Z).argmax() == 0                # a song is still closest to itself
    assert np.allclose(Z1.mean(0), 0, atol=1e-9) and np.allclose(Z1.std(0), 1, atol=1e-3)
    assert np.allclose(Z.mean(0), 0, atol=1e-9)
    assert np.allclose(scoring.scale_sound(X, None), X)                              # no scale = unchanged
    ch = r.normal(size=(40, d)) + 3                                                  # the mean of rescaled chunks ...
    assert np.allclose(scoring.scale_sound(ch, sc).mean(0), scoring.scale_sound(ch.mean(0), sc))   # ... = rescaled mean
    print("   rescaling checks passed")


def blind_pairing_test():
    """blind_test list B: Sound and Mood must match in the SAME part of a pool song."""
    print("\n4. BLIND TEST: best part chosen after combining (same part for every feature)")
    import blind_test
    r = np.random.default_rng(1)
    n, d = 40, 16
    q_vec = r.normal(size=d)
    q = dict(whole=q_vec, inst=np.ones(4), va_vg=np.array([np.nan, np.nan]), va_mc=np.array([0.0, 0.0]),
             bpm=100., confidence=3., steadiness=.02, busyness=2.)
    P = dict(key=[f"f{i}" for i in range(n)], mood_kind="musicnn",
             whole=r.normal(size=(n, d)), parts=r.normal(size=(n, 3, d)), inst=np.ones((n, 4)),
             inst_parts=np.ones((n, 3, 4)), va_mc=r.normal(size=(n, 2)), va_mc_parts=r.normal(size=(n, 3, 2)),
             bpm=np.full(n, 100.), confidence=np.full(n, 3.), steadiness=np.full(n, .02), busyness=np.full(n, 2.))
    P["va"] = P["va_mc"]; P["va_vg"] = np.full((n, 2), np.nan)
    P["rh_med"], P["rh_iqr"] = np.array([.02, 2.]), np.array([.02, 2.])
    X, Y = 0, 1
    # X: Sound matches only in part 1 (index 0), Mood matches only in part 3 (index 2)
    P["parts"][X, 0] = q_vec;               P["va_mc_parts"][X, 0] = [3., 3.]
    P["va_mc_parts"][X, 2] = [.01, .01]
    # Y: both match, a little less perfectly, in the SAME part (part 2)
    P["parts"][Y, 1] = q_vec + 0.1 * r.normal(size=d); P["va_mc_parts"][Y, 1] = [.1, .1]
    pairs = blind_test.pair_similarities(q, P)
    pct = [{f: scoring.to_percentile(v) for f, v in p.items()} for p in pairs]
    chosen = ["sound", "mood"]
    _, raw, pair, passes = scoring.combine([{f: p[f] for f in chosen} for p in pct], chosen)
    mixed = np.mean([max(p["sound"][X] for p in pct), max(p["mood"][X] for p in pct)])   # the old, mixed-up score
    print(f"   song X (sound in part 1, mood in part 3): old mixed score {mixed:.0f}, now {raw[X]:.0f}, passes={passes[X]}")
    print(f"   song Y (both in part 2): score {raw[Y]:.0f}, best part index {pair[Y]}, passes={passes[Y]}")
    assert mixed > 90 and raw[X] < 75 and not passes[X]
    assert passes[Y] and pair[Y] == 1 and raw[Y] > raw[X]
    assert blind_test.parts3(np.ones((1, 4)), np.zeros(4)).shape == (3, 4)      # short song: padded to 3 parts
    print("   blind-test pairing checks passed")


def audio_and_safety_tests():
    """No network: stand-ins for the sites and for yt-dlp. Proves the audio folder is gone after the analysis
    block, whether it ends normally or with an error, for every source; plus the key-redaction and zip guards."""
    print("\n5. NO AUDIO KEPT, and safety helpers")
    import glob, io, subprocess, tempfile, time
    import requests, sources, carry
    tmp_before = set(glob.glob(os.path.join(tempfile.gettempdir(), "hg_*")))
    seen = []

    def run_case(label, info, expect_error):
        for fail in (False, True):
            path_seen = {}
            try:
                with sources.temp_audio(info) as p:
                    path_seen["dir"] = os.path.dirname(p)
                    assert os.path.exists(p) and os.path.getsize(p) > 0, "the audio file should exist while analysing"
                    if fail:
                        raise RuntimeError("analysis crashed")
            except RuntimeError:
                assert fail
            gone = not os.path.exists(path_seen["dir"])
            seen.append(gone)
            print(f"   {label:9s} {'analysis crashed' if fail else 'analysis finished':17s} -> audio folder deleted: {gone}")
            assert gone

    class FakeResp:
        headers = {"Content-Type": "audio/mpeg"}
        def iter_content(self, n): yield b"FAKEAUDIO" * 1000

    real_get, real_run, real_zip = sources._get, subprocess.run, sources._fma_zip
    try:
        sources._get = lambda *a, **k: FakeResp()
        run_case("jamendo", {"source": "jamendo", "download_allowed": True, "download_url": "x"}, False)
        run_case("audius", {"source": "audius", "download_allowed": True, "download_url": "x"}, False)

        def fake_ytdlp(cmd, **k):                      # yt-dlp stand-in: writes the file where -o says
            out = cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp3")
            with open(out, "wb") as f:
                f.write(b"FAKEAUDIO" * 1000)
        subprocess.run = fake_ytdlp
        run_case("youtube", {"source": "youtube", "download_allowed": True,
                             "download_url": "https://www.youtube.com/watch?v=x"}, False)

        class FakeZip:
            def getinfo(self, name): return name
            def open(self, name): return io.BytesIO(b"FAKEAUDIO" * 1000)
        sources._fma_zip = lambda: FakeZip()
        run_case("fma", {"source": "fma", "id": "2048", "download_allowed": True, "download_url": "fma"}, False)
    finally:
        sources._get, subprocess.run, sources._fma_zip = real_get, real_run, real_zip
    left = set(glob.glob(os.path.join(tempfile.gettempdir(), "hg_*"))) - tmp_before
    assert not left, f"leftover audio folders: {left}"

    # genres left out of the pool stay stored but are not pool members
    import results_index
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "pool_list.csv"), "w", encoding="utf-8") as f:
            f.write("group,source,track_id,jamendo_id,i_agree\npool_rock,jamendo,,1,\npool_punk,jamendo,,2,\n"
                    "pool_audius_classical,audius,A1,,\npool_audius_hip-hop_rap,audius,A2,,\nyt_kpop,youtube,V1,,\n")
        keys = results_index.pool_keys(d)
    print(f"   pool members with punk / classical off: {sorted(keys)}")
    assert keys == {"jamendo_1", "audius_A2", "youtube_V1"}

    # a run killed hard leaves its folder; the next start removes it, and only if it is old
    old, new = tempfile.mkdtemp(prefix="hg_test_old_"), tempfile.mkdtemp(prefix="hg_test_new_")
    os.utime(old, (time.time() - 3 * 3600,) * 2)
    removed = sources.sweep_stale_temp()
    print(f"   leftover from a killed run (3 h old) removed: {not os.path.exists(old)}; a fresh folder kept: {os.path.exists(new)}")
    assert not os.path.exists(old) and os.path.exists(new) and removed >= 1
    os.rmdir(new)

    # error text never carries the key, and a rate limit on the last try is an error, not a silent None
    class Limited:
        status_code = 429; headers = {}
        def raise_for_status(self):
            raise requests.HTTPError("429 Client Error for url: https://api.example/v1?client_id=SECRET123&x=1", response=self)
    real_rget, real_sleep, real_pol = requests.get, time.sleep, sources._polite
    requests.get, time.sleep, sources._polite = (lambda *a, **k: Limited()), (lambda s: None), (lambda *a, **k: None)
    try:
        try:
            sources._get("https://api.example/v1", params={"client_id": "SECRET123"})
            raise AssertionError("a rate limit on every try must raise, not return None")
        except requests.HTTPError as e:
            msg, code = str(e), e.response.status_code
    finally:
        requests.get, time.sleep, sources._polite = real_rget, real_sleep, real_pol
    print(f"   rate limit on every try -> raises (status {code}); key in the message: {'SECRET123' in msg}")
    assert code == 429 and "SECRET123" not in msg and "REDACTED" in msg

    bad = ["../evil.csv", "results/../../evil.csv", "/etc/passwd", "results/blind/../../x.json", "notes.txt", "blind_sheets/"]
    good = ["taps.csv", "results/blind/key.csv", "results/blind/2026_a.json", "blind_sheets/sheet_JK.csv", "results/capture_log.csv"]
    print(f"   carry.py refuses {sum(not carry.carried(n) for n in bad)}/{len(bad)} unsafe names, accepts {sum(carry.carried(n) for n in good)}/{len(good)} normal ones")
    assert not any(carry.carried(n) for n in bad) and all(carry.carried(n) for n in good)
    f, rows = carry.read_csv('a,b\n"line one\nline two",2\n')
    assert rows == [{"a": "line one\nline two", "b": "2"}]
    print("   all audio / safety checks passed")


def split_filter_test():
    """evaluate.py --split test must match song keys (jamendo_214), not the zero-padded ids in the MTG files
    (track_0000214), and must read human tags for test-split songs too. (Both were wrong in the first scoring run.)"""
    print("\n6. TEST-SPLIT SCORING: song ids and tags")
    import evaluate
    ids = evaluate.mtg_test_ids()
    assert "jamendo_214" in ids and "jamendo_0000214" not in ids and len(ids) > 10000
    tags = evaluate.mtg_tags()
    assert 214 in tags and "punkrock" in tags[214]["genre"]      # first song of the test file
    print(f"   {len(ids)} test-split song keys, e.g. jamendo_214; tags found for it: {sorted(tags[214]['genre'])}")
    print("   split filter checks passed")


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


def failure_handling_tests():
    """No network, no GPU: replays the failures of the night of 7 Oct and checks that none of them can lose work again.
    (a) YouTube answers 429 or crashes half-way through the list build: what was found is saved, a re-run skips the
        searches that finished.  (b) The Voice runner stops on a missing key / a streak of failed songs, writes only
        numbers, and leaves no audio behind.  (c) pick_windows is deterministic and never overlaps."""
    print("\n7. FAILURE HANDLING (list build and Voice runner)")
    import contextlib, csv, glob, io, json, shutil, sys, tempfile
    import build_youtube as by

    # ---- (a1) _call: 429 is retried, then treated like a quota stop; a 429 followed by success returns the data
    class R:
        def __init__(self, code, body="{}"):
            self.status_code, self.text, self._b = code, body, body
        def json(self):
            return json.loads(self._b)
        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.HTTPError(f"{self.status_code} error")
    real_get, real_sleep, real_polite = by.requests.get, by.time.sleep, by._polite
    os.environ["YOUTUBE_API_KEY"] = "fake-test-key"
    by.time.sleep = lambda s: None
    by._polite = lambda *a, **k: None
    try:
        calls = {"n": 0}
        by.requests.get = lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1) or R(429))
        try:
            by._call("search", q="x")
            raise AssertionError("429 forever should stop the run")
        except by.QuotaUsed:
            print(f"   429 on every try -> retried {calls['n']} times, then a clean quota stop")
            assert calls["n"] == 4
        seq = iter([R(429), R(200, '{"items": [1]}')])
        by.requests.get = lambda *a, **k: next(seq)
        assert by._call("search", q="x") == {"items": [1]}
        print("   429 once, then fine -> the data is returned")
    finally:
        by.requests.get, by.time.sleep, by._polite = real_get, real_sleep, real_polite

    # ---- (a2) list build: crash / quota half-way keeps what was found; a re-run skips finished searches
    with tempfile.TemporaryDirectory() as d:
        real = dict(HERE=by.HERE, DONE_Q=by.DONE_Q, pick=by.pick_for_genre, pk=by.pool_keys, lr=by.latest_rows,
                    argv=sys.argv, ex=dict(by.EXTRA_QUERIES), dg=dict(by.DEFAULT_GENRES))
        by.HERE = d
        by.DONE_Q = os.path.join(d, "results", "done.json")
        by.pool_keys = lambda: []
        by.latest_rows = lambda: {}
        by.EXTRA_QUERIES.clear()
        by.EXTRA_QUERIES.update({"kpop": ["q1", "q2"], "rnb": ["q3"]})
        by.DEFAULT_GENRES.clear()
        by.DEFAULT_GENRES.update({"kpop": "x", "rnb": "y"})
        searched, crash_on = [], ["never", None]

        def fake_pick(genre, query, *a):
            searched.append(query)
            if query == crash_on[0]:
                raise crash_on[1]
            return [dict(source="youtube", track_id=f"{query}-{i}", title="t", artist="a", duration=200, listens=10,
                         licence="x", listen="u", site_genre=genre, group=f"yt_{genre}", i_agree="") for i in range(2)]
        by.pick_for_genre = fake_pick
        try:
            # round order is q1 (kpop), q3 (rnb), q2 (kpop): a stop on the 3rd search keeps the 4 songs of the first two
            for what, exc, expect_exit in (("YouTube quota", by.QuotaUsed(), None), ("unexpected crash", ValueError("boom"), 1)):
                for f in glob.glob(os.path.join(d, "*")) + glob.glob(os.path.join(d, "results", "*")):
                    if os.path.isfile(f):
                        os.remove(f)
                searched.clear()
                crash_on[:] = ["q2", exc]
                sys.argv = ["build_youtube.py", "--variety", "--per", "2", "--pages", "1"]
                code = None
                with contextlib.redirect_stdout(io.StringIO()):
                    try:
                        by.main()
                    except SystemExit as e:
                        code = e.code
                saved = list(csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig")))
                assert code == expect_exit, (what, code)
                assert len(saved) == 4, f"{what}: the 4 songs found before the stop must be saved, got {len(saved)}"
                print(f"   {what} on the 3rd search -> the 4 songs found before it are saved (exit code {code})")
            # re-run after the stop: finished searches are skipped, only the unfinished one is paid for
            searched.clear()
            crash_on[:] = ["never", None]
            with contextlib.redirect_stdout(io.StringIO()):
                by.main()
            assert searched == ["q2"], searched
            print(f"   re-run after the stop -> only {searched} is searched again (finished searches skipped)")
        finally:
            by.HERE, by.DONE_Q, by.pick_for_genre, by.pool_keys, by.latest_rows = (
                real["HERE"], real["DONE_Q"], real["pick"], real["pk"], real["lr"])
            sys.argv = real["argv"]
            by.EXTRA_QUERIES.clear()
            by.EXTRA_QUERIES.update(real["ex"])
            by.DEFAULT_GENRES.clear()
            by.DEFAULT_GENRES.update(real["dg"])

    # ---- (b) Voice runner (FAKE_VOICE: no GPU, no models)
    os.environ["FAKE_VOICE"] = "1"
    import analyze_voice as av, run_voice as rv, sources
    assert av.FAKE
    if shutil.which("ffmpeg") is None:
        print("   (ffmpeg not found: Voice runner checks skipped)")
        return
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "song.wav")
        sig = (0.3 * np.sin(2 * np.pi * 220 * np.arange(SR * 30) / SR)).astype(np.float32)
        analyze._es().MonoWriter(filename=wav, sampleRate=SR, format="wav")(sig)
        vres = os.path.join(d, "voice")
        os.makedirs(vres)
        real = dict(VRES=rv.VRES, INDEX=rv.INDEX, HERE=rv.HERE, jt=sources.jamendo_tracks, ta=sources.temp_audio,
                    argv=sys.argv)
        rv.VRES, rv.INDEX, rv.HERE = vres, os.path.join(vres, "index.csv"), d
        ids = list(range(1, 9))
        with open(os.path.join(d, "l.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["jamendo_id"])
            for i in ids:
                w.writerow([i])
        sources.jamendo_tracks = lambda ids_: {int(i): {"source": "jamendo", "id": i, "download_allowed": True,
                                                         "download_url": "x"} for i in ids_}
        sys.argv = ["run_voice.py", "--list", "l.csv"]
        try:
            os.environ.pop("JAMENDO_CLIENT_ID", None)
            try:
                rv.main()
                raise AssertionError("a missing Jamendo key must stop the run")
            except SystemExit as e:
                assert "JAMENDO_CLIENT_ID" in str(e.code)
                print("   Voice runner without the Jamendo key -> stops at once with a clear message")
            os.environ["JAMENDO_CLIENT_ID"] = "fake"

            @contextlib.contextmanager
            def bad(info):
                raise RuntimeError("network down")
                yield
            sources.temp_audio = bad
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    rv.main()
                    raise AssertionError("a streak of failures must stop the run")
                except SystemExit as e:
                    assert "in a row" in str(e.code)
            rows = list(csv.DictReader(open(rv.INDEX)))
            assert len(rows) == rv.MAX_IN_A_ROW, len(rows)
            print(f"   {rv.MAX_IN_A_ROW} failed songs in a row -> the run stops after {len(rows)} of {len(ids)} songs")
            # normal run: numbers only, audio folder gone, finished songs skipped on the next run
            os.remove(rv.INDEX)
            made = []

            @contextlib.contextmanager
            def good(info):
                with tempfile.TemporaryDirectory(prefix="hg_") as td:
                    p = os.path.join(td, "song.wav")
                    shutil.copy(wav, p)
                    made.append(td)
                    yield p
            sources.temp_audio = good
            with contextlib.redirect_stdout(io.StringIO()):
                rv.main()
            assert all(not os.path.exists(m) for m in made), "audio folders must be deleted"
            files = sorted(os.listdir(vres))
            assert all(f.endswith((".npz", ".csv")) for f in files), files
            z = np.load(os.path.join(vres, "jamendo_1.npz"))
            assert z["emb_stem"].shape[1:] == (5, 1000) and z["emb_stem"].dtype == np.float16
            print(f"   normal run -> {len(files) - 1} .npz files + index only, all {len(made)} audio folders deleted")
            made.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                rv.main()
            assert not made, "finished songs must be skipped on a re-run"
            print("   re-run -> finished songs skipped")
        finally:
            rv.VRES, rv.INDEX, rv.HERE = real["VRES"], real["INDEX"], real["HERE"]
            sources.jamendo_tracks, sources.temp_audio, sys.argv = real["jt"], real["ta"], real["argv"]

    # ---- (c) windows: deterministic, non-overlapping, and none for a clip shorter than one window
    v = np.array([-70] * 20 + [-20] * 10 + [-60] * 20 + [-25] * 10, dtype=np.float32)
    w1, w2 = av.pick_windows(v, len(v)), av.pick_windows(v, len(v))
    assert w1 == w2 and all(b - a >= 5 for a, b in zip(w1, w1[1:])), w1
    assert av.pick_windows(v[:3], 3) == []
    print(f"   windows: same pick on a re-run, no overlap ({len(w1)} windows), none for a 3 s clip")


def near_copy_test():
    """A re-upload / cover / slowed version of the starting song, and other songs by its artist, must never be recommended back,
    even when the Sound match sits just under the 0.97 same-recording cut-off; a DIFFERENT song with the same title must stay."""
    print("\n8. NEAR-COPIES OF THE STARTING SONG")
    import blind_test as bt
    P = dict(key=list("abcdefg"),
             title=["Earrings (Lyrics)", "earrings - slowed", "Some Other Song", "Earrings", "Brand New Day", "Earrings", "Malcolm Todd - Chest"],
             artist_name=["lyric channel", "slow channel", "x", "Another Band", "Malcolm Todd", "Cover Kid", "y"])
    plain = np.array([0.96, 0.95, 0.99, 0.60, 0.70, 0.88, 0.40])
    m = bt.near_copy_mask(P, plain, "Earrings", "Malcolm Todd")
    #   a lyric re-upload (title + close sound), a slowed copy, a different song, a different song called Earrings that sounds
    #   unlike it, another song BY the artist (artist name), a cover (title + close sound), the artist's name in the title
    expect = [True, True, False, False, True, True, True]
    assert list(m) == expect, list(m)
    print("   re-upload, slowed copy, cover and the artist's other songs are dropped; a different song with the same title stays")


def round2_test():
    """Round 2 settings (10 Oct 2026): only YouTube songs are recommended, lists are best-match-first, and the AI note stays off
    the friends' sheets unless HG_AI_NOTE=1."""
    print("\n9. ROUND 2 SETTINGS: YouTube-only pool, best match first, no AI note")
    import blind_test as bt, importlib, os
    # (a) site filter: FMA / Jamendo / Audius songs are left out, YouTube songs stay, whichever store the numbers came from
    keys = ["youtube_a", "fma_1", "jamendo_2", "audius_3", "youtube_b"]
    P = dict(key=list(keys), source=[k.split("_")[0] for k in keys], link=["l"] * 5, listens=np.arange(5.0), whole=np.zeros((5, 2)))
    out = bt.apply_quality(P)
    assert bt.POOL_SOURCES == ("youtube",), bt.POOL_SOURCES
    assert out["key"] == ["youtube_a", "youtube_b"] and out["whole"].shape == (2, 2) and out["listens"].tolist() == [0.0, 4.0], out["key"]
    # (b) best match first: highest match wins even when it is the most played song; one per artist; same-song / skipped songs never picked
    match = np.array([95., 90., 88., 85., 99., 70.])
    obscurity = np.array([0., 100., 50., 80., 10., 90.])           # song 0 is the most played one
    artists = np.array(["a", "b", "c", "c", "d", "e"])
    none = np.array([False] * 4 + [True, False])                   # song 4 is a copy of the starting song
    skip = np.array([False, False, False, False, False, False]); skip[1] = True
    idx, bar = scoring.pick_best(match, np.ones(6, bool), none, skip, artists, 3)
    assert list(idx) == [0, 2, 5] and bar == 70.0, (list(idx), bar)
    #   0 = best match although it is the MOST played; 1 skipped (quality guard); 3 same artist as 2; 4 copy of the starting song;
    #   the bar fell from 80 to 70 to find 3 songs, so 5 (match 70) joins at the end
    #   the per-artist cap follows the list size: 1 of 3, 3 of 9 or 10 (10 Oct), HG_MAX_PER_ARTIST overrides
    assert [scoring.max_per_artist(k) for k in (3, 4, 5, 9, 10, 20)] == [1, 1, 2, 3, 3, 5]
    art3 = np.array(["a"] * 4 + ["b"] * 2)
    top3, _ = scoring.pick_best(np.array([99., 98, 97, 96, 95, 94]), np.ones(6, bool), np.zeros(6, bool), np.zeros(6, bool), art3, 5, max_per_artist=3)
    assert list(top3) == [0, 1, 2, 4, 5], list(top3)               # at most 3 by artist "a" (song 3 is the 4th), the rest from "b"
    idx2, _ = scoring.pick_hidden_gems(match, np.ones(6, bool), obscurity, none, k=3, artists=artists, skip=skip)
    assert idx2[0] != idx[0] and idx2[0] == 5, idx2                # the old rule starts with the least played (5), the best match comes last
    # (c) the AI note: empty for the friend unless HG_AI_NOTE=1; the researcher's ai_note() always works
    assert bt.AI_NOTE_FOR_FRIENDS is False and bt.friend_note("likely") == "" and bt.friend_note("confirmed") == ""
    assert bt.ai_note("likely") == "likely AI-generated"
    old = os.environ.get("HG_AI_NOTE")
    os.environ["HG_AI_NOTE"] = "1"
    try:
        on = importlib.reload(bt)
        assert on.friend_note("confirmed") == "AI-generated (confirmed)" and on.friend_note("none") == ""
    finally:
        if old is None:
            os.environ.pop("HG_AI_NOTE", None)
        else:
            os.environ["HG_AI_NOTE"] = old
        importlib.reload(bt)
    # (d) a sheet has no 'note' column when the note is off, and refresh_sheets drops an old one
    import refresh_sheets as rs
    assert "note" not in rs.COLS and "also_on" in rs.COLS
    r = rs.fix_row({"item": "x-1-01", "listen_here": "http://a", "also_on": "", "note": "likely AI-generated"},
                   {"x-1-01": "youtube_a"}, {}, {}, {"youtube_a": ("likely", "", 5.0)})
    assert r["note"] == "", r
    print("   FMA / Jamendo / Audius left out; best match first (not least played); the AI note is off for friends and a sheet has no note column")


def deezer_discover_test():
    """deezer_discover.py with a canned Deezer (no network): crawl depth, votes, and every filter."""
    print("\n10. DEEZER ARTIST DISCOVERY (canned answers)")
    import deezer_discover as dd
    _get, _save = dd.Deezer.get, dd.Deezer.save
    try:

        # fake Deezer: seed "The 1975" (id 1) -> related 2..9 ; 2 -> related 10
        ARTISTS = {  # id: (name, fans, albums, deezer genre id of its albums, top titles)
            2: ("Indie Band", 120000, 4, 85, ["a", "b", "c"]),            # Alternative -> alternative
            3: ("Tiny Uploader", 800, 5, 85, ["a", "b", "c"]),            # too few fans
            4: ("Superstar", 9000000, 9, 132, ["a", "b", "c"]),           # too many fans
            5: ("Metal Guys", 90000, 3, 464, ["a", "b", "c"]),            # Metal: not mapped
            6: ("Folk Singer", 50000, 3, 466, ["a", "b", "c"]),           # Folk -> indiefolk
            7: ("Already In Pool", 70000, 3, 85, ["a", "b", "c"]),
            8: ("One Album", 70000, 1, 85, ["a", "b", "c"]),              # too few albums
            9: ("한국 밴드", 60000, 3, 16, ["노래", "b", "c"]),             # Asian Music + Hangul -> kpop
            10: ("Deep Rock", 40000, 2, 152, ["a", "b", "c"]),            # Rock, found at depth 2
            11: ("Latin Asian", 40000, 2, 16, ["a", "b", "c"]),           # Asian Music, Latin script -> skipped
            12: ("Rock Two", 41000, 2, 152, ["a", "b", "c"]),
        }
        GENRES = {85: "Alternative", 132: "Pop", 464: "Metal", 466: "Folk", 16: "Asian Music", 152: "Rock"}
        RELATED = {1: [2, 3, 4, 5, 6, 7, 8, 9, 11], 2: [10, 12, 6], 6: [10]}
        calls = []
        def fake_get(self, path, **p):
            calls.append(path)
            if path == "/search/artist":
                return {"data": [{"id": 1, "name": "The 1975"}]} if p["q"].lower() == "the 1975" else {"data": [{"id": 99, "name": "Other"}]}
            if path == "/genre":
                return {"data": [{"id": k, "name": v} for k, v in GENRES.items()]}
            if path.endswith("/related"):
                aid = int(path.split("/")[2])
                return {"data": [{"id": i, "name": ARTISTS[i][0], "nb_fan": ARTISTS[i][1], "nb_album": ARTISTS[i][2]} for i in RELATED.get(aid, [])]}
            if path.endswith("/top"):
                aid = int(path.split("/")[2])
                return {"data": [{"title": t, "title_short": t, "duration": 200, "album": {"id": aid * 100}} for t in ARTISTS[aid][4]]}
            if path.startswith("/album/"):
                aid = int(path.split("/")[2]) // 100
                return {"genres": {"data": [{"id": ARTISTS[aid][3]}]}}
            return {}
        dd.Deezer.get = fake_get
        dd.Deezer.save = lambda self: None
        dz = dd.Deezer(cache_path="/nonexistent/x.json")
        cand = dd.crawl(dz, ["The 1975", "Nobody Known"], 2)
        assert 10 in cand and cand[10]["depth"] == 2 and cand[6]["votes"] == 2, cand[6]   # 6 is pointed at by seed and by 2
        class A: target = 10; min_fans = 5000; max_fans = 1500000; min_albums = 2; quota = ["rock=1"]
        taken = {dd.norm("Already In Pool")}
        picked, why, used = dd.choose(dz, cand, A, taken, set())
        names = [c["name"] for c in picked]
        print(names, why, used)
        assert names[0] == "Folk Singer"                     # most votes first
        assert set(names) == {"Folk Singer", "Indie Band", "한국 밴드", "Deep Rock"}, names   # Rock Two cut by the rock=1 quota
        assert [c["genre"] for c in picked if c["name"] == "한국 밴드"] == ["kpop"] and used["indiefolk"] == 1 and used["rock"] == 1
        assert why == {"fans": 2, "albums": 1, "in pool / skipped": 1, "genre": 2, "quota": 1}, why
        # the age filter: with --since the old act is left out and the year range is recorded; without it nothing changes (and albums without a date never count as old)
        YEARS = {2: "2022-05-01", 6: "1999-01-01", 10: "2020-03-03", 9: "2019-01-01"}
        _fg = fake_get
        def dated(self, path, **p):
            r = _fg(self, path, **p)
            if path.startswith("/album/"):
                r = dict(r, release_date=YEARS.get(int(path.split("/")[2]) // 100, ""))
            return r
        dd.Deezer.get = dated
        class B(A): since = 2015
        p2, why2, _ = dd.choose(dd.Deezer(cache_path="/nonexistent/x.json"), cand, B, {dd.norm("Already In Pool")}, set())
        assert "Folk Singer" not in [c["name"] for c in p2] and why2.get("age") == 1, (why2, [c["name"] for c in p2])
        assert [c["years"] for c in p2 if c["name"] == "Indie Band"] == [(2022, 2022)]
        p3, why3, _ = dd.choose(dd.Deezer(cache_path="/nonexistent/x.json"), cand, A, {dd.norm("Already In Pool")}, set())
        assert "age" not in why3 and "Folk Singer" in [c["name"] for c in p3]
        assert dd.DEFAULT_QUOTA["rock"] == 4
        # your own genre label (deezer_genres.txt): wins over Deezer's, still needs a quota genre, comments and blanks are ignored
        import tempfile as _tf
        ov_path = os.path.join(_tf.mkdtemp(), "g.txt")
        open(ov_path, "w", encoding="utf-8").write("# my labels\nFolk Singer = singer\n\nIndie Band = nonsense  # not a pool genre\nDeep Rock = indierock\n")
        ov = dd.load_overrides(ov_path)
        assert ov == {"folk singer": "singer", "indie band": "nonsense", "deep rock": "indierock"}, ov
        p4, why4, used4 = dd.choose(dd.Deezer(cache_path="/nonexistent/x.json"), cand, A, {dd.norm("Already In Pool")}, set(), ov)
        g4 = {c["name"]: c["genre"] for c in p4}
        assert g4["Folk Singer"] == "singer" and g4["Deep Rock"] == "indierock" and "Indie Band" not in g4 and g4["Rock Two"] == "rock", g4        # Deep Rock left the rock quota, so Rock Two takes the free slot
        assert dd.load_overrides("/nonexistent/none.txt") == {}
        dd.Deezer.get = fake_get
        src = dd.to_source(picked[0], 20)
        assert src["kind"] == "artist" and src["more"] == 20 and len(src["tracks"]) == 3 and src["tracks"][0]["seconds"] == 200.0
        print("   fans / albums / genre / pool / quota filters, depth-2 crawl and vote order behave; Asian Music is split by writing")
    finally:
        dd.Deezer.get, dd.Deezer.save = _get, _save


def seen_songs_test():
    """Round 2 leaves out songs already recommended to the same friend (any list), without touching other friends or the genre pick."""
    print("\n11. SONGS ALREADY RECOMMENDED ARE LEFT OUT")
    import blind_test as bt, tag_ai, json, tempfile, os
    # (a) the snapshot: only THIS friend's captures, all three lists
    d = tempfile.mkdtemp()
    def cap(name, friend, A, B, C):
        json.dump(dict(friend=friend, A=[dict(key=k) for k in A], B=[dict(key=k) for k in B], C=[dict(key=k) for k in C]),
                  open(os.path.join(d, name), "w"))
    cap("1.json", "Felicia", ["youtube_1"], ["youtube_2"], ["youtube_3"])
    cap("2.json", "Isaac", ["youtube_9"], [], [])
    open(os.path.join(d, "bad.json"), "w").write("{not json")
    assert bt.previously_recommended("Felicia", d) == {"youtube_1", "youtube_2", "youtube_3"}
    assert bt.previously_recommended("Nobody", d) == set()
    _b = bt.BLIND
    try:
        bt.BLIND = d + "_preview"                                      # a preview run: BLIND is elsewhere, the real captures still count
        real = os.path.join(bt.RES, "blind")
        assert bt.previously_recommended("Felicia", d) == {"youtube_1", "youtube_2", "youtube_3"}
        assert bt.previously_recommended("Felicia") == bt.previously_recommended("Felicia", real)     # default = results/blind
    finally:
        bt.BLIND = _b
    # (b) make_lists with a synthetic pool: the excluded songs appear in no list, and the lists are still full
    rng = np.random.default_rng(0)
    n = 300
    P = dict(key=[f"youtube_{i}" for i in range(n)], source=["youtube"] * n, artist=[f"art{i}" for i in range(n)],
             artist_name=[f"Artist {i}" for i in range(n)], group=["yt_pop"] * n, title=[f"Song {i}" for i in range(n)],
             link=[f"https://x/{i}" for i in range(n)], listens=rng.integers(100, 1_000_000, n).astype(float),
             whole=rng.normal(size=(n, 16)), parts=rng.normal(size=(n, 3, 16)), va_vg=rng.normal(size=(n, 2)), va_mc=rng.normal(size=(n, 2)),
             inst=rng.random((n, 40)), bpm=rng.uniform(70, 160, n), confidence=rng.random(n), steadiness=rng.random(n), busyness=rng.random(n))
    P["from"] = "synthetic"
    for k in ("whole", "parts", "va_vg", "va_mc", "inst", "bpm", "confidence", "steadiness", "busyness", "listens"):
        P[k] = np.asarray(P[k], float)
    _load, _pool, _win = tag_ai.load_tags, bt._pool, bt.window_sound
    try:
        tag_ai.load_tags = lambda: {}
        P = bt.apply_quality(P)
        bt._attach_parts(P)
        P["scale"] = None; P["whole_z"] = P["whole"]; P["parts_z"] = P["parts"]
        bt._pool = bt._finish(P)
        bt.window_sound = lambda q, P, scaled=True: None
        j = 10
        q = dict(whole=P["whole"][j] + 0.3 * rng.normal(size=16), va_vg=P["va_vg"][j], va_mc=P["va_mc"][j], inst=P["inst"][j],
                 bpm=P["bpm"][j], confidence=P["confidence"][j], steadiness=P["steadiness"][j], busyness=P["busyness"][j])
        first = bt.make_lists(q, "mood+rhythm", seed=1)
        shown = {s["key"] for L in "ABCD" for s in first[L]}
        second = bt.make_lists(q, "mood+rhythm", seed=1, exclude=shown)
        again = {s["key"] for L in "ABCD" for s in second[L]}
        assert shown and not (shown & again), shown & again
        assert all(len(second[L]) == bt.K for L in "ABC") and second["excluded_as_seen"] == len(shown)
        assert second["genre_group"] == first["genre_group"]                    # the genre pick ignores the exclusion
        assert bt.make_lists(q, "mood+rhythm", seed=1)["excluded_as_seen"] == 0   # no exclude = nothing left out
    finally:
        tag_ai.load_tags, bt._pool, bt.window_sound = _load, _pool, _win
    print("   the snapshot reads one friend's earlier lists; excluded songs appear in no list; lists stay full; the genre pick is unchanged")


def youtube_scale_test():
    """The Sound scale can be fitted on YouTube songs only (round 2), without changing the default all-site fit that evaluate.py uses."""
    print("\n12. SOUND SCALE FITTED ON THE YOUTUBE POOL")
    import match, results_index, tempfile, os
    rng = np.random.default_rng(1)
    d = tempfile.mkdtemp()
    rows, X = {}, {"youtube": [], "fma": []}
    for site, shift in (("youtube", 0.0), ("fma", 5.0)):                 # the two sites sit in different places on purpose
        for i in range(6):
            v = rng.normal(size=8) + shift
            X[site].append(v); k = f"{site}_{i}"
            np.savez(os.path.join(d, k + ".npz"), effnet_whole=v); rows[k] = dict(status="done")
    saved = (match.RES, match.latest_rows, match.MIN_SCALE_SONGS, results_index.pool_keys, dict(match._scale), match._scale_sources, match._lib, match._win)
    try:
        match.RES, match.latest_rows, match.MIN_SCALE_SONGS = d, (lambda r: rows), 2
        results_index.pool_keys = lambda *a, **k: set(rows)
        match._scale.clear(); match._scale_sources = None
        mu_all = match.sound_scale()[0]
        assert np.allclose(mu_all, np.mean(X["youtube"] + X["fma"], axis=0)) and os.path.exists(os.path.join(d, "sound_scale.npz"))
        match._lib = match._win = "stale"
        match.use_scale_sources(("youtube",))
        assert match._lib is None and match._win is None                  # rescaled vectors are rebuilt with the new scale
        mu_yt = match.sound_scale()[0]
        assert np.allclose(mu_yt, np.mean(X["youtube"], axis=0)) and not np.allclose(mu_yt, mu_all)
        assert os.path.exists(os.path.join(d, "sound_scale_youtube.npz"))
        match.use_scale_sources(("all",))                                  # "all" = the old default again
        assert np.allclose(match.sound_scale()[0], mu_all)
    finally:
        match.RES, match.latest_rows, match.MIN_SCALE_SONGS, results_index.pool_keys = saved[:4]
        match._scale.clear(); match._scale.update(saved[4]); match._scale_sources, match._lib, match._win = saved[5:]
    print("   YouTube-only fit differs from the all-site fit, has its own cache file, resets the rescaled library, and 'all' restores the default")


def clustered_range_test():
    """The friend-test ranges resample friends (ratings of one friend are not independent) and need at least 3 friends."""
    print("\n13. FRIEND-TEST RANGES RESAMPLE FRIENDS")
    import blind_test as bt
    # (a) fewer than 3 friends: no honest range
    two = {"F1": [1.0, 0.0, 1.0], "F2": [0.0, 0.0, 1.0]}
    assert all(np.isnan(x) for x in bt._boot_clustered(two))
    # (b) friends who differ a lot give a wide range even with many ratings each; identical friends give a narrow one
    rng = np.random.default_rng(0)
    split = {f"F{i}": list((rng.random(60) < p).astype(float)) for i, p in enumerate([0.05, 0.95, 0.1, 0.9])}     # 240 ratings, 4 very different friends
    alike = {f"F{i}": list((rng.random(60) < 0.5).astype(float)) for i in range(4)}
    lo1, hi1 = bt._boot_clustered(split); lo2, hi2 = bt._boot_clustered(alike)
    pooled = np.concatenate(list(split.values()))
    r = np.random.default_rng(0)
    old = np.percentile([r.choice(pooled, len(pooled)).mean() for _ in range(2000)], [2.5, 97.5])    # the old, row-level range
    assert (hi1 - lo1) > 3 * (old[1] - old[0]), (hi1 - lo1, old[1] - old[0])       # the old range was far too narrow here
    assert (hi2 - lo2) < (hi1 - lo1)
    # (c) differences: a clear gap between lists is found (range above 0); no gap gives a range that includes 0; friends are paired
    A = {f"F{i}": [1.0, 1.0, 1.0, 0.0] * 3 for i in range(5)}          # 75% would add
    C = {f"F{i}": [0.0, 0.0, 1.0, 0.0] * 3 for i in range(5)}          # 25%
    d, lo, hi = bt._boot_diff(A, C)
    assert abs(d - 0.5) < 1e-9 and lo > 0.3 and hi <= 0.7, (d, lo, hi)
    d0, lo0, hi0 = bt._boot_diff(A, A)
    assert d0 == 0 and lo0 <= 0 <= hi0
    d2, lo2_, hi2_ = bt._boot_diff({"F1": [1.0]}, {"F1": [0.0]})                   # one friend: a difference but no range
    assert d2 == 1.0 and np.isnan(lo2_) and np.isnan(hi2_)
    assert all(np.isnan(x) for x in bt._boot_diff({"F1": [1.0]}, {"F2": [0.0]}))    # nobody rated both lists
    print("   too-narrow row-level ranges are gone; <3 friends gives no range; list differences are paired by friend")


def list_d_and_rule_test():
    """List D (most-viewed songs of the same style) and the pre-set success verdict."""
    print("\n14. LIST D AND THE PRE-SET SUCCESS RULE")
    import blind_test as bt, io, contextlib
    # (a) list D: most viewed first, one per artist, only the closest match's style, blocked songs never, wider genre when the style is tiny
    n = 40
    P = dict(key=[f"youtube_{i}" for i in range(n)], group=["yt_indiepop"] * 20 + ["yt_kpop"] * 15 + ["yt_rnb"] * 5,
             listens=np.array([float(i * 100) for i in range(n)]))
    artists = np.array([f"art{i // 2}" for i in range(n)])                      # two songs per artist
    blocked = np.zeros(n, bool); blocked[19] = True                             # the most-viewed indiepop song is blocked (e.g. a copy)
    d = bt.most_viewed_same_style(P, 0, blocked, artists)
    assert d == [18, 17, 15], d                                                  # 19 blocked; 18 (art9), 17 (art8; 16 shares its artist), 15 (art7); all indiepop
    assert all(P["group"][i] == "yt_indiepop" for i in d)
    tiny = dict(key=["a", "b", "c", "d"], group=["yt_kpop", "yt_pop", "yt_pop", "yt_cpop"], listens=np.array([5.0, 40.0, 30.0, 20.0]))
    assert bt.most_viewed_same_style(tiny, 0, np.zeros(4, bool), np.array(["w", "x", "y", "z"])) == [1, 2, 3]    # style too small: the genre "pop" is used
    # (b) the verdict
    def run(rows):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bt.rule_verdict(rows)
        return buf.getvalue()
    def rows_for(friends, p):                                                    # p = chance of "would add" per list
        rng = np.random.default_rng(5); out = []
        for f in friends:
            for L, pr in p.items():
                for _ in range(10):
                    out.append(dict(friend=f, lists=L, add=float(rng.random() < pr), heard=None, rating=None, liked="mood", ai="none", said_ai=False))
        return out
    five = ["F1", "F2", "F3", "F4", "F5"]
    txt = run(rows_for(five, {"A": 0.8, "B": 0.8, "C": 0.2, "D": 0.5}))
    assert "SUPPORTED" in txt.split("H1")[1].split("H2")[0] and "SUPPORTED" in txt.split("H2")[1].split("H3")[0], txt     # A beats C and D
    assert "NOT CLEAR" in txt.split("H3")[1], txt                                                                       # B equals A
    assert "CONTRADICTED" in run(rows_for(five, {"A": 0.1, "B": 0.1, "C": 0.9, "D": 0.5})).split("H1")[1].split("H2")[0]
    assert "CANNOT JUDGE" in run(rows_for(["F1", "F2"], {"A": 0.8, "B": 0.8, "C": 0.2, "D": 0.5}))                       # only 2 friends
    # a real but small gap (+5 points) is not enough, however clear
    small = run(rows_for(five, {"A": 0.55, "B": 0.5, "C": 0.5, "D": 0.5}))
    assert "SUPPORTED" not in small.split("H1")[1].split("H2")[0], small
    print("   D = most viewed of the same style (one per artist, copies blocked); the verdict says SUPPORTED, CONTRADICTED, NOT CLEAR or CANNOT JUDGE as the rule says")


def pool_duplicates_test():
    """pool_duplicates.py: same-recording uploads are grouped (most-viewed kept), sound-alike songs with other titles are only listed, nothing else is touched."""
    print("\n15. DUPLICATE UPLOADS IN THE POOL")
    import pool_duplicates as pdp, tempfile, os, csv
    rng = np.random.default_rng(4)
    base, other = rng.normal(size=64), rng.normal(size=64)
    whole = np.stack([base, base + 0.01 * rng.normal(size=64), base + 0.01 * rng.normal(size=64), other, other + 0.01 * rng.normal(size=64)]
                     + [rng.normal(size=64) for _ in range(3)])
    P = dict(key=[f"youtube_t{i}" for i in range(8)], whole=whole, listens=np.array([100.0, 5000.0, 90000.0, 10.0, 20.0, 7.0, 8.0, 9.0]),
             title=["Hold On", "Hold On (Official Audio)", "Artist - Hold On (Lyrics)", "Other Song", "Totally Different Title", "Aaa", "Bbb", "Ccc"],
             artist=["a", "a", "label", "b", "b", "c", "d", "e"], artist_name=["A", "A", "Label", "B", "B", "C", "D", "E"])
    pairs, clusters = pdp.analyse(P)
    assert len(clusters) == 1, clusters
    c = clusters[0]
    assert c["members"] == [0, 1, 2] and c["keep"] == 1 and sorted(c["drop"]) == [0, 2], c        # the official upload is kept although a lyric re-upload has 90,000 views
    cats = sorted((p["a"], p["b"], p["category"]) for p in pairs)
    assert (3, 4, "check by ear") in cats and (0, 1, "duplicate") in cats and (0, 2, "duplicate") in cats and (1, 2, "duplicate") in cats, cats
    assert not any(p["a"] >= 5 or p["b"] >= 5 for p in pairs)                                         # the unrelated songs are in no pair
    assert pdp.keep_rank("Hold On (Official Audio)", 1) > pdp.keep_rank("Hold On", 999) > pdp.keep_rank("Hold On (Lyrics)", 10 ** 9)
    assert pdp.keep_rank("LEE HI - M/V", 1) > pdp.keep_rank("LEE HI - Lyrics", 5) and pdp.keep_rank("Song - Visualizer", 5) < pdp.keep_rank("Song", 1)
    assert pdp.keep_rank("CHUNG HA - 'I'm Ready' Extended Performance Video (Official)", 10 ** 8) < pdp.keep_rank("I'm Ready", 100)        # a performance cut never beats the plain song
    assert pdp.keep_rank("Song (Live)", 5) < pdp.keep_rank("Song", 1) and pdp.keep_rank("Song (Official Audio)", 1) > pdp.keep_rank("Song (Acoustic)", 10 ** 9)
    assert pdp.title_share("Hold On (Official Audio)", "Artist - Hold On") == 1.0 and pdp.title_share("x", "") == 0.0
    # the artist's own channel beats a curator channel with more views (11 Oct: "Malcolm Todd - Earrings" kept from "Minimal Sounds")
    w2 = np.stack([base, base + 0.01 * rng.normal(size=64), base + 0.01 * rng.normal(size=64)])
    P2 = dict(key=["youtube_x0", "youtube_x1", "youtube_x2"], whole=w2, listens=np.array([900000.0, 1200.0, 50000.0]),
              title=["Malcolm Todd - Earrings", "Malcolm Todd - Earrings", "Earrings (Lyric Video)"],
              artist=["minimal sounds", "malcolm todd", "lyrics co"], artist_name=["Minimal Sounds", "Malcolm Todd", "Lyrics Co"])
    _, cl2 = pdp.analyse(P2)
    assert len(cl2) == 1 and cl2[0]["keep"] == 1 and sorted(cl2[0]["drop"]) == [0, 2], cl2
    assert pdp.own_channel("Aioz - Topic", ["Aioz - 放你走吧"]) and not pdp.own_channel("Minimal Sounds", ["Malcolm Todd - Earrings"]) and not pdp.own_channel("X", ["Song"])
    # different language versions are not copies; a subtitled upload still is
    assert pdp.language_markers("Trap (English Version)") == {"english"} and pdp.language_markers("Henry Trap Chinese ver MV English subs") == {"chinese"}
    assert pdp.language_markers("Hold On (English subs)") == set() and pdp.language_markers("No One Noticed (Extended Spanish)") == {"spanish"}
    vA, vB = rng.normal(size=64), rng.normal(size=64)
    P3 = dict(key=[f"youtube_l{i}" for i in range(4)], whole=np.stack([vA, vA + 0.01 * rng.normal(size=64), vB, vB + 0.01 * rng.normal(size=64)]),
              listens=np.array([5.0, 9.0, 5.0, 9.0]), title=["Trap (English Version)", "Trap Chinese ver MV", "Hold On", "Hold On (English subs)"],
              artist=["h", "h", "x", "y"], artist_name=["H", "H", "X", "Y"])
    pr3, cl3 = pdp.analyse(P3)
    cats3 = {(p["a"], p["b"]): p["category"] for p in pr3}
    assert cats3[(0, 1)] == "check by ear" and cats3[(2, 3)] == "duplicate" and len(cl3) == 1 and cl3[0]["members"] == [2, 3], (cats3, cl3)
    # marking: only the dropped copies get i_agree = n, the keeper and the sound-alike do not; a log line is written; a .bak copy exists
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["source", "track_id", "title", "artist", "i_agree"])
        for i in range(8):
            w.writerow(["youtube", f"t{i}", P["title"][i], P["artist_name"][i], ""])
    log = os.path.join(d, "audit.csv")
    assert pdp.apply_marks(P, clusters, here=d, log=log) == 2
    rows = list(csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig")))
    assert [r["track_id"] for r in rows if r["i_agree"] == "n"] == ["t0", "t2"] and os.path.exists(os.path.join(d, "pool_youtube.csv.bak"))
    assert "duplicate upload of youtube_t1" in open(log, encoding="utf-8-sig").read()
    assert pdp.apply_marks(P, clusters, here=d, log=log) == 0                                          # a second run changes nothing
    # the sheet check: two copies on the SAME friend's sheets are reported (titles only), another friend's single copy is not
    kc = os.path.join(d, "key.csv")
    with open(kc, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["item", "friend", "key", "lists"])
        for fr, k in (("Isaac", "youtube_t0"), ("Isaac", "youtube_t1"), ("Felicia", "youtube_t2"), ("Felicia", "youtube_t5")):
            w.writerow([f"{fr}-1", fr, k, "A"])
    tw = pdp.sheet_twins(P, clusters, kc)
    assert tw == {"Isaac": [("Hold On", "Hold On (Official Audio)")]}, tw
    print("   a triple upload is grouped and the most-viewed copy kept; sound-alikes with other titles are only listed; marking is idempotent; the sheet check shows titles only")


def ai_tag_check_test():
    """ai_tag_check.py: stratified blind sample, answers read back per group, estimates scaled to the pool, pass marks."""
    print("\n16. AI-TAGGER CHECK")
    import ai_tag_check as ai, tempfile, os, csv, io, contextlib
    frame, n = [], 0
    for status, views, count in (("confirmed", 500, 20), ("confirmed", 50000, 10), ("likely", 300, 120), ("likely", 40000, 30),
                                 ("none", 800, 250), ("none", 90000, 140)):
        for _ in range(count):
            frame.append(dict(key=f"youtube_{n}", title=f"t{n}", channel=f"c{n}", link=f"https://y/{n}", status=status, views=float(views))); n += 1
    s1, pops = ai.draw_sample(frame, seed=3); s2, _ = ai.draw_sample(frame, seed=3)
    assert [r["key"] for r in s1] == [r["key"] for r in s2] and len(s1) == 100 and len({r["key"] for r in s1}) == 100      # reproducible, no repeats
    assert pops == {"C": 30, "LL": 120, "LH": 30, "NL": 250, "NH": 140}, pops
    got = {g: sum(r["group"] == g for r in s1) for g in ai.SIZES}
    assert got == ai.SIZES, got
    assert [r["group"] for r in s1] != sorted(r["group"] for r in s1)                                                         # shuffled
    tiny, _ = ai.draw_sample(frame[:5], seed=1); assert len(tiny) == 5                                                        # a short group is taken whole
    d = tempfile.mkdtemp(); sheet, key = os.path.join(d, "sheet.csv"), os.path.join(d, "key.csv")
    m, _ = ai.make(frame, sheet, key, seed=3)
    text = open(sheet, encoding="utf-8-sig").read()
    assert m == 100 and "confirmed" not in text and "likely" not in text and "none" not in text.split("\n", 1)[1]            # the sheet does not reveal the tags
    # a rater: 12 of 12 confirmed AI; likely-low 14 of 20; likely-high 9 of 10; untagged-low 3 yes, 1 unsure, 24 no; untagged-high 1 of 30
    plan = {"C": ["y"] * 12, "LL": ["y"] * 14 + ["n"] * 6, "LH": ["y"] * 9 + ["n"], "NL": ["y"] * 3 + ["u"] + ["n"] * 24, "NH": ["y"] + ["n"] * 29}
    rows = list(csv.DictReader(open(key, encoding="utf-8"))); filled = os.path.join(d, "filled.csv"); used = {g: 0 for g in plan}
    with open(filled, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["item", "ai? (y / n / unsure)"])
        for r in rows:
            w.writerow([r["item"], plan[r["group"]][used[r["group"]]]]); used[r["group"]] += 1
    counts, p2 = ai.read_answers([filled], key)
    assert counts == {"C": [12, 0, 0], "LL": [14, 6, 0], "LH": [9, 1, 0], "NL": [3, 24, 1], "NH": [1, 29, 0]} and p2["LL"] == 120 and p2["C_under_10k"] == 20
    point, rng_ = ai.estimates(counts, p2)
    likely = (120 * 0.7 + 30 * 0.9) / 150; untagged = (250 * (3 / 27) + 140 * (1 / 30)) / 390
    assert abs(point["likely"] - likely) < 1e-9 and abs(point["untagged"] - untagged) < 1e-9 and point["confirmed"] == 1.0
    assert abs(point["wrongly_dropped"] - (20 * 0 + 120 * 0.3)) < 1e-9                                                       # 30% of the 120 dropped 'likely' songs are real
    assert rng_["likely"][0] < point["likely"] < rng_["likely"][1]
    v = ai.verdict(point)
    assert v == {"likely": "PASS", "confirmed": "PASS", "untagged": "PASS"}, (v, point)                                       # 0.74 >= 0.70, 1.0 >= 0.90, 0.083 <= 0.10
    worse = dict(counts, NL=[10, 17, 1], LL=[8, 12, 0])                                                                       # many missed AI songs, many false alarms
    assert ai.verdict(ai.estimates(worse, p2)[0]) == {"likely": "FAIL", "confirmed": "PASS", "untagged": "FAIL"}
    assert ai.verdict(ai.estimates(dict(counts, C=[0, 0, 0]), p2)[0])["confirmed"] == "unknown"                              # nothing answered in a group: no verdict
    lo, hi = ai.wilson(7, 10); assert abs(lo - 0.397) < 0.002 and abs(hi - 0.892) < 0.002 and all(np.isnan(ai.wilson(0, 0)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai.score([filled], key)
    out = buf.getvalue()
    assert "100 songs answered, 1 of them 'unsure'" in out and "PASS" in out and "If every 'unsure' were AI" in out, out
    print("   stratified blind sample (tags never shown), answers read back per group, estimates scaled to the pool, marks give PASS or FAIL")


def replace_songs_test():
    """replace_songs.py: 'replace with <link>' comments become pool replacements; the old song is marked n, the new one joins the same list and style."""
    print("\n17. REPLACING SONGS BY AN OFFICIAL UPLOAD")
    import replace_songs as rs, tempfile, os, csv
    d = tempfile.mkdtemp()
    sheet = os.path.join(d, "sheet.csv")
    rows = [("ai-012", "https://www.youtube.com/watch?v=TcPwpEHcKLA", "Henry Lau live TRAP", "replace song with https://www.youtube.com/watch?v=mshfI4IzcII"),
            ("ai-017", "https://www.youtube.com/watch?v=AWBO0VF08v8", "Honey, There's No Time", "replace song with https://www.youtube.com/watch?v=UsqYXbHYkEI"),
            ("ai-042", "https://www.youtube.com/watch?v=qv5eFIjvR-A", "me without you", "replace with https://youtu.be/nHZdYsXYOhA?t=3"),
            ("ai-050", "https://www.youtube.com/watch?v=aaaaaaaaaaa", "no comment here", ""),
            ("ai-051", "https://www.youtube.com/watch?v=bbbbbbbbbbb", "a note, not a replacement", "sounds like a real band"),
            ("ai-052", "https://www.youtube.com/watch?v=ccccccccccc", "replace but no link", "replace this one"),
            ("ai-053", "https://www.youtube.com/watch?v=ddddddddddd", "same video", "replace with https://www.youtube.com/watch?v=ddddddddddd")]
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["item", "listen_here", "title", "channel", "ai? (y / n / unsure)", rs.COMMENT_COL])
        for item, link, title, c in rows:
            w.writerow([item, link, title, "ch", "", c])
    pairs, problems = rs.pairs_from_sheet(sheet)
    assert pairs == [("ai-012", "TcPwpEHcKLA", "mshfI4IzcII", "Henry Lau live TRAP"), ("ai-017", "AWBO0VF08v8", "UsqYXbHYkEI", "Honey, There's No Time"),
                     ("ai-042", "qv5eFIjvR-A", "nHZdYsXYOhA", "me without you")], pairs
    assert len(problems) == 2 and any("no YouTube link" in p for p in problems) and any("same video" in p for p in problems), problems
    # a pool list with the three old songs (one already marked n elsewhere is not needed); the plan and the apply
    cols = ["source", "track_id", "title", "artist", "duration", "listens", "licence", "listen", "site_genre", "group", "i_agree"]
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cols)
        w.writerow(["youtube", "TcPwpEHcKLA", "Henry Lau live TRAP", "Aaron", 200, 900, "youtube-standard", "u", "khiphop", "yt_khiphop", ""])
        w.writerow(["youtube", "AWBO0VF08v8", "Honey, There's No Time", "Strange girl The", 180, 40, "youtube-standard", "u", "indierock", "yt_indierock", ""])
        w.writerow(["youtube", "qv5eFIjvR-A", "me without you", "tatata_ash", 170, 12, "youtube-standard", "u", "indiepop", "yt_indiepop", ""])
        w.writerow(["youtube", "UsqYXbHYkEI", "Honey, There's No Time (official)", "Feng Suave", 180, 5000, "youtube-standard", "u", "indierock", "yt_indierock", ""])   # new video ALREADY in the pool
    lists = rs.load_lists(d)
    details = {"mshfI4IzcII": dict(title="Henry Lau - TRAP", channel="Henry Lau - Topic", duration=210, views=3_000_000, licence="youtube-standard"),
               "UsqYXbHYkEI": dict(title="x", channel="Feng Suave", duration=180, views=5000, licence="youtube-standard"),
               "nHZdYsXYOhA": dict(title="me without you", channel="Official Artist", duration=175, views=80_000, licence="youtube-standard")}
    acts = rs.plan(pairs, lists, details)
    assert [x["new_already"] for x in acts] == [False, True, False] and all(x["list"] == "pool_youtube.csv" for x in acts)
    assert acts[0]["row"]["group"] == "yt_khiphop" and acts[2]["row"]["group"] == "yt_indiepop" and acts[0]["row"]["artist"] == "Henry Lau"   # '- Topic' removed, style kept
    log = os.path.join(d, "audit.csv")
    assert rs.apply_plan(acts, lists, d, log) == (3, 2)                                                                  # 3 old songs marked, 2 new added (one was already there)
    out = list(csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig")))
    assert sorted(r["track_id"] for r in out if r["i_agree"] == "n") == ["AWBO0VF08v8", "TcPwpEHcKLA", "qv5eFIjvR-A"]
    assert [r["track_id"] for r in out].count("UsqYXbHYkEI") == 1 and {"mshfI4IzcII", "nHZdYsXYOhA"} <= {r["track_id"] for r in out}
    assert os.path.exists(os.path.join(d, "pool_youtube.csv.bak")) and "replaced by official upload youtube_mshfI4IzcII" in open(log, encoding="utf-8-sig").read()
    lists2 = rs.load_lists(d)                                                                                              # a second run changes nothing
    assert rs.apply_plan(rs.plan(pairs, lists2, details), lists2, d, log) == (0, 0)
    assert rs.video_id("https://youtu.be/mshfI4IzcII?t=3") == "mshfI4IzcII" and rs.video_id("no link") is None
    print("   the three 'replace' comments become replacements, notes and bad rows are reported, the old song is marked n, the new one keeps its style, a second run changes nothing")


def official_versions_test():
    """find_official_versions.py: spots covers and fan lyric videos, guesses the original artist, picks the artist's own upload, and feeds replace_songs."""
    print("\n18. COVERS AND FAN LYRIC VIDEOS -> THE ORIGINAL UPLOAD")
    import sys, types, tempfile, os, csv
    sys.modules.setdefault("yt_dlp", types.ModuleType("yt_dlp"))                         # only the checking helpers are used, not the downloader
    import find_official_versions as fo, replace_songs as rs
    # (a) what counts as a candidate
    assert fo.kind_of("Faouzia - UNETHICAL (Lyrics)", "Vibe Music") == "fan lyric video"
    assert fo.kind_of("Dead and Gone", "StateChampsLyrics") == "fan lyric video"                                           # the channel says Lyrics
    assert fo.kind_of("Song (Official Lyric Video)", "Artist") is None and fo.kind_of("Faouzia - UNETHICAL (Official Video)", "Faouzia") is None
    assert fo.kind_of("Best Friend (cover by Sam)", "Sam") == "cover" and fo.kind_of("Hold On - Karaoke Version", "x") == "cover"
    assert fo.kind_of("Hold On", "Some Band") is None and fo.kind_of("\u3010\u52d5\u614b\u6b4c\u8a5e\u3011No Reason", "Boba Beats") == "fan lyric video"
    # (b) guessing artist and song
    assert fo.candidate_pairs("Faouzia - UNETHICAL (Lyrics)", "Vibe Music", "Vibe Music") == [("Faouzia", "UNETHICAL")]
    assert fo.candidate_pairs("\u201cKissing Other People\u201d // Lyrics", "Lennon Stella", "SomeLyrics") == [("Lennon Stella", "Kissing Other People")]
    assert fo.candidate_pairs("Earrings (Lyrics)", "Vibe Music", "Vibe Music") == []                                      # the pool artist is just the uploader: no guess
    # (c) finding the official upload among the search results
    old = dict(key="youtube_OLDOLDOLD11", kind="fan lyric video", title="Faouzia - UNETHICAL (Lyrics)", channel="Vibe Music", pool_artist="Vibe Music",
               views="900", duration="200", link="https://www.youtube.com/watch?v=OLDOLDOLD11")
    entries = [dict(id="OLDOLDOLD11", title="Faouzia - UNETHICAL (Lyrics)", channel="Vibe Music", duration=200, view_count=9_000_000),
               dict(id="LYRICFAN111", title="UNETHICAL lyric video Faouzia", channel="Fan", duration=200, view_count=5),
               dict(id="COVERCOVER1", title="UNETHICAL Faouzia (cover)", channel="Sam", duration=200, view_count=500),
               dict(id="WRONGLEN111", title="Faouzia - UNETHICAL (Official Video)", channel="Faouzia", duration=420, view_count=10),
               dict(id="TOPICTOPIC1", title="UNETHICAL", channel="Faouzia - Topic", duration=201, view_count=70_000),
               dict(id="OFFICIAL111", title="Faouzia - UNETHICAL (Official Video)", channel="Faouzia", duration=203, view_count=40_000_000)]
    g = fo.find_official(old, lambda q, n: entries)
    assert g["entry"]["id"] == "OFFICIAL111" and g["official"] and g["artist"] == "Faouzia", g                           # official channel first; old, lyric, cover and wrong-length results skipped
    assert fo.find_official(old, lambda q, n: entries[:4]) is None                                                         # nothing acceptable left
    cov = dict(old, key="youtube_COVCOV11111", kind="cover", title="Best Friend cover", channel="Sam", pool_artist="Sam", duration="")
    ent2 = [dict(id="ROCROCROC11", title="Best Friend (Official Audio)", channel="Rex Orange County", duration=180, view_count=9)]
    assert fo.find_official(cov, lambda q, n: ent2) is None                                                                # a cover with no artist in the title needs --deezer
    g2 = fo.find_official(cov, lambda q, n: ent2, lambda q: ("Rex Orange County", "Best Friend", 180.0))
    assert g2["entry"]["id"] == "ROCROCROC11" and "Deezer" in g2["note"]
    assert fo.deezer_original("Best Friend", get=lambda q: {"data": [dict(title="Other", title_short="Other", artist=dict(name="X"), duration=1),
                              dict(title="Best Friend", title_short="Best Friend", artist=dict(name="Rex Orange County"), duration=180)]}) == ("Rex Orange County", "Best Friend", 180.0)
    # a 'Song - Artist' title: the official channel is the SECOND part; it must still be recognised and ranked first
    rev = dict(old, key="youtube_REVREVREV11", kind="fan lyric video", title="TAO LANG - LOONIE (Lyrics)", channel="Fan", pool_artist="Fan", duration="200")
    ent3 = [dict(id="FANFANFAN111", title="LOONIE - TAO LANG (Lyrics)", channel="Another Fan", duration=200, view_count=99_000_000),
            dict(id="LOONIEOFF11", title="LOONIE - TAO LANG (Official Music Video)", channel="LOONIE", duration=201, view_count=1_000_000)]
    g3 = fo.find_official(rev, lambda q, n: ent3)
    assert g3["entry"]["id"] == "LOONIEOFF11" and g3["official"] and "check the artist" in g3["note"], g3
    # the 18 real proposals of 11 Oct: an artist's OWN visualizer / lyric video is the original (never a candidate); fan re-uploads still are
    ic = fo.is_candidate
    assert ic("Jastin Martin - Want This To Happen (Visualizer)", "JastinMartinVEVO", "Jastin Martin") is None
    assert ic("Alessi Rose - Skin (Visualizer)", "AlessiRoseVEVO", "Alessi Rose") is None and ic("Lyle Kam - all we do is talk (lyric visualizer)", "Lyle Kam", "Lyle Kam") is None
    assert ic("\ub9ac\ub3c4\uc5b4 (Redoor)  - Feathers (Visualizer)", "Redoor \ub9ac\ub3c4\uc5b4", "\ub9ac\ub3c4\uc5b4") is None
    assert ic('Omichle - "Blur" (Lyrics Video) | K-indie Bedroom Pop', "Omichle (\uc624\ubbf8\ud074)", "Omichle") is None
    assert ic("joon - by my side (ft. bixby) [lyrics]", "Biteki \u3073\u3066\u304d", "joon") == "fan lyric video"
    assert ic("SRA - You (Lyrics)", "Monday Vibes", "SRA") == "fan lyric video" and ic("Dead and Gone (Lyrics)", "StateChampsLyrics", "State Champs") == "fan lyric video"
    assert ic("Rol3ert frozen - acoustic piano version-", "Rol3ert", "Rol3ert") == "cover"                     # an own-channel COVER is still a cover
    assert ic("Earrings (Lyrics)", "Vibe Music", "Vibe Music") == "fan lyric video"                                 # pool artist = uploader: no exemption
    assert fo.candidate_pairs("Vietsub | B.O.T.A. (Baddest Of Them All) - Eliza Rose & Interplanetary Criminal | Lyrics Video", "Vietsub", "Vietsub M\u1ed7i Ng\u00e0y") \
        == [("B.O.T.A.", "Eliza Rose & Interplanetary Criminal")]
    assert fo.channel_matches("Aioz - Topic", "Aioz") and fo.channel_matches("Eliza Rose", "B.O.T.A.", "Eliza Rose & Interplanetary Criminal") and not fo.channel_matches("MrMoMMusic", "A Little Sound")
    # a live / session / translated / dated fan recording is never proposed, even from a channel that matches
    eliza = dict(old, key="youtube_ELIZAVIET11", title="Vietsub | B.O.T.A. (Baddest Of Them All) - Eliza Rose & Interplanetary Criminal | Lyrics Video", channel="Vietsub M\u1ed7i Ng\u00e0y",
                 pool_artist="Vietsub", duration="227")
    ent4 = [dict(id="LIVELIVELIV", title="Eliza Rose - B.O.T.A. Hamburg, 20.05.2025", channel="Msauerland", duration=225, view_count=26),
            dict(id="SESSIONSESS", title="Eliza Rose & Interplanetary Criminal - B.O.T.A. | Bedroom Session", channel="Eliza Rose", duration=225, view_count=70_000),
            dict(id="TRANSLATED1", title="Eliza Rose & Interplanetary Criminal - B.O.T.A. [Traducci\u00f3n al Espa\u00f1ol]", channel="MOI", duration=227, view_count=1),
            dict(id="ELIZAOFFICI", title="Eliza Rose & Interplanetary Criminal - B.O.T.A. (Baddest Of Them All) [Official Video]", channel="Eliza Rose", duration=227, view_count=54_745_994)]
    g4 = fo.find_official(eliza, lambda q, n: ent4)
    assert g4["entry"]["id"] == "ELIZAOFFICI" and g4["official"], g4
    # the 40 unresolved of 11 Oct: a cut-down fan upload must still find the official one; "Song by Artist"; junk words; titles with no artist at all
    zyko = dict(old, key="youtube_ZYKOZYKO111", title="Ordinary \u2013 Alex Warren (Lyrics) | Warm Vocal Performance", channel="ZYKO MUSIC", pool_artist="ZYKO MUSIC", duration="151")
    off = dict(id="ALEXOFFIC11", title="Alex Warren - Ordinary (Official Video)", channel="Alex Warren", duration=186, view_count=90_000_000)
    other = dict(id="OTHERFAN111", title="Alex Warren - Ordinary", channel="Some Fan", duration=186, view_count=5)
    g5 = fo.find_official(zyko, lambda q, n: [other, off])
    assert g5["entry"]["id"] == "ALEXOFFIC11" and g5["official"], g5                                         # 151 s vs 186 s: fine from the artist's own channel
    assert fo.find_official(zyko, lambda q, n: [other]) is None                                              # but not from an unrelated channel
    assert fo.length_ok(151, 186, True) and not fo.length_ok(151, 186, False) and fo.length_ok(200, 210, False) and not fo.length_ok(200, 700, True)
    assert fo.candidate_pairs("Pirate Radio* by Jean Dawson Lyric Music Video", "Derek T", "Derek T") == [("Jean Dawson", "Pirate Radio")]
    assert fo.candidate_pairs("F**k Being A Princess (lyrics) by Esme Rose. #Esme Rose", "Rise and Shine", "Rise and Shine")[0][0] == "Esme Rose"
    assert fo.candidate_pairs("awr (\u9646\u6770) - Bo Li (\u73bb\u7483) (R&B) Lyrics \u6b4c\u8bcd Pinyin/English Translation", "M - Lyrics", "M - Lyrics") == [("awr", "Bo Li")]
    kay = dict(old, key="youtube_KAYKAYKAY11", title="\u8b1d\u5b89\u742a Kay Tse \u56cd\u5e16\u8857 Wedding Invitation Street [\u7cb5\u62fc | Jyutping | HK Cantonese Song", channel="Lyrics Chan",
               pool_artist="Lyrics Chan", duration="210")
    assert fo.candidate_pairs(kay["title"], kay["pool_artist"], kay["channel"]) == []
    ent5 = [dict(id="KAYOTHER111", title="\u56cd\u5e16\u8857", channel="Other Singer", duration=212, view_count=9),
            dict(id="KAYOFFICIAL", title="\u56cd\u5e16\u8857", channel="\u8b1d\u5b89\u742a Kay Tse Official", duration=213, view_count=1_000_000)]
    log = []
    g6 = fo.find_official(kay, lambda q, n: ent5, explain=log)
    assert g6["entry"]["id"] == "KAYOFFICIAL" and g6["fallback"] and "check it" in g6["note"], g6                 # found through the channel name in the old title
    assert [w for _, e, w in log if e["id"] == "KAYOTHER111"] == ["the channel name is not in the old title"] and [w for _, e, w in log if e["id"] == "KAYOFFICIAL"] == [None]
    log2 = []
    fo.find_official(old, lambda q, n: [dict(id="X", title="Faouzia - UNETHICAL (Official Video)", channel="Faouzia", duration=420, view_count=1)], explain=log2)
    assert log2[0][2] == "length 420 s against the old 200 s" or "length" in log2[0][2], log2
    fo.write_proposals(os.path.join(tempfile.mkdtemp(), "q.csv"), [kay], [(kay, g6)])                              # a fallback match is never pre-approved
    # (d) the review file and replace_songs: only approve = y rows are used; fan lyric videos from an official channel come pre-approved, covers do not
    d = tempfile.mkdtemp(); path = os.path.join(d, "p.csv")
    fo.write_proposals(path, [old, cov], [(old, g), (cov, g2)])
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert [r["approve"] for r in rows] == ["y", ""] and rows[0]["new_link"].endswith("OFFICIAL111") and rows[0]["official_channel"] == "yes"
    pairs, problems = rs.pairs_from_proposals(path)
    assert pairs == [("youtube_OLDOLDOLD11", "OLDOLDOLD11", "OFFICIAL111", "Faouzia - UNETHICAL (Lyrics)")] and not problems
    rows[1]["approve"] = "Y"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    assert len(rs.pairs_from_proposals(path)[0]) == 2                                                                      # approving the cover adds it
    # (h) fixes from the 12 Oct --explain blocks: word order of a channel name, the song's other-language name in brackets, a cover's length
    assert fo.channel_in_title("Kay Tse \u8b1d\u5b89\u742a", "\u8b1d\u5b89\u742a Kay Tse \u56cd\u5e16\u8857 Wedding Invitation Street") and not fo.channel_in_title("Movie World", "\u5d50 \u4f60\u7684\u8ecc\u8de1")
    assert fo.bracket_alts("awr - Bo Li (\u73bb\u7483) (R&B) Lyrics (feat. X)") == ["\u73bb\u7483"], fo.bracket_alts("awr - Bo Li (\u73bb\u7483) (R&B) Lyrics (feat. X)")
    e = dict(title="\u73bb\u7483 (R&B\u6c1b\u56f4\u7248)", channel="\u9646\u6770awr - Topic", duration=202)
    assert fo.why_rejected(e, "Bo Li", "awr", 202) == "title does not match the song"
    assert fo.why_rejected(e, "Bo Li", "awr", 202, alts=["\u73bb\u7483"]) is None
    e2 = dict(title="\u8521\u7434 Tsai Chin\u300a\u60c5\u4eba\u7684\u773c\u6dda\u300bOfficial Audio", channel="\u95ca\u601d\u97f3\u6a02 CROS MUSIC", duration=388)
    assert "length" in fo.why_rejected(e2, "\u60c5\u4eba\u7684\u773c\u6dda", "\u8521\u7434", 228)
    assert fo.why_rejected(e2, "\u60c5\u4eba\u7684\u773c\u6dda", "\u8521\u7434", 228, cover=True) is None
    for bad in ("TAEYANG - 'EYES, NOSE, LIPS' STAGE CAM", "SPOTIFY FAN SUBMISSION - Acoustic 'Our Time to Go'", "Song (Acoustic)", "Song - dance practice"):
        assert fo.ALTERED.search(bad), bad
    assert not fo.ALTERED.search("Rex Orange County - Always (Official Video)") and not fo.ALTERED.search("Center Stage - Artist")
    assert not fo.channel_matches("Sonu Nigam - UnOfficial", "Sonu Nigam") and not fo.channel_matches("Ariel Lin Fan Club", "Ariel Lin") and fo.channel_matches("Sonu Nigam - Topic", "Sonu Nigam")
    assert fo.channel_matches("Hikaru Utada", "Utada Hikaru") and not fo.channel_matches("Hikaru Tanaka", "Utada Hikaru")
    assert fo.ALTERED.search("\u8521\u7434 \u60c5\u4eba\u7684\u773c\u6dda HD\u73fe\u5834") and not fo.ALTERED.search("\u8521\u7434 Tsai Chin\u300a\u60c5\u4eba\u7684\u773c\u6dda\u300bOfficial Audio")
    assert fo.length_ok(100, 200, False, cover=True) and not fo.length_ok(100, 200, False) and not fo.length_ok(100, 300, False, cover=True) and not fo.length_ok(100, 20, False, cover=True)
    # (i) review_proposals.py: numbered rows, flags, marking by row number without touching other columns
    import review_proposals as rp, collections
    d = tempfile.mkdtemp(); pf = os.path.join(d, "p.csv")
    cols = ["approve", "kind", "old_key", "old_title", "old_channel", "new_link", "new_title", "new_channel", "new_seconds", "old_seconds", "official_channel"]
    rows = [dict(zip(cols, ["y", "fan lyric video", "youtube_a", "Song (Lyrics)", "Fan", "L1", "Song (Audio)", "Artist", "200", "190", "yes"])),
            dict(zip(cols, ["", "fan lyric video", "youtube_b", "Song (Lyrics)", "Fan2", "L1", "Song (Audio)", "Artist", "200", "100", "yes"])),
            dict(zip(cols, ["", "cover", "youtube_c", "Other (cover)", "Kid", "L3", "Other (Live)", "Someone", "200", "200", "no"]))]
    rp.save(pf, rows, cols)
    back, bc = rp.load(pf)
    cnt = collections.Counter(r["new_link"] for r in back)
    assert rp.flags(back[0], cnt) == ["x2"] and rp.flags(back[1], cnt) == ["len", "x2"] and rp.flags(back[2], cnt) == ["lyr", "chan"], [rp.flags(r, cnt) for r in back]
    assert rp.parse_numbers("1 3-3, 2", 3) == {1, 2, 3}
    for bad in ("0", "4", "x", "3-1"):
        try:
            rp.parse_numbers(bad, 3); raise AssertionError(bad)
        except ValueError:
            pass
    assert rp.apply_marks(back, {2, 3}, {1}) == (2, 1) and [r["approve"] for r in back] == ["", "y", "y"]
    rp.save(pf, back, bc); assert [r["new_link"] for r in rp.load(pf)[0]] == ["L1", "L1", "L3"]
    print("   covers and fan lyric videos are spotted, the original artist's own upload is chosen over re-uploads, covers, wrong lengths and the old video, nothing is approved for a cover unless you do it")


def ai_removal_test():
    """Every AI-tagged song leaves the pool; ai_block.txt takes whole channels; ai_keep.txt wins over both; ai_channels.py previews and writes the block list."""
    print("\n19. REMOVING AI SONGS: TAGS, BLOCKED CHANNELS, KEPT ARTISTS")
    import blind_test as bt, tag_ai, ai_channels as ac, tempfile, os, io, contextlib, csv
    keys = [f"youtube_{c}" for c in "abcdefgh"]
    chan = dict(zip(keys, ["Real Band", "Suno Radio", "Suno Radio", "Suno Radio", "kanegi.", "kanegi.", "Clouds.Rap", "Other"]))
    tags = dict(zip(keys, [("none", "", 500.0), ("confirmed", "", 90000.0), ("likely", "", 20.0), ("none", "", 40.0), ("likely", "", 10.0), ("none", "", 5.0),
                           ("confirmed", "", 3.0), ("likely", "", 50000.0)]))
    def make_P():
        return dict(key=list(keys), source=["youtube"] * 8, link=["l"] * 8, listens=np.arange(8.0), artist_name=[chan[k] for k in keys])
    saved = (tag_ai.load_tags, tag_ai.load_channels, tag_ai.load_name_list, os.environ.get("HG_AI_POLICY"))
    try:
        tag_ai.load_tags, tag_ai.load_channels = (lambda: tags), (lambda res=None: chan)
        lists = {"ai_keep.txt": {"kanegi", "clouds rap"}, "ai_block.txt": {"suno radio"}}
        tag_ai.load_name_list = lambda name, here=None: lists[name]
        os.environ.pop("HG_AI_POLICY", None)
        P = bt.apply_quality(make_P())
        # default policy hide: tagged songs go (b, c, h), the blocked channel's UNTAGGED song d goes too, the kept artists stay (e, f, g) although tagged, a and untagged others stay
        assert P["key"] == ["youtube_a", "youtube_e", "youtube_f", "youtube_g"], P["key"]
        os.environ["HG_AI_POLICY"] = "hide-low"                                                     # the old policy: tagged songs with 10,000+ views stay, the block list still applies
        P2 = bt.apply_quality(make_P())
        assert P2["key"] == ["youtube_a", "youtube_e", "youtube_f", "youtube_g", "youtube_h"], P2["key"]   # b, c, d are on the blocked channel (gone even under hide-low); h has 50,000 views and stays
        lists["ai_block.txt"] = set()
        os.environ["HG_AI_POLICY"] = "hide-low"
        assert "youtube_h" in bt.apply_quality(make_P())["key"]                                       # no block list: a 50,000-view tagged song stays under hide-low
    finally:
        tag_ai.load_tags, tag_ai.load_channels, tag_ai.load_name_list = saved[:3]
        if saved[3] is None:
            os.environ.pop("HG_AI_POLICY", None)
        else:
            os.environ["HG_AI_POLICY"] = saved[3]
    # the channel tool
    d = tempfile.mkdtemp(); sheet = os.path.join(d, "sheet.csv")
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["item", "title", "channel", ac.ANSWER_COL])
        for ch_, a in (("Suno Radio", "y"), ("Suno Radio", "y"), ("kanegi.", "y"), ("Real Band", "n"), ("Mixed Channel", "y"), ("Mixed Channel", "n"), ("Quiet", "u"), ("", "y")):
            w.writerow(["i", "t", ch_, a])
    flags = ac.flagged_channels(sheet)
    assert flags["suno radio"] == dict(name="Suno Radio", y=2, n=0, unsure=0) and flags["mixed channel"]["y"] == 1 and flags["mixed channel"]["n"] == 1 and "" not in flags
    rows = [dict(key=k, site="youtube", title=f"t{k}") for k in keys]
    pool = ac.by_channel(rows, chan, tags)
    assert pool["suno radio"]["tagged"] == 2 and pool["suno radio"]["untagged"] == 1 and pool["suno radio"]["untagged_keys"] == ["youtube_d"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        blocked = ac.preview(flags, pool, {"kanegi"}, {k: (f"title {k}", False) for k in keys})
    out = buf.getvalue()
    assert blocked == ["suno radio", "mixed channel"] or blocked == ["mixed channel", "suno radio"], blocked        # kanegi. is kept: not blocked
    assert "KEPT (ai_keep.txt)" in out and "you also answered n" in out and "1 more songs" in out.replace("would remove 1 more", "1 more songs"), out
    blockfile = os.path.join(d, "ai_block.txt"); open(blockfile, "w").write("# header\nSuno Radio\n")
    assert ac.write_block(["suno radio", "New Channel"], blockfile) == 1 and open(blockfile).read().count("Suno Radio") == 1
    assert ac.write_block(["new channel"], blockfile) == 0
    assert tag_ai.norm_name("Clouds.Rap") == tag_ai.norm_name("clouds rap") == "clouds rap" and tag_ai.norm_name("kanegi.") == "kanegi"
    shown = ac.suggest(pool, {"kanegi"}, min_songs=3, min_share=0.5)
    assert shown == [("Suno Radio", 3, 2, 1)], shown
    print("   all tagged AI songs leave by default; a blocked channel loses every song, tagged or not; kept artists stay; the tool previews, warns about mixed answers and writes the list")


def demo_server_test():
    """demo_server.py: link parsing, one job at a time, every failure route offers the tab-capture fallback, audio is deleted, answers are logged."""
    print("\n20. LIVE DEMO SERVER")
    import contextlib, csv, json, os, tempfile, threading, time, urllib.request, urllib.error
    import numpy as np
    import demo_server as ds

    # (a) which links are accepted: only YouTube, and only the 11-character id is used afterwards
    ok_ids = {"https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5s": "dQw4w9WgXcQ", "youtu.be/dQw4w9WgXcQ?si=abc": "dQw4w9WgXcQ",
              "https://music.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ", "dQw4w9WgXcQ": "dQw4w9WgXcQ"}
    for text, vid in ok_ids.items():
        assert ds.video_id(text) == vid, text
    for bad in ("", "hello world", "https://vimeo.com/123456789", "https://evil.example/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ; rm -rf /", "file:///etc/passwd"):
        assert ds.video_id(bad) is None, bad
    assert ds.yt_id_of("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ" and ds.yt_id_of("https://example.com/x") == ""
    s = ds.shape(dict(A=[dict(link="https://youtu.be/dQw4w9WgXcQ", x=np.float64(1.5))] * 9, B=[], features=["sound"], pool=3, best_sound=np.float64(0.9)), 4)
    assert len(s["A"]) == 4 and s["A"][0]["yt"] == "dQw4w9WgXcQ" and json.dumps(s, default=ds._plain)
    got = ds.auto_samples(["a", "b", "c", "d"], ["A", "B", "C", "D"], ["x"] * 4, ["g1", "g1", "g2", "g3"], [5.0, 9.0, float("nan"), 1.0], n=2)
    assert [x["key"] for x in got] == ["b", "c"], got                    # the two biggest groups (g1: 2 songs, then g2 / g3 tie by first seen), the most viewed song of each

    # (b) a fake backend (no Essentia, no pool, no network)
    d = tempfile.mkdtemp()
    seen = dict(paths=[], features=[])
    gate = threading.Event(); gate.set()

    class Fake:
        def warm(self): return 42
        def weak_cosine(self): return 0.45
        def info(self, vid):
            if vid == "ddddddddddd":
                raise ds.DemoError("lookup_failed", "YouTube would not let this computer read that video.", fallback="capture")
            return dict(title="Song " + vid[:3], channel="Chan", duration=1200.0 if vid == "bbbbbbbbbbb" else 200.0)
        @contextlib.contextmanager
        def download(self, vid):
            if vid == "ccccccccccc":
                raise RuntimeError("http error 403: forbidden")
            with tempfile.TemporaryDirectory(prefix="hg_fake_") as td:
                p = os.path.join(td, "song.mp3"); open(p, "wb").write(b"x" * 100); seen["paths"].append(p)
                yield p
        def analyse(self, path):
            gate.wait(10)
            self.last_timings = {"decode": 0.4, "effnet": 1.2, "rhythm": 0.01, "total": 1.61}
            return dict(f=1)
        def analyse_clip(self, wav_path):
            n = os.path.getsize(wav_path)
            return dict(rms_db=-20, silent_share=0.0), (None if n < 1000 else dict(f=2))
        def query(self, feats): return feats
        def sample_query(self, key): return dict(f=3), dict(title="T", artist="A")
        def search(self, q, n=5):
            if q == "boom":
                raise ds.DemoError("search_failed", "YouTube search did not answer.")
            return [dict(id=c * 11, title=f"{q} {i}", channel="C", seconds=200, views=10, official=i == 0) for i, c in enumerate("kxyzwv")][:n]
        def known(self, vid): return vid == "kkkkkkkkkkk" or vid in seen.setdefault("cached", set())
        def known_query(self, vid): return dict(f=7), dict(title="Known " + vid[:3], artist="Pool Artist", duration=181)
        def cache_put(self, vid, feats, meta):
            seen.setdefault("cached", set()).add(vid); seen["cache_meta"] = meta
        def recommend(self, q, meta, k, features):
            seen["features"].append(features)
            best = 0.3 if seen.get("weak") else 0.9
            row = lambda i, w: dict(key=f"youtube_x{i}{w}", title=f"Rec {i}", artist="Art", link=f"https://www.youtube.com/watch?v=xxxxxxxxx{i}{w}",
                                    sound=np.float64(80), mood=70, rhythm=60, instruments=75, match=np.float64(80 - i), popularity="few plays", ai="")
            return dict(A=[row(i, "a") for i in range(10)], B=[row(i, "b") for i in range(3 if features != "none" else 0)], features=["sound"] + features.split("+"),
                        pool=42, best_sound=best, A_bar=np.float64(70.0), B_bar=65.0)
        def samples(self): return [dict(key="youtube_s1", title="Sample one", artist="Someone")]

    demo = ds.Demo(Fake(), k=4, log=os.path.join(d, "log.csv"), feedback=os.path.join(d, "fb.csv"))
    html = os.path.join(d, "demo.html"); open(html, "w").write("<html>demo</html>")
    srv = ds.make_server(demo, "127.0.0.1", 0, html)
    assert srv.server_address[0] == "127.0.0.1"                                       # this computer only, unless --host is given
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(path, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    J = lambda r: (r[0], json.loads(r[1]))
    try:
        # before the pool is loaded the server says so instead of failing
        assert J(call("/api/status"))[1]["ready"] is False
        code, b = J(call("/api/link", dict(url="dQw4w9WgXcQ")))
        assert code == 503 and b["error"] == "warming_up", (code, b)
        demo.warm()
        st = J(call("/api/status"))[1]
        assert st["ready"] and st["pool"] == 42 and not st["busy"]
        assert call("/")[0] == 200 and b"demo" in call("/")[1]
        # a good link: two lists, the first k shown, YouTube ids filled in, the downloaded audio is gone afterwards
        code, b = J(call("/api/link", dict(url="https://www.youtube.com/watch?v=aaaaaaaaaaa")))
        assert code == 200 and b["ok"] and b["input"]["title"] == "Song aaa" and len(b["results"]["A"]) == 4 and len(b["results"]["B"]) == 3, (code, b)
        assert b["results"]["A"][0]["yt"] == "xxxxxxxxx0a" and seen["paths"] and not os.path.exists(seen["paths"][-1]), "audio must be deleted"
        token = b["token"]
        # every failure route offers the tab capture, except the ones that are the user's to fix
        for url, want_err, want_fallback in (("https://vimeo.com/123456789", "not_youtube", None), ("bbbbbbbbbbb", "too_long", None),
                                             ("ccccccccccc", "download_failed", "capture"), ("ddddddddddd", "lookup_failed", "capture")):
            code, b = J(call("/api/link", dict(url=url)))
            assert b["error"] == want_err and b.get("fallback") == want_fallback and code in (200, 400), (url, code, b)
        assert not os.path.exists(seen["paths"][-1])
        # one job at a time
        gate.clear()
        t = threading.Thread(target=lambda: call("/api/link", dict(url="eeeeeeeeeee")), daemon=True); t.start()
        for _ in range(100):
            if J(call("/api/status"))[1]["busy"]:
                break
            time.sleep(0.05)
        st = J(call("/api/status"))[1]
        assert st["busy"] and st["stage"], st
        code, b = J(call("/api/link", dict(url="eeeeeeeeeee")))
        assert code == 429 and b["error"] == "busy", (code, b)
        gate.set(); t.join(10)
        assert not J(call("/api/status"))[1]["busy"]
        # tab capture: needs a WAV; silent clips and non-WAV bodies are refused with a reason; a weak match carries a warning
        wavlike = b"RIFF" + b"\0" * 5000
        code, b = J(call("/api/capture", raw=wavlike))
        assert code == 200 and b["ok"] and b["input"]["kind"] == "capture" and "warning" not in b, (code, b)
        assert J(call("/api/capture", raw=b"RIFF" + b"\0" * 10))[1]["error"] == "silent"
        assert J(call("/api/capture", raw=b"not a wav"))[0] == 400
        seen["weak"] = True
        assert "warning" in J(call("/api/capture", raw=wavlike))[1]
        # samples: listed, one can be run, an unknown key is refused
        assert J(call("/api/samples"))[1][0]["key"] == "youtube_s1"
        code, b = J(call("/api/sample", dict(key="youtube_s1")))
        assert code == 200 and b["input"]["title"] == "Sample one"
        assert J(call("/api/sample", dict(key="nope")))[0] == 400
        # refine: the chosen features reach the recommender; unknown tokens / no features are refused
        code, b = J(call("/api/refine", dict(token=token, features="mood+instruments")))
        assert code == 200 and seen["features"][-1] == "mood+instruments"
        assert J(call("/api/refine", dict(token=token, features="bogus")))[0] == 400 and J(call("/api/refine", dict(token="x", features="mood")))[0] == 400
        # ratings are saved with the song they belong to; bad ones are refused
        assert J(call("/api/rate", dict(token=token, visitor="v1x", list="A", rec_key="youtube_x0a", rec_title="Rec 0", would_add="yes")))[0] == 200
        assert J(call("/api/rate", dict(token=token, list="Z", would_add="yes")))[0] == 400 and J(call("/api/rate", dict(token="x", list="A")))[0] == 400
        fb = list(csv.DictReader(open(os.path.join(d, "fb.csv"), encoding="utf-8-sig")))
        assert len(fb) == 1 and fb[0]["rec_key"] == "youtube_x0a" and fb[0]["would_add"] == "yes" and fb[0]["input"] == "aaaaaaaaaaa" and fb[0]["visitor"] == "v1x", fb
        # booth: a typed song name finds candidates (each says whether its numbers are stored), and a stored song needs no YouTube, no download, no analysis
        code, b = J(call("/api/search", dict(q="  hello   world ")))
        assert code == 200 and b["ok"] and b["query"] == "hello world" and len(b["results"]) == 5 and b["results"][0]["instant"] is True and b["results"][1]["instant"] is False, b
        assert J(call("/api/search", dict(q="boom")))[1]["ok"] is False and J(call("/api/search", dict(q="a")))[0] == 400
        n_paths = len(seen["paths"])
        code, b = J(call("/api/link", dict(url="kkkkkkkkkkk", visitor="v 1;x")))                       # the visitor id is cleaned to letters and digits
        assert code == 200 and b["source"] == "stored" and b["input"]["title"] == "Known kkk" and len(seen["paths"]) == n_paths, b
        assert ds.clean_visitor("v 1;x") == "v1x" and ds.clean_visitor(None) == "" and len(ds.clean_visitor("a" * 40)) == 12
        # one visitor, several songs: every song is its own result with its own token and its own lists (the server never combines songs)
        code, b2 = J(call("/api/link", dict(url="aaaaaaaaaaa", visitor="v1x")))
        assert b2["token"] != b["token"] and b2["results"]["A"] != [] and "blend" not in json.dumps(b2).lower(), b2
        # a new song's numbers are kept after its first analysis (never the audio), so the next visitor with the same song is served at once
        assert "aaaaaaaaaaa" in seen["cached"] and seen["cache_meta"]["title"].startswith("Song")
        code, b = J(call("/api/link", dict(url="aaaaaaaaaaa")))
        assert b["source"] == "stored" and len(seen["paths"]) == n_paths
        # a weak match is said out loud on every route, not only for recordings
        seen["weak"] = True
        code, b = J(call("/api/link", dict(url="kkkkkkkkkkk")))
        assert "closest we have" in b["warning"], b
        seen["weak"] = False
        # every run is logged with the reason when it failed
        log = list(csv.DictReader(open(os.path.join(d, "log.csv"), encoding="utf-8-sig")))
        errs = [r["error"] for r in log if r["ok"] == "0"]
        assert {"download_failed", "lookup_failed", "too_long", "silent"} <= set(errs) and sum(r["ok"] == "1" and r["kind"] == "link" for r in log) >= 4, errs
        assert any("effnet 1.2" in r["detail"] and "decode 0.4" in r["detail"] and "rhythm" not in r["detail"] for r in log), [r["detail"] for r in log]
        assert sum(r["visitor"] == "v1x" for r in log) >= 2 and any(r["kind"] == "search" for r in log) and any(r["source"] == "stored" for r in log) and any(r["best_sound"] not in ("", None) for r in log), log[:3]
    finally:
        gate.set(); srv.shutdown(); srv.server_close()
    # "what we heard": plain words, never more than the models know
    assert ds.mood_label(7.0, 7.0) == "upbeat and energetic" and ds.mood_label(3.0, 3.0) == "sad and calm" and ds.mood_label(5.0, 5.0) == "balanced" and ds.mood_label(float("nan"), 5) == ""
    assert ds.tempo_text(92.4, 3.1) == "about 92 BPM" and ds.tempo_text(92.4, 0.5) == "tempo unclear" and ds.tempo_text(300, 4) == "tempo unclear" and ds.tempo_text(None, None) == "tempo unclear"
    names = ["voice", "drums", "acousticguitar", "piano", "beat", "strings"]
    assert ds.top_instruments([0.99, 0.5, 0.9, 0.8, 0.95, 0.1], names) == ["acoustic guitar", "piano", "drums"]            # voice and beat are not instruments
    h = ds.build_heard(dict(va_vg=np.array([np.nan, np.nan]), va_mc=np.array([6.0, 3.0]), inst=np.array([0.1, 0.2, 0.9, 0.8, 0.1, 0.3]), bpm=100.0, confidence=3.0), names)
    assert h["mood"] == "warm and relaxed" and h["instruments"][0] == "acoustic guitar" and h["tempo"] == "about 100 BPM" and h["energy"] == 3.0, h      # falls back to the other mood model when VGGish has no output
    # practice mode: the fake backend answers everything the page asks, flags itself on the status, and its numbers never reach the real logs
    fd = tempfile.mkdtemp()
    fake = ds.Demo(ds.FakeBackends(), k=3, log=os.path.join(fd, "l.csv"), feedback=os.path.join(fd, "f.csv"))
    fake.fake = True; fake.warm()
    assert fake.status()["fake"] is True and fake.status()["ready"]
    code, b = fake.from_link("dQw4w9WgXcQ")
    assert code == 200 and len(b["results"]["A"]) == 3 and b["heard"]["mood"] and b["results"]["A"][0]["title"].startswith("Practice"), b
    assert fake.from_sample("practice_s1")[0] == 200 and fake.refine(b["token"], "mood")[0] == 200
    # the pre-flight check: one line per thing that can fail on the day, with a plain fix
    memfile = os.path.join(fd, "meminfo"); open(memfile, "w").write("MemTotal: 16000000 kB\nMemAvailable: 2000000 kB\n")
    def run(cmd, timeout=45):
        if cmd[0] == "yt-dlp" and "--version" in cmd:
            return 0, "2025.01.01\n", ""
        if cmd[0] == "yt-dlp":
            return 1, "", "ERROR: Sign in to confirm you are not a bot\n"
        if cmd[0] == "hostname":
            return 0, "172.20.1.2 \n", ""
        return -1, "", ""
    res = ds.doctor(port=0, run=run, which=lambda x: None, meminfo=memfile, here=fd, jobs=["123"])
    text = "\n".join(f"{l}: {t}" for l, t in res)
    assert "warn: yt-dlp 2025.01.01" in text and "fail: ffmpeg is missing" in text and "fail: deno is missing" in text and "fail: 1.9 GB of memory free" in text and "warn: an analysis" in text, text
    assert "warn: YouTube would not answer" in text and "Sign in" in text and "http://172.20.1.2:" in text and "fail: results/ai_tags.csv is missing" in text, text
    # the rehearsal: a link per line, comments ignored, one line each, a CSV, the capture fallback counted
    lp = os.path.join(fd, "links.txt"); open(lp, "w").write("# my links\naaaaaaaaaaa\nhttps://vimeo.com/123456789\nccccccccccc\nhello world\n\n")
    lines = []
    rd = ds.Demo(Fake(), k=4, log=os.path.join(fd, "rl.csv"), feedback=os.path.join(fd, "rf.csv"))
    rows = ds.rehearse(lp, rd, out_csv=os.path.join(fd, "reh.csv"), printer=lines.append)
    assert [r["ok"] for r in rows] == [1, 0, 0, 1] and rows[2]["error"] == "CAPTURE download_failed" and rows[1]["error"] == "not_youtube", rows
    assert rows[3]["asked"] == "hello world" and rows[3]["title"].startswith("Known"), rows[3]              # a NAME is searched and its first candidate is used, like a visitor's tap
    assert os.path.exists(os.path.join(fd, "reh.csv")) and "2 of 4 worked" in lines[-1] and "1 would need the tab capture" in lines[-1], lines
    try:
        ds.rehearse(os.path.join(fd, "nope.txt"), rd, out_csv=os.path.join(fd, "x.csv"), printer=lines.append)
        raise AssertionError("a missing file must stop with a plain message")
    except SystemExit as e:
        assert "not found" in str(e) and "rehearsal_songs.txt" in str(e), str(e)
    # the benchmark: four ways of analysing, each compared with the full analysis
    class B2:
        def search(self, q, n=5): return [dict(id="bbbbbbbbbbb", title="Song B")]
        def warm(self): return 10
        @contextlib.contextmanager
        def download(self, vid): yield "/dev/null"
        def analyse_full(self, path, fast=True, max_seconds=None):
            time.sleep(0.01)
            f = {(False, None): 0, (True, None): 0, (True, 90): 1, (True, 60): 2}[(fast, max_seconds)]
            return dict(f=f), {"decode": 1.0, "effnet": 4.0 if not fast else 2.0, "total": 5.0}
        def query(self, feats): return dict(whole=np.array([1.0, 0.5 + 0.05 * feats["f"]]), f=feats["f"])
        def recommend(self, q, meta, k, features):
            n_changed = {0: 0, 1: 2, 2: 5}[q["f"]]
            return dict(A=[dict(key=(f"new{i}" if i < n_changed else f"k{i}")) for i in range(10)])
    lines2 = []
    rows2 = ds.benchmark("hello", b=B2(), printer=lines2.append)
    assert [r["same"] for r in rows2] == [10, 10, 8, 5], rows2
    text2 = "\n".join(lines2)
    assert "fast mode saves" in text2 and "acceptable if you need the speed (start the demo with --excerpt 90)" in text2 and "too much changes: keep whole songs" in text2, text2
    import io, contextlib as _cl
    buf = io.StringIO()
    with _cl.redirect_stdout(buf):
        ds.summary(os.path.join(d, "log.csv"), os.path.join(d, "fb.csv"))
    out = buf.getvalue()
    assert "runs:" in out and "download_failed" in out and "link, new song (downloaded and analysed): median" in out and "would add 1 of 1" in out and "1 visitors with at least one song" in out and "never blended" in out, out
    print("   links are checked, one job at a time, every failure offers the tab capture, audio is deleted, ratings and runs are logged")


def mark_ai_out_test():
    """mark_ai_out.py: AI-tagged songs and blocked channels are marked out of the lists for good; ai_keep wins; other marks are never touched or restored; --restore undoes only its own marks;
    the pool filter stays quiet unless un-marked AI songs are still in the lists."""
    print("\n21. MARKING AI SONGS OUT OF THE LISTS")
    import blind_test as bt, tag_ai, mark_ai_out as mo, replace_songs as rs, csv, io, contextlib, os, tempfile
    assert tag_ai.ai_reason("confirmed", 5.0, "x", "y", "hide", set(), set()) == "confirmed" and tag_ai.ai_reason("none", 5.0, "x", "y", "hide", set(), set()) is None
    assert tag_ai.ai_reason("likely", 5.0, "kanegi", "y", "hide", {"kanegi"}, set()) is None and tag_ai.ai_reason("none", 5.0, "bad", "y", "hide", set(), {"bad"}) == "blocked channel"
    assert tag_ai.ai_reason("likely", 50000.0, "x", "y", "hide-low", set(), set()) is None and tag_ai.ai_reason("likely", 50000.0, "x", "y", "hide", set(), set()) == "likely"
    d = tempfile.mkdtemp(); log = os.path.join(d, "audit.csv")
    ids = ["a", "b", "c", "d", "e"]
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["source", "track_id", "title", "artist", "i_agree"])
        for i in ids:
            w.writerow(["youtube", i, f"title {i}", {"a": "Real Band", "d": "kanegi"}.get(i, "Someone"), "n" if i == "e" else ""])
        w.writerow(["fma", "9", "an fma song", "Old Band", ""])
    chans = {f"youtube_{i}": c for i, c in zip(ids, ["Real Band", "Real Radio", "Suno Radio", "kanegi.", "Real Radio"])}
    tags = {"youtube_b": ("confirmed", "", 10.0), "youtube_d": ("likely", "", 3.0), "youtube_e": ("likely", "", 3.0), "fma_9": ("confirmed", "", 1.0)}
    keep, block = {"kanegi"}, {"suno radio"}
    lists = rs.load_lists(d)
    plan = mo.plan_mark(lists, tags, chans, keep, block, "hide")
    got = {r["track_id"]: why for _, r, why in plan}
    assert got == {"b": "AI: confirmed", "c": "AI: blocked channel (Suno Radio)"}, got            # a real, d kept (kanegi), e already marked, the fma song is not looked at
    assert mo.apply_mark(lists, plan, d, log) == 2
    after = {r["track_id"]: r["i_agree"] for r in csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig"))}
    assert after == {"a": "", "b": "n", "c": "n", "d": "", "e": "n", "9": ""} and os.path.exists(os.path.join(d, "pool_youtube.csv.bak")), after
    assert "AI: blocked channel (Suno Radio)" in open(log, encoding="utf-8-sig").read()
    assert mo.plan_mark(rs.load_lists(d), tags, chans, keep, block, "hide") == []                    # a second run changes nothing
    # restore: the channel is unblocked -> c comes back; b is still tagged; e was marked for another reason (written in the log as a duplicate) and is never restored
    with open(log, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(["2026-10-12", "youtube_e", "title e", "Someone", "duplicate upload of youtube_x"])
    lists = rs.load_lists(d)
    pr = mo.plan_restore(lists, tags, chans, keep, set(), "hide", log)
    assert [r["track_id"] for _, r in pr] == ["c"], pr
    assert mo.apply_restore(lists, pr, d, log) == 1
    after = {r["track_id"]: r["i_agree"] for r in csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig"))}
    assert after["c"] == "" and after["b"] == "n" and after["e"] == "n"
    assert "AI mark removed" in open(log, encoding="utf-8-sig").read()
    # the pool filter: silent when nothing un-marked is left, one clear line (with the fix) when it is
    keys = [f"youtube_{c}" for c in "abc"]
    def P():
        return dict(key=list(keys), source=["youtube"] * 3, link=["l"] * 3, listens=np.arange(3.0), artist_name=["x", "y", "z"])
    saved = (tag_ai.load_tags, tag_ai.load_channels, tag_ai.load_name_list)
    try:
        tag_ai.load_channels, tag_ai.load_name_list = (lambda res=None: {k: "c" for k in keys}), (lambda name, here=None: set())
        for tg, loud in (({k: ("none", "", 1.0) for k in keys}, False), ({**{k: ("none", "", 1.0) for k in keys}, "youtube_b": ("likely", "", 1.0)}, True)):
            tag_ai.load_tags = lambda tg=tg: tg
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                out = bt.apply_quality(P())
            assert ("mark_ai_out.py --apply" in buf.getvalue()) == loud and (buf.getvalue() == "" or loud), repr(buf.getvalue())
            assert out["key"] == (["youtube_a", "youtube_c"] if loud else keys)
    finally:
        tag_ai.load_tags, tag_ai.load_channels, tag_ai.load_name_list = saved
    print("   AI songs and blocked channels are marked out once (logged with the reason), kept artists and other marks are untouched, --restore undoes only its own marks, the filter speaks only when something is left to mark")


def analysis_fast_test():
    """analyze.analyse(fast=True) skips the models the app never reads and gives identical numbers for everything it does read; max_seconds keeps only the middle of a long song."""
    print("\n22. FAST AND EXCERPT ANALYSIS (for the demo)")
    import analyze, blind_test as bt
    a16, a44 = np.arange(16000 * 100, dtype=np.float32), np.arange(44100 * 100, dtype=np.float32)
    x16, x44, cut = analyze.centre_excerpt(a16, a44, 30)
    assert cut and len(x16) == 30 * 16000 and len(x44) == 30 * 44100 and x16[0] == 35 * 16000 and x44[0] == 35 * 44100          # the middle 30 s of 100 s
    assert analyze.centre_excerpt(a16, a44, 80)[2] is False and analyze.centre_excerpt(a16, a44, None)[2] is False                # up to 1.3x the limit: analysed whole
    saved = (analyze.FAKE, analyze.load, analyze.rhythm_features, analyze._es)
    try:
        analyze.FAKE = True
        rng = np.random.default_rng(1)
        analyze.load = lambda path: ((0.1 * rng.normal(size=16000 * 200)).astype(np.float32), (0.1 * rng.normal(size=44100 * 200)).astype(np.float32))
        analyze.rhythm_features = lambda a: (dict(bpm=100.0, confidence=3.0, steadiness=0.1, busyness=2.0, danceability=1.0, loudness_db=-20.0, n_beats=100), 0.1)
        analyze._es = lambda: None
        full, _ = analyze.analyse("/x/song.mp3")
        fast, _ = analyze.analyse("/x/song.mp3", fast=True)
        cut_, _ = analyze.analyse("/x/song.mp3", fast=True, max_seconds=60)
        whole_len, _ = analyze.analyse("/x/song.mp3", fast=True, max_seconds=190)
    finally:
        analyze.FAKE, analyze.load, analyze.rhythm_features, analyze._es = saved
    needed = ("effnet_whole", "effnet_parts", "instruments_whole", "instruments_parts", "emomusic_whole", "emomusic_parts", "cand_emomusic_vggish_whole",
              "rhythm_bpm", "rhythm_confidence", "rhythm_steadiness", "rhythm_busyness")
    for k in needed:
        assert k in fast and np.allclose(full[k], fast[k], equal_nan=True), k                       # identical numbers for everything the app reads
    for k in ("genre_top5_idx", "mood_happy_whole", "mood_aggressive_whole", "deam_whole", "cand_deam_vggish_whole", "cand_tempocnn_bpm", "cand_percival_bpm", "cand_danceability_whole"):
        assert k in full and k not in fast, k                                                          # the models the app never reads are skipped
    q1, q2 = bt.query_from_analysis(full), bt.query_from_analysis(fast)
    assert all(np.allclose(np.asarray(q1[k], float), np.asarray(q2[k], float), equal_nan=True) for k in q1), "a fast analysis must give the same query"
    assert "excerpt_seconds" not in fast and "excerpt_seconds" not in whole_len and cut_["excerpt_seconds"] == 60.0 and abs(cut_["trimmed_duration"] - 60) < 1.0, (cut_["trimmed_duration"])
    print("   fast analysis = same query as the full analysis without the unused models; an excerpt keeps the middle of long songs only")


def demo_bundle_test():
    """make_demo_bundle.py: only pool songs with numbers, cut-down .npz files that give the same query, the lists and tags, nothing else."""
    print("\n23. DEMO BUNDLE FOR THE BOOTH LAPTOP")
    import make_demo_bundle as mb, blind_test as bt, zipfile, tempfile, csv, os, io
    d = tempfile.mkdtemp(); res = os.path.join(d, "results"); os.makedirs(os.path.join(res, "meta"))
    rng = np.random.default_rng(3)
    def full_npz(path):
        np.savez_compressed(path, effnet_whole=rng.normal(size=1280), effnet_parts=rng.normal(size=(3, 1280)), effnet_chunks=rng.normal(size=(200, 1280)).astype(np.float16),
                            instruments_whole=rng.random(40), instruments_parts=rng.random((3, 40)), instruments_chunks=rng.random((200, 40)).astype(np.float16),
                            emomusic_whole=np.array([5.0, 6.0]), emomusic_parts=rng.random((3, 2)) + 4, cand_emomusic_vggish_whole=np.array([5.5, 5.0]),
                            rhythm_bpm=100.0, rhythm_confidence=3.0, rhythm_steadiness=0.1, rhythm_busyness=2.0, genre400_extra=rng.normal(size=400))
    with open(os.path.join(res, "index.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["key", "status", "group", "artist", "title", "page", "listens"])
        for k in ("a", "b", "c", "e"):
            w.writerow([f"youtube_{k}", "done", "yt_pop", f"Artist {k}", f"Title {k}", f"https://www.youtube.com/watch?v={k}", 100])
    for k in ("a", "b", "e"):                                           # c is listed in the pool but has no numbers file; e is marked out (i_agree = n)
        full_npz(os.path.join(res, f"youtube_{k}.npz")); open(os.path.join(res, "meta", f"youtube_{k}.json"), "w").write('{"title": "T"}')
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["source", "track_id", "title", "artist", "group", "i_agree"])
        for k in ("a", "b", "c", "e"):
            w.writerow(["youtube", k, f"Title {k}", f"Artist {k}", "yt_pop", "n" if k == "e" else ""])
    for n in ("ai_tags.csv",):
        open(os.path.join(res, n), "w").write("key,status\n")
    open(os.path.join(d, "ai_keep.txt"), "w").write("kanegi\n")
    dry = mb.build(d, os.path.join(d, "out"), dry_run=True)
    assert dry["zip"] is None and dry["songs"] == 2 and dry["listed"] == 3 and dry["missing"] == 1 and not os.path.exists(os.path.join(d, "out")), dry
    r = mb.build(d, os.path.join(d, "out"), when="test")
    assert r["songs"] == 2 and r["zip"].endswith("demo-bundle-test.zip"), r
    with zipfile.ZipFile(r["zip"]) as z:
        names = set(z.namelist())
        assert {"results/youtube_a.npz", "results/youtube_b.npz", "results/index.csv", "results/meta/youtube_a.json", "pool_youtube.csv", "ai_keep.txt", "results/ai_tags.csv", "DEMO_BUNDLE_README.txt"} <= names, names
        assert "results/youtube_e.npz" not in names and "results/youtube_c.npz" not in names                      # marked out / no numbers: not in the bundle
        assert "results/windows_cache.npz" in names, names
        wc = np.load(io.BytesIO(z.read("results/windows_cache.npz")), allow_pickle=False)
        assert list(wc["keys"]) == ["youtube_a", "youtube_b"] and "raw" in wc.files, list(wc["keys"])              # same order as the bundle's index.csv
        import match
        with np.load(os.path.join(res, "youtube_b.npz")) as fb:
            want = match.window_means(fb["effnet_chunks"])
        assert np.array_equal(wc["vecs"][wc["owner"] == 1], want) and set(wc["owner"]) == {0, 1}, "the stretch index must equal what match.windows would build"
        idx = list(csv.DictReader(io.StringIO(z.read("results/index.csv").decode("utf-8-sig"))))
        assert sorted(x["key"] for x in idx) == ["youtube_a", "youtube_b"], idx
        slim = np.load(io.BytesIO(z.read("results/youtube_a.npz")), allow_pickle=False)
        assert set(slim.files) <= set(mb.KEEP_KEYS) and "effnet_chunks" not in slim.files and "genre400_extra" not in slim.files, slim.files
        assert "DEMO_BUNDLE_README" in "".join(names) and b"python demo_server.py --check" in z.read("DEMO_BUNDLE_README.txt")
        slim_dict = {k: slim[k] for k in slim.files}
    with np.load(os.path.join(res, "youtube_a.npz"), allow_pickle=False) as fullz:
        q_full, q_slim = bt.query_from_analysis({k: fullz[k] for k in fullz.files}), bt.query_from_analysis(slim_dict)
    assert all(np.allclose(np.asarray(q_full[k], float), np.asarray(q_slim[k], float), equal_nan=True) for k in q_full), "a cut-down file must give the same query"
    assert os.path.getsize(r["zip"]) < 0.5 * sum(os.path.getsize(os.path.join(res, f"youtube_{k}.npz")) for k in "abe") + 5000                          # and it is smaller
    print("   the bundle holds only pool songs with numbers, in cut-down files that give the same query, plus the lists, tags and a README")


def demo_hardening_test():
    """Fixes from the 12 Oct review of the demo server: CSV formulas, unwritable logs, half-written cache entries, live streams, analysis errors, odd Content-Length."""
    print("\n24. DEMO SERVER HARDENING")
    import contextlib, csv, io, json, os, tempfile
    import demo_server as ds
    d = tempfile.mkdtemp()
    # (a) a typed song name or a title that starts with = + - @ is stored as plain text; a log that cannot be written does not raise
    log = os.path.join(d, "x", "log.csv")
    ds.append_row(log, ["a", "b"], dict(a="=HYPERLINK(1)", b="+1 -x"))
    ds.append_row(log, ["a", "b"], dict(a="normal", b=5))
    rows = list(csv.DictReader(open(log, encoding="utf-8-sig")))
    assert rows[0]["a"] == "'=HYPERLINK(1)" and rows[0]["b"] == "'+1 -x" and rows[1]["a"] == "normal" and rows[1]["b"] == "5", rows
    blocker = os.path.join(d, "afile"); open(blocker, "w").write("x")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        ds.append_row(os.path.join(blocker, "sub", "log.csv"), ["a"], dict(a=1))              # the folder cannot be made: a message, no exception
    assert "could not write" in out.getvalue()
    # (b) a cache entry is complete or absent: no temporary files left, the .npz (what known() looks for) exists only with its .json
    old_cache = ds.DEMO_CACHE
    ds.DEMO_CACHE = os.path.join(d, "cache")
    try:
        b = ds.Backends.__new__(ds.Backends)
        b.cache_put("aaaaaaaaaaa", dict(whole=np.ones(3), name="text-is-skipped"), dict(title="T", artist="A", duration=190))
        names = sorted(os.listdir(ds.DEMO_CACHE))
        assert names == ["aaaaaaaaaaa.json", "aaaaaaaaaaa.npz"], names
        assert json.load(open(os.path.join(ds.DEMO_CACHE, "aaaaaaaaaaa.json")))["title"] == "T"
    finally:
        ds.DEMO_CACHE = old_cache
    # (c) live streams and premieres are refused before any download
    class P:
        def __init__(self, out): self.returncode, self.stdout, self.stderr = 0, out, b""
    real_run = ds.subprocess.run
    try:
        for payload in (dict(title="Live", duration=None, is_live=True), dict(title="Premiere", duration=200, live_status="is_upcoming"), dict(title="No length")):
            ds.subprocess.run = lambda *a, _p=payload, **k: P(json.dumps(_p).encode())
            try:
                ds.Backends.__new__(ds.Backends).info("bbbbbbbbbbb")
                raise AssertionError("a live stream must be refused")
            except ds.DemoError as e:
                assert e.code == "not_a_song", e.code
        ds.subprocess.run = lambda *a, **k: P(json.dumps(dict(title="Song", channel="C", duration=200)).encode())
        assert ds.Backends.__new__(ds.Backends).info("bbbbbbbbbbb")["duration"] == 200.0
    finally:
        ds.subprocess.run = real_run
    # (d) stored numbers that cannot be read fall through to the download; an analysis crash is not reported as a blocked download
    state = dict(analyse_fails=False)

    class Fake:
        def warm(self): return 1
        def weak_cosine(self): return 0.45
        def known(self, vid): return True
        def known_query(self, vid): raise ValueError("truncated file")
        def info(self, vid): return dict(title="S", channel="C", duration=200.0)
        @contextlib.contextmanager
        def download(self, vid):
            with tempfile.TemporaryDirectory(prefix="hg_fake_") as td:
                p = os.path.join(td, "song.mp3"); open(p, "wb").write(b"x"); yield p
        def analyse(self, path):
            if state["analyse_fails"]:
                raise RuntimeError("model crashed")
            return dict(f=1)
        def query(self, feats): return feats
        def recommend(self, q, meta, k, features):
            return dict(A=[], B=[], features=["sound"], pool=1, best_sound=0.9, A_bar=1.0, B_bar=1.0)
    demo = ds.Demo(Fake(), k=3, log=os.path.join(d, "l.csv"), feedback=os.path.join(d, "f.csv"))
    demo.warm()
    code, body = demo.from_link("https://youtu.be/dQw4w9WgXcQ")
    assert code == 200 and body.get("ok"), (code, body)
    state["analyse_fails"] = True
    code, body = demo.from_link("https://youtu.be/dQw4w9WgXcQ")
    assert body.get("error") == "analysis_failed" and body.get("fallback") == "capture" and "blocked" not in body["message"], body
    # (e) Content-Length: negative or not a number is refused, never read
    class H(ds.BaseHTTPRequestHandler):
        pass
    handler = ds.make_handler(demo, os.path.join(d, "demo.html"))
    h = handler.__new__(handler)
    for bad in ("-1", "abc"):
        h.headers = {"Content-Length": bad}
        try:
            h._length(1000)
            raise AssertionError(bad)
        except ds.DemoError as e:
            assert e.status == 400, e.status
    h.headers = {"Content-Length": "5000"}
    try:
        h._length(1000); raise AssertionError("too big")
    except ds.DemoError as e:
        assert e.status == 413
    h.headers = {}; assert h._length(1000) == 0
    h.headers = {"Content-Length": "999"}; assert h._length(1000) == 999
    print("   formulas neutralised, log failures harmless, cache entries atomic, live streams refused, analysis errors named correctly, bad lengths refused")


def data_safety_test():
    """Fixes from the 12 Oct review of scripts that rewrite user files: replacements without a usable new song, block-list append, proposals sheet, AI tags merge."""
    print("\n25. DATA SAFETY OF THE POOL TOOLS")
    import contextlib, csv, io, json, os, tempfile
    import replace_songs as rs, ai_channels as ac, find_official_versions as fo
    d = tempfile.mkdtemp()
    # (a) the old song leaves only when its replacement really exists
    cols = ["source", "track_id", "title", "artist", "duration", "listens", "licence", "listen", "site_genre", "group", "i_agree"]
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cols)
        for vid in ("oldAAAAAAAA", "oldBBBBBBBB", "oldCCCCCCCC"):
            w.writerow(["youtube", vid, "Song " + vid, "Art", 200, 100, "youtube-standard", "u", "pop", "yt_pop", ""])
        w.writerow(["youtube", "newBBBBBBBB", "Song B official", "Art", 200, 100, "youtube-standard", "u", "pop", "yt_pop", "n"])          # replacement already there, but marked out
    lists = rs.load_lists(d)
    pairs = [("1", "oldAAAAAAAA", "newAAAAAAAA", "t"), ("2", "oldBBBBBBBB", "newBBBBBBBB", "t"), ("3", "oldCCCCCCCC", "newCCCCCCCC", "t")]
    details = {"newBBBBBBBB": dict(title="B", channel="Art", duration=200, views=5, licence="youtube-standard"),
               "newCCCCCCCC": dict(title="C", channel="Art", duration=200, views=5, licence="youtube-standard")}       # newAAAAAAAA: the API found nothing
    acts = rs.plan(pairs, lists, details)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        done = rs.apply_plan(acts, lists, d, os.path.join(d, "audit.csv"))
    assert done == (1, 1) and out.getvalue().count("left alone") == 2, (done, out.getvalue())
    rows = {r["track_id"]: r for r in csv.DictReader(open(os.path.join(d, "pool_youtube.csv"), encoding="utf-8-sig"))}
    assert rows["oldAAAAAAAA"]["i_agree"] == "" and rows["oldBBBBBBBB"]["i_agree"] == "" and rows["oldCCCCCCCC"]["i_agree"] == "n" and "newCCCCCCCC" in rows
    # (b) a block list that ends without a newline does not swallow the first new channel
    bf = os.path.join(d, "ai_block.txt"); open(bf, "w", encoding="utf-8").write("# comment without newline at the end")
    assert ac.write_block(["Some Channel"], bf) == 1
    assert open(bf, encoding="utf-8").read().splitlines() == ["# comment without newline at the end", "Some Channel"]
    # (c) a re-run of the proposals search keeps your approvals and the earlier sheet
    path = os.path.join(d, "official_proposals.csv")
    def cand(key): return dict(key=key, kind="cover", title="t " + key, channel="c", views=1, link="l", duration=100, pool_artist="a")
    def found(key, vid): return (cand(key), dict(entry=dict(id=vid, title="n", channel="x", view_count=5, duration=100), official=False, artist="a", song="s", note="", fallback=False))
    fo.write_proposals(path, [cand("youtube_1")], [found("youtube_1", "vidAAAAAAAA")])
    text = open(path, encoding="utf-8-sig").read().replace("\n" + "," , "\n,", 1)
    rows = list(csv.reader(open(path, encoding="utf-8-sig"))); rows[1][0] = "y"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)                                                                                           # the user approves the row
    fo.write_proposals(path, [cand("youtube_1"), cand("youtube_2")], [found("youtube_1", "vidAAAAAAAA"), found("youtube_2", "vidBBBBBBBB")])
    new = {r["old_key"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}
    assert new["youtube_1"]["approve"] == "y" and new["youtube_2"]["approve"] == "", new                                       # same proposal: approval kept
    fo.write_proposals(path, [cand("youtube_1")], [found("youtube_1", "vidCHANGED00")])
    new = {r["old_key"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}
    assert new["youtube_1"]["approve"] == "", new                                                                              # a different link: not approved any more
    assert len([n for n in os.listdir(d) if n.startswith("official_proposals.csv.") and n.endswith(".bak")]) >= 1
    print("   old songs leave only with a real replacement, the block list stays intact, proposals approvals and earlier sheets are kept")


def add_song_test():
    """add_song.py: hand-picked songs go into their own list, songs already in the pool (or marked out) are skipped, live streams refused."""
    print("\n27. ADDING SINGLE SONGS BY HAND")
    import add_song as asg, csv, os, tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "pool_youtube.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(asg.COLS)
        w.writerow(["youtube", "aaaaaaaaaaa", "In pool", "A", 200, 1, "youtube-standard", "u", "pop", "yt_pop", ""])
        w.writerow(["youtube", "bbbbbbbbbbb", "Marked", "B", 200, 1, "youtube-standard", "u", "pop", "yt_pop", "n"])
    fake = {"ccccccccccc": dict(title="New Song (Official Audio)", channel="Singer - Topic", duration=201.0, views=5000, live=False),
            "ddddddddddd": dict(title="Live now", channel="X", duration=0.0, views=0, live=True),
            "eeeeeeeeeee": dict(title="Two hour mix", channel="Y", duration=7200.0, views=10, live=False)}
    links = ["https://youtu.be/aaaaaaaaaaa", "https://www.youtube.com/watch?v=bbbbbbbbbbb", "https://www.youtube.com/watch?v=ccccccccccc&list=RDx",
             "https://youtu.be/ddddddddddd", "https://youtu.be/eeeeeeeeeee", "hello"]
    p = asg.plan(links, "chiphop", get_info=lambda v: fake[v], here=d)
    notes = {v: (r is not None, n) for v, r, n in p}
    assert notes["aaaaaaaaaaa"] == (False, "already in the pool") and notes["bbbbbbbbbbb"][1].startswith("marked out"), notes
    assert notes["ccccccccccc"][0] and notes["ddddddddddd"] == (False, "a live stream or premiere, not a finished song") and "length 7200" in notes["eeeeeeeeeee"][1], notes
    assert notes["hello"] == (False, "not a YouTube link")
    row = next(r for v, r, _ in p if v == "ccccccccccc")
    assert row["artist"] == "Singer" and row["group"] == "yt_chiphop" and row["listen"].endswith("ccccccccccc")
    assert asg.apply(p, here=d) == 2                                                    # c and e (e only with a warning)
    out = list(csv.DictReader(open(os.path.join(d, asg.LIST), encoding="utf-8-sig")))
    assert [r["track_id"] for r in out] == ["ccccccccccc", "eeeeeeeeeee"] and list(out[0].keys()) == asg.COLS
    assert "pool_handpicked.csv" in __import__("results_index").POOL_LISTS
    p2 = asg.plan(["https://youtu.be/ccccccccccc"], "pop", get_info=lambda v: fake[v], here=d)
    assert p2[0][1] is None and p2[0][2] == "already in the pool"                             # a second run adds nothing
    print("   hand-picked songs go into pool_handpicked.csv; pool songs, marked-out songs and live streams are skipped")


def ai_names_check_test():
    """ai_channels.py --check / --patterns: given channel names are matched to pool channels (exact = blockable, near = check by hand, ? = look only)."""
    print("\n28. CHECKING GIVEN AI CHANNEL NAMES")
    import ai_channels as ac, tag_ai, tempfile, os
    p = os.path.join(tempfile.mkdtemp(), "names.txt")
    open(p, "w", encoding="utf-8").write("# comment\nEchoMuse AI\nRainyCityPop\nLo Fi Study Chill\n?L.Dre\nNot There\n")
    names = ac.read_names(p)
    assert names == [("EchoMuse AI", True), ("RainyCityPop", True), ("Lo Fi Study Chill", True), ("L.Dre", False), ("Not There", True)], names
    pool = {tag_ai.norm_name(n): dict(name=n, keys=["k"] * c) for n, c in [("EchoMuse AI", 5), ("RainyCityPop", 3), ("Lo Fi Study Chill Beats", 2), ("L.Dre", 4), ("Taylor Swift", 9)]}
    lines = []
    found = ac.check(names, pool, set(), {tag_ai.norm_name("RainyCityPop")}, printer=lines.append)
    text = "\n".join(lines)
    assert found == ["EchoMuse AI"], found                                              # blocked already, near match and look-only names are never added
    assert "NEAR MATCH" in text and "look only" in text and "already in ai_block.txt" in text and "not in the pool" in text, text
    assert [n for n, _ in ac.mill_channels(pool, set(), set())] == ["EchoMuse AI", "Lo Fi Study Chill Beats"]
    print("   exact names can be blocked, near matches and ? names are only shown, mood / lofi / AI mill names are listed for reading")


if __name__ == "__main__":
    rhythm_tests()
    trim_and_parts_tests()
    scoring_tests()
    sound_scale_test()
    blind_pairing_test()
    audio_and_safety_tests()
    split_filter_test()
    failure_handling_tests()
    near_copy_test()
    round2_test()
    deezer_discover_test()
    seen_songs_test()
    youtube_scale_test()
    clustered_range_test()
    list_d_and_rule_test()
    pool_duplicates_test()
    ai_tag_check_test()
    replace_songs_test()
    official_versions_test()
    ai_removal_test()
    demo_server_test()
    mark_ai_out_test()
    analysis_fast_test()
    demo_bundle_test()
    demo_hardening_test()
    data_safety_test()
    add_song_test()
    ai_names_check_test()
