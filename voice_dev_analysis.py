"""Voice DEVELOPMENT analysis (VOICE_PIPELINE.md sections 4-5). Uses ONLY the train-split songs of voice_dev.csv.
Nothing from the sealed test split is read here, so settings can be chosen freely; they are frozen afterwards.

  python voice_dev_analysis.py                  # Voice alone: which model / stem or mix / window mean / rescaling / gate
  python voice_dev_analysis.py --with-sound     # + the dry run of the real test: Sound alone vs Sound + Voice
                                                #   (needs the dev songs analysed by run_tests.py --list voice_dev.csv)

Question (the same as the sealed test): for a song whose artist has a song on a DIFFERENT album in the library, is that
song in the top 10? Candidates exclude the song itself and songs of the same artist AND album. Hit = in the top 10.
Writes voice_dev_report.md, voice_dev_summary.json and (the best settings, NOT yet frozen) voice_dev_choice.json.
Runs in the main .venv (numpy only).
"""
import argparse, csv, itertools, json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VRES = os.path.join(HERE, "results", "voice")
MODELS = ["byol", "contrastive", "contrastive-vc", "unif-align", "vicreg"]
SOURCES = ["stem", "mix"]
AGGS = ["all", "top5", "top3"]                       # which windows are averaged: all 8, the 5 / 3 with the most singing
SCALES = {"none": None, "centre": 0.0, "spread^0.25": 0.25, "z-score": 1.0}
GATES = [None, -55.0, -50.0, -45.0, -40.0, -35.0]    # mean vocal level (dB) of the 3 most-sung windows
rng = np.random.default_rng(20261007)


def unit(X):
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)


# ------------------------------------------------------------------ loading
def load(list_csv="voice_dev.csv"):
    rows = list(csv.DictReader(open(os.path.join(HERE, list_csv), encoding="utf-8-sig")))
    meta = {f"jamendo_{r['jamendo_id']}": r for r in rows}
    S = []
    for key, r in meta.items():
        p = os.path.join(VRES, f"{key}.npz")
        if not os.path.exists(p):
            continue
        try:
            d = np.load(p)
            if len(d["win_start"]) == 0:
                continue
            ws, w = d["win_start"], float(d["win_s"])
            vdb = d["vocal_db"].astype(np.float32)
            lvl = np.array([vdb[int(s): int(s + w)].mean() for s in ws])            # singing level of each window
            S.append(dict(key=key, artist=r["artist"], album=r["album"], group=r["group"], lvl=lvl,
                          stem=d["emb_stem"].astype(np.float32), mix=d["emb_mix"].astype(np.float32)))
        except Exception as e:
            print(f"  skipped {key}: {e}")
    return S


def gate_level(s):
    return float(np.sort(s["lvl"])[::-1][:3].mean())


def song_vectors(S, model, source, agg):
    """(n, d): mean of the unit-length window vectors; model 'all5' = the five models' vectors joined."""
    out = []
    for s in S:
        order = np.argsort(-s["lvl"])
        k = {"all": len(order), "top5": 5, "top3": 3}[agg]
        sel = order[:k]
        E = s[source][sel]                                                          # (k, 5, 1000)
        # a window with a broken number (an fp16 overflow on a near-silent stem happened once) is skipped, otherwise one
        # song would turn every rescaled comparison of that model into NaN
        ok = np.isfinite(E).all(axis=(1, 2)) if model == "all5" else np.isfinite(E[:, MODELS.index(model)]).all(axis=1)
        E = E[ok]
        if len(E) == 0:
            out.append(np.zeros(5000 if model == "all5" else 1000, np.float32))
            continue
        if model == "all5":
            parts = [unit(E[:, m]).mean(0) for m in range(len(MODELS))]
            out.append(np.concatenate([p / (np.linalg.norm(p) + 1e-9) for p in parts]))
        else:
            out.append(unit(E[:, MODELS.index(model)]).mean(0))
    return np.stack(out)


def rescale(V, power):
    if power is None:
        return V
    return (V - V.mean(0)) / ((V.std(0) + 1e-6) ** power)


