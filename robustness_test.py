"""How well does Sound still recognise a song after the damage a real capture does?

  python robustness_test.py              # 100 analysed Jamendo songs, ~20 minutes
  python robustness_test.py --songs 40   # quicker

For each song: download it again into a temporary folder (deleted afterwards), cut 30 seconds from a random
point, damage the clip in the ways a capture would, and check where the song ranks among all analysed songs.
  clean        - the 30 s clip as it is (the best a perfect tab capture could do)
  quiet        - 18 dB quieter (tab played at low volume)
  low bitrate  - high frequencies removed above 8 kHz (heavily compressed stream)
  phone mic    - speaker/microphone band only (150 Hz - 7 kHz) + room echo + background noise at 20 dB
  noisy room   - as phone mic, but noise at 10 dB (a busy room)
  ... + cleaned - the same two, after the light cleaning the app would do (rumble filter, subtracting the
                  room's background sound measured before the song starts, evening out the volume)
Each damaged clip is compared three ways: with the whole-song average only ("whole"), with the whole song or one of
its 3 stored parts ("both", the original rule), and with the whole song or ANY ~30 s stretch ("windows").
Results go to results/robustness.json and are printed as a table.
"""
import argparse, json, os, random
import numpy as np
import analyze, match, sources
from results_index import latest_rows, RES

SR = 16000


def bandpass(a, lo, hi):
    f = np.fft.rfft(a); fr = np.fft.rfftfreq(len(a), 1 / SR)
    f[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(f, len(a)).astype(np.float32)


def room(a, rng, seconds=0.35):
    n = int(seconds * SR); t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t / (seconds / 4)); ir[0] = 1.0; ir /= np.abs(ir).sum() / 4
    L = len(a) + n - 1; m = 1 << (L - 1).bit_length()
    out = np.fft.irfft(np.fft.rfft(a, m) * np.fft.rfft(ir, m), m)[: len(a)]
    return (out / (np.abs(out).max() + 1e-9) * np.abs(a).max()).astype(np.float32)


def add_noise(a, snr_db, rng):
    # pinkish background noise (falls off with frequency, like a room)
    w = rng.standard_normal(len(a)); f = np.fft.rfft(w); fr = np.fft.rfftfreq(len(a), 1 / SR)
    f[1:] /= np.sqrt(fr[1:]); n = np.fft.irfft(f, len(a))
    ps, pn = np.mean(a ** 2), np.mean(n ** 2) + 1e-12
    return (a + n * np.sqrt(ps / pn / 10 ** (snr_db / 10))).astype(np.float32)


def _stft(a, n=1024, hop=256):
    w = np.hanning(n); fr = range(0, max(len(a) - n, 0) + 1, hop)
    return np.stack([np.fft.rfft(a[i:i + n] * w) for i in fr]), w


def _istft(S, w, length, n=1024, hop=256):
    out = np.zeros(length); norm = np.zeros(length)
    for k, i in enumerate(range(0, S.shape[0] * hop, hop)):
        out[i:i + n] += np.fft.irfft(S[k], n) * w; norm[i:i + n] += w ** 2
    return (out / np.maximum(norm, 1e-8)).astype(np.float32)


def clean_up(a, room_noise):
    """The light cleaning the app would do: remove rumble below 80 Hz, subtract the room's background sound
    (measured from 2 s of 'silence' recorded before the song starts), then even out the volume."""
    a = bandpass(a, 80, SR / 2)
    S, w = _stft(a); N, _ = _stft(bandpass(room_noise, 80, SR / 2))
    noise = np.abs(N).mean(axis=0)
    mag = np.abs(S); keep = np.maximum(mag - 1.5 * noise, 0.1 * mag)      # never remove more than 90%
    out = _istft(keep * np.exp(1j * np.angle(S)), w, len(a))
    return (out / (np.sqrt(np.mean(out ** 2)) + 1e-9) * 0.1).astype(np.float32)


def level(a, target_rms=0.2):
    """Even out the volume only (RMS to -14 dBFS, about a finished release; peaks kept below clipping): tests how much loudness alone matters."""
    out = a / (np.sqrt(np.mean(a ** 2)) + 1e-9) * target_rms
    pk = np.abs(out).max()
    return (out / pk * 0.99 if pk > 0.99 else out).astype(np.float32)


