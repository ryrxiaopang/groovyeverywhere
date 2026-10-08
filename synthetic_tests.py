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
    import contextlib, glob, io, subprocess, tempfile, time
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