# ------------------------------------------------------------------ the question
class Questions:
    def __init__(self, S, keep=None):
        keep = np.ones(len(S), bool) if keep is None else keep
        self.idx = np.where(keep)[0]
        art = np.array([S[i]["artist"] for i in self.idx])
        alb = np.array([S[i]["album"] for i in self.idx])
        same_a = art[:, None] == art[None, :]
        same_alb = alb[:, None] == alb[None, :]
        eye = np.eye(len(self.idx), dtype=bool)
        self.valid = ~eye & ~(same_a & same_alb)                                    # allowed candidates
        self.partner = same_a & ~same_alb                                           # the answers
        self.q = np.where(self.partner.any(1))[0]                                   # songs that have an answer
        self.artist = art[self.q]

    def score(self, sim, extra_exclude=None):
        """sim (n, n) in library order. Returns per-question hit@10 and reciprocal rank of the best answer."""
        valid = self.valid if extra_exclude is None else self.valid & ~extra_exclude
        s = np.where(valid, sim, -np.inf)
        bp = np.where(self.partner & valid, s, -np.inf).max(1)
        rank = (s > bp[:, None]).sum(1)
        ok = np.isfinite(bp)
        hit = (rank < 10) & ok
        rr = np.where(ok, 1.0 / (rank + 1), 0.0)
        return hit[self.q].astype(float), rr[self.q]


def boot_ci(vals, artists, reps=1000, paired=None):
    """95% range of the mean over questions, resampling ARTISTS (their songs are not independent)."""
    ua, inv = np.unique(artists, return_inverse=True)
    sums = np.bincount(inv, weights=vals if paired is None else vals - paired, minlength=len(ua))
    cnt = np.bincount(inv, minlength=len(ua)).astype(float)
    m = rng.integers(0, len(ua), size=(reps, len(ua)))
    est = sums[m].sum(1) / cnt[m].sum(1)
    return float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def cos_sim(V):
    U = unit(V)
    return U @ U.T


def random_hit(Q, reps=20):
    h = []
    for _ in range(reps):
        h.append(Q.score(rng.normal(size=Q.valid.shape))[0].mean())
    return float(np.mean(h))


# ------------------------------------------------------------------ main analyses
def sweep(S, Q):
    configs = []
    for model, source, agg, scale in itertools.product(MODELS + ["all5"], SOURCES, AGGS, SCALES):
        V = rescale(song_vectors(S, model, source, agg)[Q.idx], SCALES[scale])
        hit, rr = Q.score(cos_sim(V))
        configs.append(dict(model=model, source=source, agg=agg, scale=scale, hit=hit, rr=rr))
    return configs


def marginals(configs, factor):
    levels = sorted({c[factor] for c in configs}, key=lambda x: [c[factor] for c in configs].index(x))
    return {lv: float(np.mean([c["hit"].mean() for c in configs if c[factor] == lv])) for lv in levels}