def noisy(mic, snr_db, rng):
    """Returns (noisy clip, a separate 2 s recording of the same room noise)."""
    both = add_noise(np.concatenate([np.zeros(2 * SR, np.float32), mic]), snr_db, rng)
    return both[2 * SR:], both[: 2 * SR] - 0.0


def versions(clip, rng):
    mic = room(bandpass(clip, 150, 7000), rng)
    m20, n20 = noisy(mic, 20, rng); m10, n10 = noisy(mic, 10, rng)
    quiet_ = (clip * 10 ** (-18 / 20)).astype(np.float32)
    return {"clean": clip, "quiet": quiet_, "low bitrate": bandpass(clip, 0, 8000),
            "quiet + level": level(quiet_), "phone mic": m20, "phone mic + level": level(m20),
            "phone mic + cleaned": clean_up(m20, n20),
            "noisy room": m10, "noisy room + cleaned": clean_up(m10, n10)}


METHODS = ("whole", "both", "windows")   # whole song only / whole or 3 parts / whole or any 30 s stretch


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--songs", type=int, default=100); a = ap.parse_args()
    rng = np.random.default_rng(7); random.seed(7)
    keys = match.library()[0]
    rows = latest_rows(RES)
    cand = [k for k in keys if k.startswith("jamendo_") and float(rows[k].get("trimmed_duration") or rows[k].get("file_duration") or 999) >= 60]
    random.shuffle(cand)
    effnet = analyze._model("effnet"); es = analyze._es()
    match.windows()                        # build the sliding-window index before timing anything
    res = {}; ovl = {}; done = 0
    print(f"library: {len(keys)} analysed songs; testing up to {a.songs} of them")
    for k in cand:
        if done >= a.songs:
            break
        jid = int(k.split("_", 1)[1])
        info = sources.jamendo_tracks([jid]).get(jid)
        if not info:
            continue
        try:
            with sources.temp_audio(info) as p:
                a16 = es.MonoLoader(filename=p, sampleRate=SR, resampleQuality=1)()
        except Exception as e:
            print(f"  skip {k}: {e}"); continue
        if len(a16) < 45 * SR:
            continue
        st = rng.integers(int(5 * SR), len(a16) - 32 * SR)
        clip = np.asarray(a16[st: st + 30 * SR], np.float32)
        line = []
        lib_keys, _, W, _ = match.library()
        t = lib_keys.index(k)
        true_top = set(match.rank(W[t], exclude={k}, prepared=True)[0][:20].tolist())     # the real song's 20 closest songs
        for name, v in versions(clip, rng).items():
            emb = np.asarray(effnet(v))
            for method in METHODS:
                order, _ = match.rank(emb, method=method)
                pos = match.position_of(k, order)
                res.setdefault(f"{name} | {method}", []).append(pos)
                if method == "both":
                    near = [i for i in order if i != t][:20]
                    ovl.setdefault(name, []).append(len(true_top & set(near)) / 20)
                if method == "windows":
                    line.append(f"{name} #{pos}")
        done += 1
        print(f"  {done:3d} {k:18s} " + ", ".join(line))
    print(f"\n{'condition | compared with':34s} {'found #1':>9s} {'top 10':>7s} {'median place':>13s}   (n={done}, library {len(keys)})")
    summary = {}
    for name, p in res.items():
        p = np.array(p)
        summary[name] = dict(found_first=round(float(np.mean(p == 1)), 3), top10=round(float(np.mean(p <= 10)), 3),
                             median_place=float(np.median(p)), n=int(len(p)))
        print(f"{name:34s} {summary[name]['found_first']*100:8.0f}% {summary[name]['top10']*100:6.0f}% {summary[name]['median_place']:13.0f}")
    print("\nWould the RECOMMENDATIONS still be right? Share of the real song's 20 closest songs that the clip also")
    print("puts in its 20 closest (compared with whole song or 3 parts). Random would be about 0%.")
    overlap = {}
    for name, v in ovl.items():
        overlap[name] = round(float(np.mean(v)), 3)
        print(f"  {name:22s} {100 * overlap[name]:5.0f}%")
    with open(os.path.join(RES, "robustness.json"), "w") as f:
        json.dump(dict(library=len(keys), summary=summary, neighbour_overlap=overlap), f, indent=1)
    print("\nsaved results/robustness.json")


if __name__ == "__main__":
    main()