def split_half_optimism(configs, artists, reps=200):
    """Choose the best of all configs on half the ARTISTS, score it on the other half: how much of the best score is luck?"""
    ua = np.unique(artists)
    res = []
    H = np.stack([c["hit"] for c in configs])                                       # (configs, questions)
    for _ in range(reps):
        a = set(rng.permutation(ua)[: len(ua) // 2])
        mA = np.array([x in a for x in artists])
        best = int(np.argmax(H[:, mA].mean(1)))
        res.append((H[best, ~mA].mean(), H[:, ~mA].mean(), H[best, mA].mean()))
    r = np.array(res)
    return dict(chosen_on_A_scored_on_B=float(r[:, 0].mean()), average_config_on_B=float(r[:, 1].mean()),
                chosen_on_A_scored_on_A=float(r[:, 2].mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="voice_dev.csv")
    ap.add_argument("--with-sound", action="store_true")
    ap.add_argument("--force", nargs=4, metavar=("MODEL", "SOURCE", "WINDOWS", "RESCALING"),
                    help="use these settings instead of the best Voice-alone ones (writes voice_dev_report_forced.md only)")
    a = ap.parse_args()
    t0 = time.time()
    S = load(a.list)
    if len(S) < 50:
        sys.exit(f"only {len(S)} songs have Voice numbers yet: wait for run_voice.py to finish")
    out = []
    P = lambda *x: (print(*x), out.append(" ".join(str(i) for i in x)))
    Q = Questions(S)
    n_art = len(set(Q.artist))
    P("# Voice development analysis (train split only)\n")
    P(f"Library: {len(S)} songs with Voice numbers. Questions: {len(Q.q)} songs of {n_art} artists that have a song on a "
      f"different album in the library. (Test needs about 250 questions.)")
    rh = random_hit(Q)
    P(f"Random ranking would put an answer in the top 10 for {rh * 100:.1f}% of questions (library of {len(S)}).\n")

    configs = sweep(S, Q)
    H = np.stack([c["hit"] for c in configs])
    P(f"## Settings compared ({len(configs)} combinations: 5 models + all5 x stem/mix x window mean x rescaling)\n")
    for fac, title in (("model", "Singer model"), ("source", "Vocals separated (stem) or original mix"),
                       ("agg", "Windows averaged"), ("scale", "Rescaling")):
        m = marginals(configs, fac)
        P(f"- **{title}** (average hit@10 over the other settings): " + ", ".join(f"{k} {v * 100:.1f}%" for k, v in m.items()))
    order = np.argsort(-H.mean(1))
    P("\n### Best 8 combinations (hit@10 = answer in the top 10; 95% range over artists)\n")
    P("| model | source | windows | rescaling | hit@10 | 95% range | mean reciprocal rank |\n|---|---|---|---|---|---|---|")
    for i in order[:8]:
        c = configs[i]
        lo, hi = boot_ci(c["hit"], Q.artist)
        P(f"| {c['model']} | {c['source']} | {c['agg']} | {c['scale']} | {c['hit'].mean() * 100:.1f}% | "
          f"{lo * 100:.1f}-{hi * 100:.1f}% | {c['rr'].mean():.3f} |")
    opt = split_half_optimism(configs, Q.artist)
    P(f"\nHonest estimate: choosing the best combination on half the artists and scoring it on the other half gives "
      f"{opt['chosen_on_A_scored_on_B'] * 100:.1f}% (the same choice scored on the half it was chosen on: "
      f"{opt['chosen_on_A_scored_on_A'] * 100:.1f}%; the average combination: {opt['average_config_on_B'] * 100:.1f}%). "
      "The gap is how much of the best score is luck of the choice.")

    best = configs[int(order[0])]
    if a.force:
        m, so, ag, sc = a.force
        best = next(c for c in configs if (c["model"], c["source"], c["agg"], c["scale"]) == (m, so, ag, sc))
        P(f"\n**Settings forced by hand: {m} / {so} / {ag} / {sc} (Voice-alone hit@10 {best['hit'].mean() * 100:.1f}%)**")
    V = rescale(song_vectors(S, best["model"], best["source"], best["agg"]), SCALES[best["scale"]])

    # ---- the singing gate on the best settings
    lv = np.array([gate_level(s) for s in S])
    P("\n## Singing gate (mean vocal level of the 3 most-sung windows, dB)\n")
    hist, edges = np.histogram(lv, bins=[-100, -70, -60, -55, -50, -45, -40, -35, -30, -20, 0])
    P("Songs per level band: " + ", ".join(f"{int(e0)}..{int(e1)}: {h}" for h, e0, e1 in zip(hist, edges[:-1], edges[1:])))
    P("\n| gate (songs below it get no Voice) | songs kept | questions | hit@10 | 95% range |\n|---|---|---|---|---|")
    gate_rows = []
    for g in GATES:
        keep = np.ones(len(S), bool) if g is None else lv >= g
        Qg = Questions(S, keep)
        if len(Qg.q) < 30:
            continue
        Vg = V[Qg.idx]
        hit, _ = Qg.score(cos_sim(Vg))
        lo, hi = boot_ci(hit, Qg.artist)
        gate_rows.append((g, int(keep.sum()), len(Qg.q), hit.mean(), lo, hi))
        P(f"| {'none' if g is None else f'{g:.0f} dB'} | {int(keep.sum())} | {len(Qg.q)} | {hit.mean() * 100:.1f}% | "
          f"{lo * 100:.1f}-{hi * 100:.1f}% |")
    P("\nA higher gate removes quiet or instrumental songs: hit@10 rises partly because the question set changes, so "
      "the gate is chosen for coverage first (keep the songs that really are sung) and accuracy second.")

    summary = dict(library=len(S), questions=int(len(Q.q)), artists=int(n_art), random_hit=rh, best=dict(
        model=best["model"], source=best["source"], agg=best["agg"], scale=best["scale"], hit=float(best["hit"].mean()),
        ci=boot_ci(best["hit"], Q.artist)), optimism=opt,
        marginals={f: marginals(configs, f) for f in ("model", "source", "agg", "scale")},
        gate=[dict(gate=g, songs=n, questions=q, hit=h) for g, n, q, h, _, _ in gate_rows])

    # ---- dry run of the real test: Sound alone vs Sound + Voice
    if a.with_sound:
        summary["with_sound"] = sound_comparison(S, Q, V, P)
    if a.force:
        open(os.path.join(HERE, "voice_dev_report_forced.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
        print("\n(forced settings: wrote voice_dev_report_forced.md only; the choice and summary files are untouched)")
        return
    json.dump(summary, open(os.path.join(HERE, "voice_dev_summary.json"), "w"), indent=1, default=float)
    json.dump(dict(model=best["model"], source=best["source"], windows=best["agg"], rescaling=best["scale"],
                   note="chosen on development songs only; NOT frozen yet (needs voice_freeze.json before the test)",
                   made=time.strftime("%Y-%m-%d %H:%M")), open(os.path.join(HERE, "voice_dev_choice.json"), "w"), indent=1)
    open(os.path.join(HERE, "voice_dev_report.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"\n(done in {time.time() - t0:.0f}s: voice_dev_report.md, voice_dev_summary.json, voice_dev_choice.json)")


def sound_comparison(S, Q, V, P):
    """Dry run of the sealed test protocol on development songs: needs the dev songs analysed by run_tests.py."""
    import scoring, match
    sc = match.sound_scale()
    X, have = [], np.zeros(len(S), bool)
    for i, s in enumerate(S):
        p = os.path.join(HERE, "results", f"{s['key']}.npz")
        if os.path.exists(p):
            with np.load(p) as d:
                if "effnet_whole" in d.files:
                    X.append(scoring.scale_sound(np.asarray(d["effnet_whole"], np.float32), sc)); have[i] = True
    P(f"\n## Sound alone vs Sound + Voice (dry run of the test; {int(have.sum())} of {len(S)} songs have Sound numbers)\n")
    if have.sum() < 100:
        P("Not enough dev songs have Sound numbers yet: run `python -u run_tests.py --list voice_dev.csv` first.")
        return {}
    Qs = Questions(S, have)
    Xs = np.stack(X)
    Vs = V[Qs.idx]
    sound = cos_sim(Xs)
    near = sound >= 0.97                                                            # same recording on two releases
    voice = cos_sim(Vs)
    n = len(Qs.idx)

    def pct(sim):
        return np.stack([scoring.to_percentile(sim[i], exclude=np.arange(n) == i) for i in range(n)])
    Ps, Pv = pct(sound), pct(voice)
    both = (Ps + Pv) / 2
    floor_ok = (Ps >= 65) & (Pv >= 65)
    with_floor = np.where(floor_ok, both + 1000.0, both)                            # songs clearing both floors rank first
    res = {}
    for name, sim in (("Sound alone", sound), ("Voice alone", voice), ("Sound + Voice (equal weight)", both),
                      ("Sound + Voice (equal weight, 65% floor)", with_floor)):
        hit, rr = Qs.score(sim, extra_exclude=near)
        res[name] = (hit, rr)
    base = res["Sound alone"][0]
    P(f"Questions: {len(Qs.q)} (artists: {len(set(Qs.artist))}); near-copies (Sound >= 0.97) excluded as in the test rules.\n")
    P("| ranking | hit@10 | 95% range | gain vs Sound alone | 95% range of the gain | mean reciprocal rank |\n|---|---|---|---|---|---|")
    out = {}
    for name, (hit, rr) in res.items():
        lo, hi = boot_ci(hit, Qs.artist)
        glo, ghi = boot_ci(hit, Qs.artist, paired=base) if name != "Sound alone" else (0, 0)
        gain = (hit - base).mean()
        P(f"| {name} | {hit.mean() * 100:.1f}% | {lo * 100:.1f}-{hi * 100:.1f}% | "
          f"{'' if name == 'Sound alone' else f'{gain * 100:+.1f} pts'} | "
          f"{'' if name == 'Sound alone' else f'{glo * 100:+.1f} to {ghi * 100:+.1f}'} | {rr.mean():.3f} |")
        out[name] = dict(hit=float(hit.mean()), gain=float(gain), gain_ci=[glo, ghi])
    P("\nRule for the sealed test: keep Voice if the paired gain is at least +10 points and its 95% range stays above 0.")
    return out


if __name__ == "__main__":
    main()
