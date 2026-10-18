"""Step 2 of testing: read results/*.npz and write report.html with PASS / WARN / FAIL per test.

  python evaluate.py            -> report.html (open in a browser)

Tests (each answers one question from the mentor):
  T0 Data       – how many songs worked, full-length rate, time per song on this machine
  T1 Mood       – are loud-happy and loud-sad songs told apart? (and does it beat plain loudness?)
  T2 Sound      – does Sound separate styles while Mood keeps same-mood songs together?
  T3 Instruments– is the expected instrument near the top? can 'voice' detect singing?
  T4 Rhythm     – is beat confidence low for beatless songs? how often is speed halved/doubled?
  T5 Parts      – 30 s clip test: whole-song average vs best of 3 parts vs both
  T6 Overlap    – do two features secretly measure the same thing?
  T7 Same artist– does Sound alone find another album by the same artist? (Voice baseline C)
  T8 Earn place – adding features one at a time: does each one help its own tags?
  T9 Examples   – full recommendations for 3 songs with reasons
"""
from __future__ import annotations
import base64, csv, html, io, json, os, random
import numpy as np
import scoring

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
rng = random.Random(1)

# ------------------------------------------------------------------ loading
def load():
    from results_index import latest_rows
    rows = latest_rows(RES)                    # latest row per song; a finished analysis is never hidden
    # songs you listened to and marked i_agree = n in edge_cases.csv leave their group (labels are crowd tags)
    vetoed = set()
    ec = os.path.join(HERE, "edge_cases.csv")
    if os.path.exists(ec):
        with open(ec, encoding="utf-8-sig") as f:
            vetoed = {f"jamendo_{r['jamendo_id']}" for r in csv.DictReader(f) if r.get("i_agree", "").strip().lower() in ("n", "no")}
    for k in vetoed & set(rows):
        rows[k]["group"] = rows[k]["group"] + "_vetoed"
    songs = []
    for k, r in rows.items():
        p = os.path.join(RES, f"{k}.npz")
        if r["status"] == "done" and os.path.exists(p):
            try:
                d = dict(np.load(p, allow_pickle=False))
            except Exception:
                print(f"  skipped a damaged file: {k} (run python check_results.py --fix)")
                continue
            songs.append({"key": k, "meta": r, **d})
    rescale_sound(songs)
    return rows, songs


_SC = None


def rescale_sound(songs):
    """Every Sound comparison in this report uses the rescaled numbers (match.sound_scale(), the same scale the app
    uses): each of the 1,280 numbers minus the pool's average, divided by its spread. The straight-line change keeps
    the 3 parts and the clip averages consistent; the original numbers stay in effnet_whole_raw (the own mood model
    was trained on those)."""
    global _SC
    import match
    _SC = match.sound_scale()
    for s in songs:
        s["effnet_whole_raw"] = s["effnet_whole"]
        s["effnet_whole"] = scoring.scale_sound(s["effnet_whole"], _SC)
        s["effnet_parts"] = scoring.scale_sound(s["effnet_parts"], _SC)


def mtg_test_ids():
    """Jamendo song keys in the official MTG-Jamendo TEST split (the sealed split)."""
    p = os.path.join(HERE, "data", "split0-autotagging-test.tsv")
    with open(p) as f:
        next(f)
        # the file writes ids zero-padded (track_0000214); the analysed songs are keyed jamendo_214
        return {"jamendo_" + str(int(line.split("\t")[0].split("_")[1])) for line in f}


def class_names(name, n):
    try:
        import models
        return [c.lower().replace(" ", "").replace("_", "") for c in models.classes(name)]
    except Exception:
        return [f"{name}_{i}" for i in range(n)]


def mtg_tags():
    """jamendo_id -> {'genre':set,'mood':set,'inst':set} from the MTG-Jamendo validation AND test splits (a song is in
    only one split, so there is no overlap; --split chooses which songs are scored, not which tags are read)."""
    out = {}
    for fn in ("split0-autotagging-validation.tsv", "split0-autotagging-test.tsv"):
        p = os.path.join(HERE, "data", fn)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            next(f)
            for line in f:
                x = line.rstrip("\n").split("\t")
                jid = int(x[0].split("_")[1]); t = x[5:]
                out[jid] = {"genre": {s.split("---")[1] for s in t if s.startswith("genre")},
                            "mood": {s.split("---")[1] for s in t if s.startswith("mood")},
                            "inst": {s.split("---")[1] for s in t if s.startswith("instrument")}}
    return out


# ------------------------------------------------------------------ small stats helpers
def auc(pos, neg):
    """Chance a random 'pos' value is bigger than a random 'neg' value (0.5 = coin flip)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    gt = (pos[:, None] > neg[None, :]).mean(); eq = (pos[:, None] == neg[None, :]).mean()
    return gt + eq / 2


def auc_range(pos, neg, n=1000, seed=0):
    """95% range for auc(pos, neg): resample the songs with replacement 1,000 times."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    pos, neg = pos[~np.isnan(pos)], neg[~np.isnan(neg)]
    if len(pos) < 3 or len(neg) < 3:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    v = [auc(rng.choice(pos, len(pos)), rng.choice(neg, len(neg))) for _ in range(n)]
    return tuple(float(x) for x in np.percentile(v, [2.5, 97.5]))


def rate_range(hits, n=1000, seed=0):
    """95% range for a hit rate (list of True/False)."""
    h = np.asarray(hits, float)
    if len(h) < 3:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    return tuple(float(x) for x in np.percentile([rng.choice(h, len(h)).mean() for _ in range(n)], [2.5, 97.5]))


def paired_auc_win(a, b, lab, n=1000, seed=0):
    """Share of resamples (same songs for both) in which score a separates lab better than score b."""
    a, b, lab = np.asarray(a, float), np.asarray(b, float), np.asarray(lab, bool)
    rng = np.random.default_rng(seed); wins = 0; idx = np.arange(len(lab))
    for _ in range(n):
        i = rng.choice(idx, len(idx)); L = lab[i]
        if L.all() or (~L).all():
            continue
        wins += auc(a[i][L], a[i][~L]) > auc(b[i][L], b[i][~L])
    return wins / n


def rng_txt(r):
    return "" if np.isnan(r[0]) else f"{r[0]:.2f}–{r[1]:.2f}"


def either_way(a):
    return max(a, 1 - a) if not np.isnan(a) else a


def ranks(x):
    o = np.argsort(x, kind="mergesort"); r = np.empty(len(x)); r[o] = np.arange(len(x)); return r


def spearman(x, y):
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 5:
        return np.nan
    return float(np.corrcoef(ranks(x[m]), ranks(y[m]))[0, 1])


def verdict(ok, warn=None):
    if ok is None:
        return "SKIP"
    return "PASS" if ok else ("WARN" if warn else "FAIL")


def fig_to_img(fig):
    b = io.BytesIO(); fig.savefig(b, format="png", dpi=110, bbox_inches="tight"); b.seek(0)
    import matplotlib.pyplot as plt; plt.close(fig)
    return f'<img src="data:image/png;base64,{base64.b64encode(b.read()).decode()}" style="max-width:100%">'


# ------------------------------------------------------------------ report builder
class Report:
    def __init__(self): self.parts = []; self.summary = []
    def h(self, t): self.parts.append(f"<h2>{html.escape(t)}</h2>")
    def p(self, t): self.parts.append(f"<p>{t}</p>")
    def v(self, name, result, detail):
        self.summary.append((name, result, detail))
        self.parts.append(f'<p class="v {result}"><b>{result}</b> — {html.escape(name)}: {html.escape(detail)}</p>')
    def table(self, header, rows):
        s = "<table><tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in header) + "</tr>"
        for r in rows:
            s += "<tr>" + "".join(f"<td>{html.escape(fmt(c))}</td>" for c in r) + "</tr>"
        self.parts.append(s + "</table>")
    def img(self, tag): self.parts.append(tag)
    def write(self, path):
        css = """body{font-family:system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#222}
        table{border-collapse:collapse;margin:8px 0 16px}td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px}
        th{background:#f3f3f3}.v{padding:6px 10px;border-radius:6px}.PASS{background:#e5f5e8}.WARN{background:#fff4d6}
        .FAIL{background:#fde4e4}.SKIP{background:#eee}h2{margin-top:32px;border-bottom:1px solid #ddd}"""
        top = "<h1>groovyeverywhere – edge-case test report</h1>" + "<table><tr><th>Test</th><th>Result</th><th>Detail</th></tr>" + \
              "".join(f'<tr><td>{html.escape(a)}</td><td class="{b}">{b}</td><td>{html.escape(c)}</td></tr>' for a, b, c in self.summary) + "</table>"
        with open(path, "w") as f:
            f.write(f"<!doctype html><meta charset=utf-8><title>Edge-case report</title><style>{css}</style>{top}{''.join(self.parts)}")


def fmt(c):
    if isinstance(c, (float, np.floating)):
        return "–" if np.isnan(c) else f"{c:.2f}"
    return str(c)


# ------------------------------------------------------------------ tests
def group(songs, *names):
    return [s for s in songs if s["meta"].get("group") in names]


_CLS = {}


def cls_index(head, name, default):
    """Column of class `name` in a head's output, read from the model .json (falls back to default)."""
    if head not in _CLS:
        try:
            import models
            _CLS[head] = [c.lower() for c in models.classes(head)]
        except Exception:
            _CLS[head] = None
    c = _CLS[head]
    return c.index(name) if c and name in c else default


def va(s, model="emomusic", part=None):
    """Returns [valence, arousal] whatever order the model outputs them in."""
    if model == "emomusic_vggish":
        v = s["cand_emomusic_vggish_whole"]
    else:
        v = s[f"{model}_whole"] if part is None else s[f"{model}_parts"][part]
    return np.array([v[cls_index(model, "valence", 0)], v[cls_index(model, "arousal", 1)]])


# The chosen mood model (picked by T14 on 3 Oct 2026): VGGish -> emoMusic. Songs analysed before it existed
# fall back to the original MusiCNN -> emoMusic model.
MOOD_MODEL = "emomusic_vggish"


def mood_va(s):
    return va(s, MOOD_MODEL) if "cand_emomusic_vggish_whole" in s else va(s)


def head_p(s, head, name):
    return float(s[f"{head}_whole"][cls_index(head, name, 0)])


def t0_data(R, rows, songs):
    R.h("T0 · Data and timing")
    st = {}
    for r in rows.values():
        st[r["status"]] = st.get(r["status"], 0) + 1
    R.table(["status", "songs"], sorted(st.items()))
    fl = [s["meta"]["full_length_ok"] for s in songs if s["meta"].get("full_length_ok") in ("True", "False")]
    rate = np.mean([x == "True" for x in fl]) if fl else np.nan
    keys = ["t_decode", "t_effnet", "t_effnet_heads", "t_mood", "t_rhythm", "t_total"]
    tm = {k: np.nanmean([float(s["meta"][k]) for s in songs if s["meta"].get(k)]) for k in keys}
    R.table(["step", "seconds per song (mean)"], [(k[2:], tm[k]) for k in keys])
    per = tm["t_total"]
    R.p(f"At this speed, 1,000 songs ≈ <b>{per*1000/3600:.1f} hours</b> of analysis on this machine "
        f"(plus download time). Voice/Demucs is not included.")
    R.v("Full-length check", verdict(None if np.isnan(rate) else rate >= 0.95, rate >= 0.85 if not np.isnan(rate) else None),
        f"{rate*100:.0f}% of downloads match the listed length ±3 s (n={len(fl)})" if fl else "no listed lengths")


def t1_mood(R, songs):
    R.h("T1 · Mood: loud-happy vs loud-sad (the mentor's question)")
    LH, LS = group(songs, "mood_loud_happy"), group(songs, "mood_loud_sad_dark")
    QH, QS = group(songs, "mood_quiet_happy"), group(songs, "mood_quiet_sad")
    if min(len(LH), len(LS)) < 4:
        R.v("Mood corners", "SKIP", "need ≥4 songs in each loud group"); return
    rows = []
    best = {}
    for m in ("emomusic", "deam", "emomusic_vggish"):
        key = "cand_emomusic_vggish_whole" if m == "emomusic_vggish" else f"{m}_whole"
        if not all(key in s for s in LH + LS + QH + QS):
            continue
        v_lh = [va(s, m)[0] for s in LH]; v_ls = [va(s, m)[0] for s in LS]
        a_loud = [va(s, m)[1] for s in LH + LS]; a_quiet = [va(s, m)[1] for s in QH + QS]
        rows.append((m, "happiness (valence): loud-happy > loud-sad", auc(v_lh, v_ls)))
        if QH and QS:
            rows.append((m, "happiness (valence): quiet-happy > quiet-sad", auc([va(s, m)[0] for s in QH], [va(s, m)[0] for s in QS])))
        if a_quiet:
            rows.append((m, "energy (arousal): loud > quiet", auc(a_loud, a_quiet)))
        best[m] = auc(v_lh, v_ls)
    loud = either_way(auc([s["rhythm_loudness_db"] for s in LH], [s["rhythm_loudness_db"] for s in LS]))
    rows.append(("baseline", "plain loudness (either direction): loud-happy vs loud-sad", loud))
    if "mood_happy_whole" in LH[0]:
        hs = lambda s: head_p(s, "mood_happy", "happy") - head_p(s, "mood_sad", "sad")
        rows.append(("yes/no heads", "P(happy) − P(sad): loud-happy > loud-sad", auc([hs(s) for s in LH], [hs(s) for s in LS])))
        rows.append(("yes/no heads", "P(aggressive): loud-sad > loud-happy",
                     auc([head_p(s, "mood_aggressive", "aggressive") for s in LS], [head_p(s, "mood_aggressive", "aggressive") for s in LH])))
    R.table(["model", "check", "score (0.5 = coin flip, 1 = perfect)"], rows)
    m = max(best, key=best.get) if best else None
    if m:
        a = best[m]
        r95 = auc_range([va(s, m)[0] for s in LH], [va(s, m)[0] for s in LS])
        R.v("Mood tells loud-happy from loud-sad", verdict(a >= 0.75 and a >= loud + 0.10, a >= 0.62),
            f"best valence score {a:.2f} (95% range {rng_txt(r95)}, {m}) vs loudness-only {loud:.2f}. "
            f"Pass = ≥0.75 and ≥0.10 above loudness")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 5))
    for g, c in (("mood_loud_happy", "tab:orange"), ("mood_loud_sad_dark", "tab:purple"),
                 ("mood_quiet_happy", "gold"), ("mood_quiet_sad", "tab:blue")):
        pts = np.array([mood_va(s) for s in group(songs, g)])
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 1], c=c, label=g.replace("mood_", ""), s=40, alpha=.8)
    ax.set_xlabel("happiness (valence, 1–9)"); ax.set_ylabel("energy (arousal, 1–9)"); ax.legend(); ax.set_title("emoMusic mood graph")
    R.img(fig_to_img(fig))
    R.p("Tags are crowd-labelled and noisy: listen to the songs that land in the wrong corner before blaming the model.")
    t1b_measured(R, songs)


HAPPY_T = {"happy", "upbeat", "fun", "party", "positive"}
SAD_T = {"sad", "melancholic", "dark"}


def t1b_measured(R, songs):
    """Same question, but 'loud' is MEASURED (loudness of the file), not guessed from genre tags,
    and every analysed song with a happy-ish or sad-ish mood tag counts, whatever group it came from."""
    R.h("T1b · Happy vs sad, split by MEASURED loudness")
    tags = mtg_tags()
    S, lab = [], []
    for s in songs:
        m = s["meta"]
        if m.get("source") != "jamendo" or int(m["id"]) not in tags:
            continue
        mood = tags[int(m["id"])]["mood"]
        h, d = bool(mood & HAPPY_T), bool(mood & SAD_T)
        if h != d:
            S.append(s); lab.append(h)
    if len(S) < 12:
        R.v("Happy vs sad by measured loudness", "SKIP", "need ≥12 songs with happy or sad tags"); return
    lab = np.array(lab)
    v = np.array([mood_va(s)[0] for s in S]); a = np.array([mood_va(s)[1] for s in S])
    L = np.array([float(s["rhythm_loudness_db"]) for s in S]); loud = L > np.median(L)
    rows = []
    for name, m in (("all", np.ones(len(S), bool)), ("louder half", loud), ("quieter half", ~loud)):
        rows.append((name, int((lab & m).sum()), int((~lab & m).sum()), auc(v[lab & m], v[~lab & m]),
                     either_way(auc(L[lab & m], L[~lab & m]))))
    if "mood_happy_whole" in S[0]:
        hs = np.array([head_p(s, "mood_happy", "happy") - head_p(s, "mood_sad", "sad") for s in S])
        rows = [r + (auc(hs[lab & m], hs[~lab & m]),) for r, m in zip(rows, (np.ones(len(S), bool), loud, ~loud))]
        R.table(["songs", "happy-tagged", "sad/dark-tagged", "happiness score (emoMusic)", "loudness alone",
                 "yes/no models: P(happy) − P(sad)"], rows)
    else:
        R.table(["songs", "happy-tagged", "sad/dark-tagged", "happiness score separates them", "loudness alone"], rows)
    r = float(np.corrcoef(v, a)[0, 1])
    R.p(f"Happiness and energy scores move together (correlation {r:.2f}). Above about 0.5, the model partly reads "
        f"'energetic' as 'happy', which is exactly what makes loud-sad songs hard.")
    nl = min((lab & loud).sum(), (~lab & loud).sum())
    lv = rows[1][3]
    R.v("Mood on genuinely loud songs", "SKIP" if nl < 8 else verdict(lv >= 0.75, lv >= 0.65),
        f"score {lv:.2f} on the louder half (n={int((lab&loud).sum())} happy / {int((~lab&loud).sum())} sad); need ≥8 of each to judge")



def t2_sound(R, songs):
    R.h("T2 · Sound separates styles; Mood ignores style")
    C, E = group(songs, "sound_happy_classical"), group(songs, "sound_happy_electronic")
    if min(len(C), len(E)) < 4:
        R.v("Sound vs Mood", "SKIP", "need ≥4 songs in both happy_classical and happy_electronic"); return
    def pair_sims(A, B, same):
        out = []
        for i, a in enumerate(A):
            for j, b in enumerate(B):
                if same and j <= i: continue
                out.append(float(scoring.cosine(a["effnet_whole"], b["effnet_whole"][None])[0]))
        return out
    within = pair_sims(C, C, True) + pair_sims(E, E, True); across = pair_sims(C, E, False)
    a = auc(within, across)
    dv = abs(np.mean([mood_va(s)[0] for s in C]) - np.mean([mood_va(s)[0] for s in E]))
    LH, LS = group(songs, "mood_loud_happy"), group(songs, "mood_loud_sad_dark")
    R.v("Sound keeps different styles apart", verdict(a >= 0.85, a >= 0.7),
        f"same-style pairs are more alike than cross-style pairs {a*100:.0f}% of the time")
    R.v("Mood keeps same-mood songs together across styles", verdict(dv < 0.6, dv < 1.0),
        f"average happiness differs by {dv:.2f} (1–9 scale) between happy classical and happy electronic")
    if min(len(LH), len(LS)) >= 4:
        b = auc(pair_sims(LH, LH, True) + pair_sims(LS, LS, True), pair_sims(LH, LS, False))
        R.p(f"For comparison: Sound separates loud-happy from loud-sad only {b*100:.0f}% of the time "
            f"(≈50% means it can't). That is expected — Sound describes style, not feeling — and is why Mood is a separate feature.")


def t2b_genres(R, songs):
    R.h("T2b · Sound across 18 genres")
    G = [s for s in songs if s["meta"].get("group", "").startswith("genre_")]
    names = sorted({s["meta"]["group"] for s in G})
    G = [s for s in G if sum(t["meta"]["group"] == s["meta"]["group"] for t in G) >= 4]
    names = sorted({s["meta"]["group"] for s in G})
    if len(names) < 5:
        R.v("Sound separates genres", "SKIP", "need ≥5 genre groups with ≥4 songs (run the expanded list)"); return
    X = np.stack([s["effnet_whole"] for s in G]); lab = np.array([s["meta"]["group"] for s in G])
    Xn = X / np.linalg.norm(X, axis=1, keepdims=True); C = Xn @ Xn.T
    iu = np.triu_indices(len(G), 1); same = lab[iu[0]] == lab[iu[1]]
    a = auc(C[iu][same], C[iu][~same])
    rows = []
    for g in names:
        idx = np.where(lab == g)[0]; hit = []
        for i in idx:
            c = C[i].copy(); c[i] = -9
            nb = np.argsort(-c)[:5]
            hit.append(np.mean(lab[nb] == g))
        base_rate = (len(idx) - 1) / (len(G) - 1)
        rows.append((g.replace("genre_", ""), len(idx), f"{np.mean(hit)*100:.0f}%", f"{base_rate*100:.0f}%"))
    rows.sort(key=lambda r: -float(r[2][:-1]))
    R.table(["genre", "songs", "5 closest songs in same genre", "by chance"], rows)
    R.v("Sound separates genres", verdict(a >= 0.75, a >= 0.65),
        f"same-genre pairs closer than cross-genre pairs {a*100:.0f}% of the time across {len(names)} genres ({len(G)} songs)")
    R.p("Genres near the bottom are the ones Sound confuses with others; neighbouring styles (rock/punk/metal, "
        "techno/dnb, lounge/ambient) are expected to blur somewhat, and that is fine for recommendations.")


INST_EXPECT = {
    "inst_solo_piano": ({"piano"}, 3, "piano in top 3"),
    "inst_acoustic_guitar": ({"acousticguitar", "classicalguitar", "guitar"}, 3, "a guitar in top 3"),
    "inst_electronic_only": ({"synthesizer", "drummachine", "computer", "beat", "sampler", "pad"}, 3, "synth/drum machine in top 3"),
    "inst_strings_no_drums": ({"violin", "cello", "strings", "orchestra", "viola"}, 3, "strings in top 3"),
}


def t3_instruments(R, songs):
    R.h("T3 · Instruments")
    if not songs or "instruments_whole" not in songs[0]:
        R.v("Instruments", "SKIP", "no data"); return
    names = class_names("instruments", 40)
    rows, hits_all = [], []
    for g, (want, k, desc) in INST_EXPECT.items():
        G = group(songs, g)
        if not G: continue
        hits = [bool({names[i] for i in np.argsort(-s["instruments_whole"])[:k]} & want) for s in G]
        hits_all += hits
        rows.append((g, desc, f"{sum(hits)}/{len(hits)}"))
    B = group(songs, "inst_full_band")
    if B:
        need = {"drums", "bass", "electricguitar"}
        frac = [len({names[i] for i in np.argsort(-s["instruments_whole"])[:6]} & need) / 3 for s in B]
        rows.append(("inst_full_band", "drums, bass, electric guitar in top 6 (share found)", f"{np.mean(frac)*100:.0f}%"))
    R.table(["group", "expected", "hits"], rows)
    if hits_all:
        r = np.mean(hits_all)
        R.v("Expected instrument near the top", verdict(r >= 0.7, r >= 0.5), f"{r*100:.0f}% of single-instrument songs")
    # can the 'voice' class tell sung from instrumental songs?
    if "voice" in names:
        vi = names.index("voice")
        voc = [s["instruments_whole"][vi] for s in songs if s["meta"].get("vocalinstrumental") == "vocal"]
        ins = [s["instruments_whole"][vi] for s in songs if s["meta"].get("vocalinstrumental") == "instrumental"]
        src = "Jamendo's vocal/instrumental label"
        if min(len(voc), len(ins)) < 4:
            voc = [s["instruments_whole"][vi] for s in group(songs, "voice_tagged_vocal")]
            ins = [s["instruments_whole"][vi] for s in group(songs, "voice_instrumental")]
            src = "MTG tags"
        a = auc(voc, ins)
        R.v("'voice' class detects singing (to skip Voice for instrumentals)", verdict(None if np.isnan(a) else a >= 0.85, a >= 0.75),
            f"score {a:.2f} using {src} (n={len(voc)} vocal / {len(ins)} instrumental)")
    R.p("Note: this instrument model was trained on MTG-Jamendo, so scores on MTG-Jamendo songs are optimistic. "
        "Its published precision is low (PR-AUC 0.20), so expect weak results on rare instruments.")


def t4_rhythm(R, songs):
    R.h("T4 · Rhythm")
    groups = ["rhythm_fast", "rhythm_half_double_trap", "rhythm_no_steady_beat", "inst_full_band", "mood_quiet_sad", "inst_solo_piano"]
    rows = []
    for g in groups:
        G = group(songs, g)
        if not G: continue
        f = lambda k: np.nanmedian([float(s[f"rhythm_{k}"]) for s in G])
        rows.append((g, len(G), f("bpm"), f("confidence"), f("steadiness"), f("busyness"), f("danceability")))
    R.table(["group", "n", "speed (BPM)", "beat confidence (0–5.32)", "steadiness (lower = steadier)", "busyness (notes/s)", "danceability"], rows)
    NB = group(songs, "rhythm_no_steady_beat"); BT = group(songs, "rhythm_fast", "rhythm_half_double_trap", "inst_full_band")
    allc = np.array([float(s["rhythm_confidence"]) for s in songs])
    R.p(f"Across all {len(allc)} songs: {np.mean(allc < scoring.CONF_IGNORE)*100:.0f}% have beat confidence below "
        f"{scoring.CONF_IGNORE} (speed ignored), {np.mean(allc >= scoring.CONF_TRUST)*100:.0f}% at or above {scoring.CONF_TRUST} "
        f"(speed fully trusted), the rest partly trusted.")
    QB = group(songs, "mood_quiet_sad", "inst_solo_piano", "inst_strings_no_drums")
    if min(len(QB), len(BT)) >= 4:
        a2 = auc([float(s["rhythm_confidence"]) for s in BT], [float(s["rhythm_confidence"]) for s in QB])
        R.v("Beat confidence is low for acoustic songs without drums", verdict(a2 >= 0.85, a2 >= 0.7),
            f"beat songs score higher {a2*100:.0f}% of the time vs quiet sad / solo piano / strings")

    if min(len(NB), len(BT)) >= 4:
        a = auc([float(s["rhythm_confidence"]) for s in BT], [float(s["rhythm_confidence"]) for s in NB])
        R.v("Beat confidence is low for beatless songs", verdict(a >= 0.85, a >= 0.7), f"beat songs score higher {a*100:.0f}% of the time")
    F = group(songs, "rhythm_fast")
    if F:
        b = np.array([float(s["rhythm_bpm"]) for s in F])
        R.p(f"Fast group: {np.mean(b >= 140)*100:.0f}% detected ≥140 BPM, {np.mean(b < 110)*100:.0f}% detected at roughly half speed. "
            "Half-speed detections are why the half/double allowance exists.")
    # site BPM (Audius) agreement
    sb = [(float(s["rhythm_bpm"]), float(s["meta"]["site_bpm"])) for s in songs if s["meta"].get("site_bpm") not in (None, "", "None")]
    if len(sb) >= 3:
        d = np.array([scoring.tempo_distance(a, np.array([b]), half_double_penalty=0)[0] for a, b in sb])
        R.p(f"Agreement with Audius's own BPM: {np.mean(d < 0.06)*100:.0f}% within 4% (allowing half/double), n={len(sb)}.")
    HD = group(songs, "rhythm_half_double_trap")
    if len(HD) >= 4:
        bp = np.array([float(s["rhythm_bpm"]) for s in HD])
        plain = [abs(np.log2(bp[i] / bp[j])) for i in range(len(bp)) for j in range(i + 1, len(bp))]
        allow = [scoring.tempo_distance(bp[i], np.array([bp[j]]), 0)[0] for i in range(len(bp)) for j in range(i + 1, len(bp))]
        R.p(f"Half/double group: {np.mean(np.array(plain) < 0.1)*100:.0f}% of song pairs have close speed without the allowance, "
            f"{np.mean(np.array(allow) < 0.1)*100:.0f}% with it.")


def _random_clip(s, avoid_parts):
    ch = s["effnet_chunks"].astype(np.float32)
    n = len(ch); need = int(30 / 0.992)
    if n < need + 2:
        return None
    centres = np.arange(n) * 0.992 + 1.024
    for _ in range(30):
        st = rng.randint(0, n - need)
        w = (centres[st], centres[st] + 30)
        if avoid_parts and any(min(w[1], p[1]) - max(w[0], p[0]) > 10 for p in s["parts"]):
            continue
        return scoring.scale_sound(ch[st: st + need].mean(axis=0), _SC)
    return None


def t5_parts(R, songs):
    R.h("T5 · 3 parts vs whole song (30-second clip test)")
    S = [s for s in songs if s["trimmed_duration"] >= 75]
    if len(S) < 20:
        R.v("Clip test", "SKIP", "need ≥20 songs longer than 75 s"); return
    whole = np.stack([s["effnet_whole"] for s in S]); parts = [s["effnet_parts"] for s in S]
    res, margins = {}, {}
    for avoid in (False, True):
        hits = {"whole-song average": [], "best of 3 parts": [], "best of whole or parts": []}
        marg = {k: [] for k in hits}
        for i, s in enumerate(S):
            c = _random_clip(s, avoid)
            if c is None: continue
            sw = scoring.cosine(c, whole)
            sp = np.array([scoring.cosine(c, p).max() for p in parts])
            for name, sim in (("whole-song average", sw), ("best of 3 parts", sp), ("best of whole or parts", np.maximum(sw, sp))):
                rank = int((sim > sim[i]).sum())
                hits[name].append(rank)
                others = np.delete(sim, i)
                marg[name].append(float(sim[i] - others.max()))   # lead of the right song over the best wrong one
        res[avoid] = {k: ((np.mean(np.array(v) == 0), np.mean(np.array(v) < 10), len(v)) if v else (np.nan, np.nan, 0))
                      for k, v in hits.items()}
        if avoid:
            ranges = {k: rate_range(np.array(v) == 0) for k, v in hits.items()}
        else:
            ranges0 = {k: rate_range(np.array(v) == 0) for k, v in hits.items()}
        margins[avoid] = {k: float(np.mean(v)) if v else np.nan for k, v in marg.items()}
    if res[True]["whole-song average"][2] < 10:      # songs too short to place clips away from the stored parts
        res[True] = res[False]; margins[True] = margins[False]; ranges = ranges0
    pct = lambda r: "" if np.isnan(r[0]) else f"{r[0]*100:.0f}–{r[1]*100:.0f}%"
    rows = [(k, f"{v[0]*100:.0f}%", f"{v[1]*100:.0f}%", f"{res[True][k][0]*100:.0f}%", pct(ranges[k]),
             f"{res[True][k][1]*100:.0f}%", margins[True][k]) for k, v in res[False].items()]
    R.table(["compare clip with…", "own song #1 (any clip)", "own song in top 10", "#1 (clip away from stored parts)",
             "95% range", "top 10 (away)", "safety margin (away)"], rows)
    R.p("If the 95% ranges overlap, the methods are not really different on this many songs.")
    R.p("Safety margin = how far the right song's closeness is ahead of the closest wrong song (higher = the method would "
        "still work in a much bigger pool). With a small pool, every method finds the song, so the margin decides.")
    if res[False]["whole-song average"][2] == 0:
        R.v("Clip test", "SKIP", "no songs long enough"); return
    w1 = res[True]["whole-song average"][0]; p1 = res[True]["best of 3 parts"][0]; b1 = res[True]["best of whole or parts"][0]
    mw, mp, mb = (margins[True][k] for k in ("whole-song average", "best of 3 parts", "best of whole or parts"))
    if max(w1, p1, b1) - min(w1, p1, b1) < 0.03:
        best = max(("whole", mw), ("parts", mp), ("both", mb), key=lambda x: x[1])
        R.v("Which comparison finds the song from a 30 s clip", "WARN" if max(w1, p1, b1) >= 0.97 else "PASS",
            f"tie on finding the song ({w1*100:.0f}/{p1*100:.0f}/{b1*100:.0f}%) - pool too small to separate them; "
            f"safety margin whole {mw:.3f}, parts {mp:.3f}, both {mb:.3f} -> leaning '{best[0]}'. Re-run on a pool of 1,000+")
    else:
        best = max(("whole", w1), ("parts", p1), ("both", b1), key=lambda x: x[1])
        R.v("Which comparison finds the song from a 30 s clip", "PASS",
            f"#1 rate (clips away from stored parts): whole {w1*100:.0f}%, parts {p1*100:.0f}%, both {b1*100:.0f}% -> use '{best[0]}'")
    # how different are the parts inside a song?
    rows = []
    for g in sorted({s["meta"]["group"] for s in S}):
        G = [s for s in S if s["meta"]["group"] == g and len(s["effnet_parts"]) == 3]
        if len(G) < 3: continue
        d = [np.mean([scoring.cosine(s["effnet_parts"][a], s["effnet_parts"][b][None])[0] for a, b in ((0, 1), (0, 2), (1, 2))]) for s in G]
        rows.append((g, len(G), float(np.mean(d))))
    rows.sort(key=lambda r: r[2])
    R.p("How alike a song's 3 parts are (Sound, 1.0 = identical). Low values = songs that change a lot, where a single average blurs most:")
    R.table(["group", "n", "part-to-part similarity"], rows)


def feature_matrices(S):
    n = len(S)
    sound = np.stack([s["effnet_whole"] for s in S]); inst = np.stack([s["instruments_whole"] for s in S])
    mv = np.stack([mood_va(s) for s in S]); mean, std = mv.mean(0), mv.std(0) + 1e-9
    rh = {k: np.array([float(s[f"rhythm_{k}"]) for s in S]) for k in ("bpm", "confidence", "steadiness", "busyness")}
    rh["steadiness"] = np.nan_to_num(rh["steadiness"], nan=np.nanmedian(rh["steadiness"]))
    med, iqr = scoring.robust_scale_stats(np.column_stack([rh["steadiness"], rh["busyness"]]))
    loud = np.array([float(s["rhythm_loudness_db"]) for s in S])
    M = {}
    M["sound"] = np.stack([scoring.cosine(sound[i], sound) for i in range(n)])
    M["instruments"] = np.stack([scoring.cosine(inst[i], inst) for i in range(n)])
    M["mood"] = np.stack([scoring.mood_similarity(mv[i], mv, mean, std) for i in range(n)])
    # Candidate richer Mood: the 2 emoMusic scores + the 4 yes/no mood models (happy, sad, aggressive, relaxed),
    # each rescaled to the pool, compared by distance. Same audio analysis, no extra cost.
    if "mood_happy_whole" in S[0]:
        m6 = np.column_stack([mv,
            [[head_p(s, "mood_happy", "happy"), head_p(s, "mood_sad", "sad"),
              head_p(s, "mood_aggressive", "aggressive"), head_p(s, "mood_relaxed", "relaxed")] for s in S]])
        mu, sd = m6.mean(0), m6.std(0) + 1e-9
        z = (m6 - mu) / sd
        M["mood (6 numbers)"] = -np.sqrt(((z[:, None, :] - z[None, :, :]) ** 2).sum(-1))
    M["rhythm"] = np.stack([scoring.rhythm_similarity({k: rh[k][i] for k in rh}, rh, med, iqr) for i in range(n)])
    M["energy only"] = -np.abs(mv[:, 1][:, None] - mv[:, 1][None])
    M["happiness only"] = -np.abs(mv[:, 0][:, None] - mv[:, 0][None])
    M["loudness"] = -np.abs(loud[:, None] - loud[None])
    return M


def t6_overlap(R, songs):
    R.h("T6 · Do features overlap?")
    S = [s for s in songs if "instruments_whole" in s]
    if len(S) < 20:
        R.v("Feature overlap", "SKIP", "need ≥20 songs"); return None, None
    M = feature_matrices(S)
    iu = np.triu_indices(len(S), 1)
    names = list(M)
    C = np.array([[spearman(M[a][iu], M[b][iu]) for b in names] for a in names])
    R.table([""] + names, [[a] + list(C[i]) for i, a in enumerate(names)])
    core = ["sound", "instruments", "mood", "rhythm"]
    worst = max(((a, b, C[names.index(a), names.index(b)]) for i, a in enumerate(core) for b in core[i + 1:]), key=lambda x: x[2])
    R.v("Main features measure different things", verdict(worst[2] < 0.6, worst[2] < 0.8),
        f"strongest overlap: {worst[0]} ↔ {worst[1]} = {worst[2]:.2f} (above 0.8 = nearly the same thing)")
    R.p("Each number: how often two songs that are close on one feature are also close on the other (rank correlation over all song pairs). "
        "If 'loudness' correlates strongly with Mood or Sound, energy is being counted twice.")
    return S, M


def t7_same_artist(R, songs):
    R.h("T7 · Same artist, different album (Sound only = Voice baseline C)")
    G = group(songs, "voice_same_artist_diff_album")
    if len(G) < 6:
        R.v("Same-artist test", "SKIP", "need the voice_same_artist group"); return
    allv = np.stack([s["effnet_whole"] for s in songs]); keys = [s["key"] for s in songs]
    hits = []
    for s in G:
        partners = [t for t in G if t["meta"]["mtg_artist"] == s["meta"]["mtg_artist"] and t["key"] != s["key"]]
        if not partners: continue
        sim = scoring.cosine(s["effnet_whole"], allv); sim[keys.index(s["key"])] = -9
        rank = int((sim > sim[keys.index(partners[0]["key"])]).sum())
        hits.append(rank)
    h = np.array(hits)
    R.v("Sound finds the same artist's other album", "PASS" if len(h) else "SKIP",
        f"partner in top 10: {np.mean(h < 10)*100:.0f}% (n={len(h)}, pool={len(songs)}) — this is the number Voice A/B must beat by 10 points")


def t8_earn_place(R, S, M):
    R.h("T8 · Does each feature earn its place? (mini version)")
    if S is None:
        R.v("Earn its place", "SKIP", "need T6 data"); return None
    tags = mtg_tags()
    T = [tags.get(int(s["meta"]["id"])) if s["meta"].get("source") == "jamendo" else None for s in S]
    idx = [i for i, t in enumerate(T) if t]
    if len(idx) < 20:
        R.v("Earn its place", "SKIP", "need ≥20 Jamendo songs with MTG tags"); return None
    n = len(S)
    P = {f: np.stack([scoring.to_percentile(M[f][i], exclude=np.arange(n) == i) for i in range(n)]) for f in ("sound", "mood", "instruments", "rhythm")}
    def jac(a, b): return len(a & b) / len(a | b) if a | b else np.nan
    configs = [("random", None), ("sound", ["sound"]), ("sound+mood", ["sound", "mood"]),
               ("sound+mood+instruments", ["sound", "mood", "instruments"]), ("all four", ["sound", "mood", "instruments", "rhythm"])]
    rows, res = [], {}
    for name, feats in configs:
        agree = {"genre": [], "mood": [], "inst": []}
        for i in idx:
            if feats is None:
                nb = rng.sample([j for j in idx if j != i], 10)
            else:
                w = {f: scoring.WHOLE_SONG_WEIGHTS[f] for f in feats}
                score = sum(P[f][i] * w[f] for f in feats) / sum(w.values()); score[i] = -1
                nb = [j for j in np.argsort(-score) if T[j]][:10]
            for c in agree:
                agree[c].append(np.nanmean([jac(T[i][c], T[j][c]) for j in nb]))
        res[name] = {c: float(np.nanmean(v)) for c, v in agree.items()}
        rows.append((name, res[name]["genre"], res[name]["mood"], res[name]["inst"]))
    R.table(["features used", "genre tags shared", "mood tags shared", "instrument tags shared"], rows)
    gain_mood = res["sound+mood"]["mood"] - res["sound"]["mood"]
    gain_inst = res["sound+mood+instruments"]["inst"] - res["sound+mood"]["inst"]
    beats_random = res["sound"]["genre"] > res["random"]["genre"] * 1.3
    R.v("Sound beats random", verdict(beats_random), f"genre agreement {res['sound']['genre']:.2f} vs random {res['random']['genre']:.2f}")
    R.v("Adding Mood improves mood agreement", verdict(gain_mood > 0.01, gain_mood > -0.01), f"change {gain_mood:+.3f}")
    R.v("Adding Instruments improves instrument agreement", verdict(gain_inst > 0.01, gain_inst > -0.01), f"change {gain_inst:+.3f}")
    R.p("Small sample, so treat these as a dry run of the method. The real version runs on the whole MTG-Jamendo validation split on the desktop.")
    return P


def t9_examples(R, S, P):
    R.h("T9 · Example recommendations (within this small test set)")
    if S is None or P is None:
        return
    n = len(S)
    names = lambda s: f"{s['meta'].get('title') or s['key']} — {s['meta'].get('artist') or ''}"
    picks = [i for i, s in enumerate(S) if s["meta"]["group"] in ("mood_loud_happy", "mood_quiet_sad", "inst_solo_piano")][:3]
    for i in picks:
        chosen = ["sound", "mood", "instruments", "rhythm"]
        pp = [{f: P[f][i] for f in chosen}]
        match, raw, _, passes = scoring.combine(pp, chosen, weights=scoring.WHOLE_SONG_WEIGHTS, exclude=np.arange(n) == i)
        match[i] = -1
        order = np.argsort(-match)[:5]
        R.p(f"<b>Input:</b> {html.escape(names(S[i]))} <i>({S[i]['meta']['group']})</i>")
        R.table(["match %", "song", "group", "sound", "mood", "instruments", "rhythm", "passes every-feature minimum?"],
                [(match[j], names(S[j]), S[j]["meta"]["group"], *(P[f][i][j] for f in chosen), bool(passes[j])) for j in order])


def t10_flags(R, songs):
    """List songs whose numbers contradict their label, so only these need listening.
    Writes songs_to_check.csv (fill in i_agree in edge_cases.csv after listening)."""
    R.h("T10 · Songs to listen to (results contradict the label)")
    if len(songs) < 20:
        return
    tags = mtg_tags()
    V = np.array([mood_va(s)[0] for s in songs]); L = np.array([float(s["rhythm_loudness_db"]) for s in songs])
    vlo, vhi = np.percentile(V, 25), np.percentile(V, 75)
    llo, lhi = np.percentile(L, 25), np.percentile(L, 75)
    try:
        inames = class_names("instruments", 40)
    except Exception:
        inames = None
    G = [s for s in songs if s["meta"].get("group", "").startswith("genre_")]
    if len(G) >= 20:
        Xn = np.stack([s["effnet_whole"] for s in G]); Xn = Xn / np.linalg.norm(Xn, axis=1, keepdims=True)
        glab = np.array([s["meta"]["group"] for s in G]); gkey = [s["key"] for s in G]
    out = []
    for i, s in enumerate(songs):
        m = s["meta"]; g = m.get("group", ""); why = []
        mood = tags.get(int(m["id"]), {}).get("mood", set()) if m.get("source") == "jamendo" else set()
        happy, sad = bool(mood & HAPPY_T), bool(mood & SAD_T)
        if happy and not sad and V[i] <= vlo:
            why.append(f"tagged happy but scored among the saddest (happiness {V[i]:.1f})")
        if sad and not happy and V[i] >= vhi:
            why.append(f"tagged sad/dark but scored among the happiest (happiness {V[i]:.1f})")
        if "loud" in g and L[i] <= llo:
            why.append(f"in a 'loud' group but among the quietest files ({L[i]:.0f} dB)")
        if "quiet" in g and L[i] >= lhi:
            why.append(f"in a 'quiet' group but among the loudest files ({L[i]:.0f} dB)")
        conf = float(s["rhythm_confidence"])
        if g == "rhythm_no_steady_beat" and conf >= scoring.CONF_TRUST:
            why.append(f"'no steady beat' but beat confidence is high ({conf:.1f}): is there a pulse?")
        if g in ("rhythm_fast", "inst_full_band") and conf < scoring.CONF_IGNORE:
            why.append(f"should have a clear beat but confidence is very low ({conf:.1f})")
        if inames and g in INST_EXPECT:
            want, _, desc = INST_EXPECT[g]
            top5 = {inames[j] for j in np.argsort(-s["instruments_whole"])[:5]}
            if not top5 & want:
                why.append(f"expected {'/'.join(sorted(want))[:40]} but it's not in the top 5 instruments")
        if len(G) >= 20 and s["key"] in gkey:
            k = gkey.index(s["key"]); c = Xn @ Xn[k]; c[k] = -9
            if not (glab[np.argsort(-c)[:5]] == g).any():
                why.append("none of its 5 closest songs share its genre: odd genre tag, or genuinely crossover")
        for w in why:
            out.append({"group": g, "jamendo_id": m["id"], "title": m.get("title", ""), "artist": m.get("artist", ""),
                        "listen": f"https://www.jamendo.com/track/{m['id']}" if m.get("source") == "jamendo" else m.get("page", ""),
                        "reason": w, "your_verdict": ""})
    path = os.path.join(HERE, "songs_to_check.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "jamendo_id", "title", "artist", "listen", "reason", "your_verdict"])
        w.writeheader(); w.writerows(out)
    R.p(f"{len(out)} flags on {len({o['jamendo_id'] for o in out})} songs, saved to <b>songs_to_check.csv</b>. "
        "Listen to these only. If the label is wrong, put n in that song's i_agree column in edge_cases.csv and rerun the report. "
        "If the label is right, the model got it wrong: that is a real finding.")
    R.table(["group", "song", "why it's flagged"], [(o["group"], f"{o['title']} / {o['artist']}", o["reason"]) for o in out[:60]])


def _pct_matrices(S, M, feats=("sound", "mood", "instruments", "rhythm")):
    n = len(S)
    return {f: np.stack([scoring.to_percentile(M[f][i], exclude=np.arange(n) == i) for i in range(n)]) for f in feats}


SPEED_OK = {"verylow", "low", "medium", "high", "veryhigh"}


def t11_evidence(R, S, M, summary):
    """Does each feature change the list, and in the direction of what it claims to measure?
    Graded only with labels the models never produced: human tags (MTG-Jamendo) and Jamendo's own speed label."""
    R.h("T11 · Evidence: each feature pulls the list towards its own kind of similarity")
    if S is None or len(S) < 30:
        R.v("Feature evidence", "SKIP", "need ≥30 songs"); return None
    tags = mtg_tags(); n = len(S)
    T = [tags.get(int(s["meta"]["id"])) if s["meta"].get("source") == "jamendo" else None for s in S]
    spd = [s["meta"].get("speed") if s["meta"].get("speed") in SPEED_OK else None for s in S]
    feats = ["sound", "mood", "instruments", "rhythm"] + (["mood (6 numbers)"] if "mood (6 numbers)" in M else [])
    lists = {f: [] for f in feats}
    for i in range(n):
        for f in feats:
            sim = M[f][i].copy(); sim[i] = -np.inf
            lists[f].append(set(np.argsort(-sim)[:10]))
    lists["random"] = [set(rng.sample([j for j in range(n) if j != i], 10)) for i in range(n)]

    def jac(a, b):
        return len(a & b) / len(a | b) if (a | b) else np.nan

    def agree(nbs, kind):
        vals = []
        for i, nb in enumerate(nbs):
            if kind == "speed":
                if spd[i] is None: continue
                m = [spd[j] == spd[i] for j in nb if spd[j] is not None]
                if m: vals.append(np.mean(m))
            else:
                if not T[i] or not T[i][kind]: continue
                m = [jac(T[i][kind], T[j][kind]) for j in nb if T[j]]
                if m: vals.append(np.nanmean(m))
        return float(np.nanmean(vals)) if vals else np.nan, len(vals)

    # MTG-Jamendo's "mood/theme" tags mix feelings with themes (film, christmas, corporate...). Feelings only:
    FEEL = {"happy", "sad", "melancholic", "dark", "energetic", "calm", "relaxing", "upbeat", "fun", "uplifting",
            "romantic", "emotional", "dramatic", "epic", "inspiring", "hopeful", "positive", "soft", "powerful",
            "heavy", "meditative", "party", "groovy", "cool", "sexy", "funny", "dream", "deep", "motivational"}
    for t in T:
        if t is not None:
            t["feel"] = t["mood"] & FEEL
    cols = [("genre", "same genre tags"), ("mood", "same mood/theme tags"), ("feel", "same feeling tags"),
            ("inst", "same instrument tags"), ("speed", "same Jamendo speed label")]
    table, res = [], {}
    for f in feats + ["random"]:
        row = [f + " only" if f != "random" else "random songs"]
        for k, _ in cols:
            v, cnt = agree(lists[f], k); res[(f, k)] = v; row.append(v)
        table.append(row)
    R.table(["10 closest songs chosen by…"] + [c[1] for c in cols], table)
    R.p("Read across a column: the feature built for that kind of similarity should score highest in its own column "
        "(Sound for genre, Mood for mood tags, Instruments for instrument tags, Rhythm for speed), and every feature should beat random songs. "
        "All labels here come from people or from Jamendo, never from our models, so the models are not grading themselves.")
    own = {"sound": "genre", "mood": "feel", "instruments": "inst", "rhythm": "speed"}
    for f, k in own.items():
        mine = res[(f, k)]; rnd = res[("random", k)]
        others = [res[(g, k)] for g in feats if g != f and not np.isnan(res[(g, k)])]
        best_other = max(others) if others else np.nan
        ok = (mine > rnd * 1.2) and (mine >= best_other)
        warn = mine > rnd * 1.1
        if f == "rhythm" and rnd > 0.7:
            R.v("Rhythm finds songs that share its own label", "SKIP",
                f"Jamendo's speed label is the same for {rnd*100:.0f}% of random song pairs, so it can't judge Rhythm; use tapped BPM instead")
            summary["evidence_rhythm"] = [round(mine, 3), round(best_other, 3), round(rnd, 3)]
            continue
        R.v(f"{f.capitalize()} finds songs that share its own label", verdict(ok, warn),
            f"{mine:.3f} vs best other feature {best_other:.3f} vs random {rnd:.3f}")
        summary[f"evidence_{f}"] = [round(mine, 3), round(best_other, 3), round(rnd, 3)]
    if "mood (6 numbers)" in feats:
        m6v, m2v = res[("mood (6 numbers)", "feel")], res[("mood", "feel")]
        snd = res[("sound", "feel")]
        R.v("Richer Mood (6 numbers) vs current Mood (2 numbers) on feeling labels",
            verdict(m6v > m2v * 1.1 and m6v >= snd, m6v > m2v),
            f"6 numbers {m6v:.3f} vs 2 numbers {m2v:.3f} vs Sound {snd:.3f} vs random {res[('random', 'feel')]:.3f}")
        summary["evidence_mood6_feel"] = [round(m6v, 3), round(m2v, 3), round(snd, 3), round(res[("random", "feel")], 3)]
    summary["evidence_table"] = {f"{f}|{k}": (None if np.isnan(v) else round(v, 3)) for (f, k), v in res.items()}
    # how different are the lists?
    rows = []
    main4 = ["sound", "mood", "instruments", "rhythm"]
    for a_i, a in enumerate(main4):
        for b in main4[a_i + 1:]:
            ov = np.mean([len(x & y) for x, y in zip(lists[a], lists[b])])
            rows.append((f"{a} vs {b}", f"{ov:.1f} of 10"))
            summary[f"overlap_{a}_{b}"] = round(float(ov), 2)
    R.p("How many of the 10 recommendations two features share for the same starting song (10 = identical lists, about "
        f"{10*10/(n-1):.1f} = what two random lists would share):")
    R.table(["features compared", "songs in common"], rows)
    return lists


def t12_balance(R, S, M, summary):
    """Proof that the every-feature minimum stops one feature carrying a recommendation."""
    R.h("T12 · Balance: no single feature can carry a recommendation")
    if S is None or len(S) < 30:
        return
    n = len(S); feats = ["sound", "mood", "instruments", "rhythm"]
    P = _pct_matrices(S, M, feats)
    w = {f: scoring.WHOLE_SONG_WEIGHTS[f] for f in feats}
    lop_plain, lop_rule, per_feat = [], [], {f: [] for f in feats}
    for i in range(n):
        ex = np.arange(n) == i
        plain = sum(P[f][i] * w[f] for f in feats) / sum(w.values()); plain[i] = -1
        top_plain = np.argsort(-plain)[:10]
        match, raw, _, passes = scoring.combine([{f: P[f][i] for f in feats}], feats, weights=w, feature_floor=65, exclude=ex)
        cand = np.where(passes & ~ex)[0]
        top_rule = cand[np.argsort(-raw[cand])][:10]
        lowest = lambda j: min(P[f][i][j] for f in feats)
        lop_plain += [lowest(j) < 50 for j in top_plain]
        lop_rule += [lowest(j) < 50 for j in top_rule]
        for j in top_rule:
            for f in feats:
                per_feat[f].append(P[f][i][j])
    a, b = np.mean(lop_plain) * 100, (np.mean(lop_rule) * 100 if lop_rule else np.nan)
    R.table(["combining method", "recommendations where some feature is below 50% (a bad mismatch)"],
            [("plain weighted average", f"{a:.0f}%"), ("average + every feature ≥65% (our rule)", f"{b:.0f}%")])
    R.table(["feature", "average match % inside the final recommendations"], [(f, float(np.mean(v))) for f, v in per_feat.items() if v])
    R.v("Every-feature minimum removes one-sided matches", verdict(b < a / 2 if not np.isnan(b) else None, b < a),
        f"{a:.0f}% of plain-average picks hide a bad mismatch vs {b:.0f}% with the rule")
    summary["balance_plain_pct_bad"] = round(float(a), 1); summary["balance_rule_pct_bad"] = round(float(b), 1)
    summary["balance_feature_means"] = {f: round(float(np.mean(v)), 1) for f, v in per_feat.items() if v}


def t13_polarity(R, S, M, summary):
    """The measure that matches what Mood is FOR: among songs people tagged happy or sad,
    do a song's 10 closest songs have the same happy/sad side? Genre can't help much here."""
    R.h("T13 · Happy or sad: do the 10 closest songs land on the same side?")
    if S is None:
        return
    tags = mtg_tags(); pol = []
    for s in S:
        t = tags.get(int(s["meta"]["id"])) if s["meta"].get("source") == "jamendo" else None
        if not t: pol.append(None); continue
        h, d = bool(t["mood"] & HAPPY_T), bool(t["mood"] & SAD_T)
        pol.append(h if h != d else None)
    idx = np.array([i for i, p in enumerate(pol) if p is not None])
    if len(idx) < 30:
        R.v("Happy/sad side", "SKIP", "need ≥30 happy- or sad-tagged songs"); return
    lab = np.array([pol[i] for i in idx]); n = len(idx)
    sub = {f: M[f][np.ix_(idx, idx)] for f in ("sound", "mood", "instruments")}
    pct = {f: np.stack([scoring.to_percentile(sub[f][i], exclude=np.arange(n) == i) for i in range(n)]) for f in sub}
    methods = {"random songs": None, "sound only": pct["sound"], "instruments only": pct["instruments"],
               "mood only": pct["mood"], "sound + mood (equal)": (pct["sound"] + pct["mood"]) / 2}
    rows, res = [], {}
    for name, P in methods.items():
        same = []
        for i in range(n):
            if P is None:
                nb = rng.sample([j for j in range(n) if j != i], 10)
            else:
                sc = P[i].copy(); sc[i] = -1; nb = np.argsort(-sc)[:10]
            same.append(np.mean(lab[nb] == lab[i]))
        res[name] = float(np.mean(same)); rows.append((name, f"{res[name]*100:.0f}%"))
    R.table(["10 closest songs chosen by…", "on the same happy/sad side"], rows)
    R.p(f"{int(lab.sum())} happy-tagged and {int((~lab).sum())} sad/dark-tagged songs. Random lists land on the same side "
        "about half the time; the higher, the better a feature keeps the feeling of the starting song.")
    m, s_, sm = res["mood only"], res["sound only"], res["sound + mood (equal)"]
    R.v("Mood keeps the happy/sad side better than Sound", verdict(m > s_ + 0.03, m > s_),
        f"mood {m*100:.0f}% vs sound {s_*100:.0f}% vs random {res['random songs']*100:.0f}%")
    R.v("Adding Mood to Sound keeps the side better than Sound alone", verdict(sm > s_ + 0.03, sm > s_),
        f"sound+mood {sm*100:.0f}% vs sound {s_*100:.0f}%")
    summary["polarity"] = {k: round(v, 3) for k, v in res.items()}
    summary["polarity_n"] = [int(lab.sum()), int((~lab).sum())]


def _polar_labels(S):
    tags = mtg_tags(); out = []
    for s in S:
        t = tags.get(int(s["meta"]["id"])) if s["meta"].get("source") == "jamendo" and str(s["meta"]["id"]).isdigit() else None
        if not t: out.append(None); continue
        h, d = bool(t["mood"] & HAPPY_T), bool(t["mood"] & SAD_T)
        out.append(h if h != d else None)
    return out


def _same_side(points, lab):
    """Share of each song's 10 closest songs (2-D distance on z-scored points) on the same happy/sad side."""
    z = (points - points.mean(0)) / (points.std(0) + 1e-9)
    D = np.sqrt(((z[:, None, :] - z[None, :, :]) ** 2).sum(-1)); np.fill_diagonal(D, np.inf)
    nb = np.argsort(D, axis=1)[:, :10]
    return float(np.mean(lab[nb] == lab[:, None]))


def t14_mood_candidates(R, songs, summary):
    """Which mood model separates happy from sad best, especially on LOUD songs?
    Pick rule fixed in advance: the candidate with the best louder-half score wins, but only if it beats
    the current model there by at least 0.03 and keeps at least the same 'same side' score (-1 point)."""
    R.h("T14 · Mood candidates: which model tells happy from sad best?")
    S = [s for s in songs if "cand_emomusic_vggish_whole" in s or "cand_deam_vggish_whole" in s]
    pol = _polar_labels(S)
    idx = [i for i, p in enumerate(pol) if p is not None]
    if len(idx) < 40:
        R.v("Mood candidates", "SKIP", f"need ≥40 happy/sad-tagged songs analysed with the new models (have {len(idx)}); run --upgrade / the big pass")
        return
    S = [S[i] for i in idx]; lab = np.array([pol[i] for i in idx])
    L = np.array([float(s["rhythm_loudness_db"]) for s in S]); loud = L > np.median(L)
    cur = np.array([va(s) for s in S])
    cands = {"emoMusic via MusiCNN (original)": cur, "DEAM via MusiCNN": np.array([va(s, "deam") for s in S])}
    for key, name in (("emomusic_vggish", "emoMusic via VGGish"), ("deam_vggish", "DEAM via VGGish")):
        if all(f"cand_{key}_whole" in s for s in S):
            v = np.array([s[f"cand_{key}_whole"] for s in S])
            cands[name] = np.column_stack([v[:, cls_index(key, "valence", 0)], v[:, cls_index(key, "arousal", 1)]])
    zs = [(c - c.mean(0)) / (c.std(0) + 1e-9) for c in cands.values()]
    cands["Average of the mood models"] = np.mean(zs, axis=0)
    own = os.path.join(HERE, "own_mood.npz")
    if os.path.exists(own):
        o = np.load(own)
        X = np.array([np.concatenate([s["effnet_whole_raw"], s["musicnn_whole"]]) for s in S])
        sc = ((X - o["mu"]) / o["sd"]) @ o["w"] + float(o["b"])
        cands[f"Own trained model (cross-val {float(o['cv_auc']):.2f})"] = np.column_stack([sc, cur[:, 1]])
    rows, res = [], {}
    for name, P in cands.items():
        a_all, a_loud, a_quiet = auc(P[lab, 0], P[~lab, 0]), auc(P[lab & loud, 0], P[~lab & loud, 0]), auc(P[lab & ~loud, 0], P[~lab & ~loud, 0])
        side = _same_side(P, lab); r = float(np.corrcoef(P[:, 0], P[:, 1])[0, 1])
        res[name] = (a_all, a_loud, a_quiet, side, r)
        rows.append((name, a_all, a_loud, rng_txt(auc_range(P[lab & loud, 0], P[~lab & loud, 0])), a_quiet, f"{side*100:.0f}%", r))
    for key, name in (("mood", "Yes/no models via EffNet: P(happy)−P(sad)"), ("musicnn", "Yes/no models via MusiCNN: P(happy)−P(sad)")):
        if key == "mood":
            v = np.array([head_p(s, "mood_happy", "happy") - head_p(s, "mood_sad", "sad") for s in S])
        elif all("cand_mood_happy_musicnn_whole" in s and "cand_mood_sad_musicnn_whole" in s for s in S):
            v = np.array([s["cand_mood_happy_musicnn_whole"][cls_index("mood_happy_musicnn", "happy", 0)]
                          - s["cand_mood_sad_musicnn_whole"][cls_index("mood_sad_musicnn", "sad", 1)] for s in S])
        else:
            continue
        rows.append((name, auc(v[lab], v[~lab]), auc(v[lab & loud], v[~lab & loud]), "", auc(v[lab & ~loud], v[~lab & ~loud]), "–", np.nan))
    R.table(["mood model", "happy vs sad (all)", "louder half", "louder half 95% range", "quieter half", "10 closest on same side",
             "happy–energy link (lower = less confusion)"], rows)
    R.p(f"{int(lab.sum())} happy- and {int((~lab).sum())} sad-tagged songs. 0.5 = guessing, 1.0 = perfect. "
        "Pick rule set before running: best louder-half score wins if it beats the current model by ≥0.03 "
        "without lowering the same-side score by more than 1 point.")
    base_name = "emoMusic via MusiCNN (original)"; b = res[base_name]
    ok = {n: v for n, v in res.items() if n != base_name and v[1] >= b[1] + 0.03 and v[3] >= b[3] - 0.01}
    if ok:
        best = max(ok, key=lambda n: ok[n][1])
        win = paired_auc_win(cands[best][loud, 0], cands[base_name][loud, 0], lab[loud])
        summary["mood_candidate_win_share"] = round(win, 3)
        R.v("Better mood model found", "PASS" if win >= 0.9 else "WARN",
            f"{best}: louder half {ok[best][1]:.2f} vs original {b[1]:.2f}; same side {ok[best][3]*100:.0f}% vs {b[3]*100:.0f}%; "
            f"ahead in {win*100:.0f}% of resamples" + ("" if win >= 0.9 else " (under 90%: could be luck, check again on more songs)"))
    else:
        R.v("Better mood model found", "WARN", f"none beat the original model by ≥0.03 on loud songs (original {b[1]:.2f}); keep it")
    summary["mood_candidates"] = {n: [round(x, 3) for x in v] for n, v in res.items()}


def _load_taps():
    p = os.path.join(HERE, "taps.csv"); out = {}
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                v = (r.get("tapped_bpm") or "").strip().lower()
                if v == "none":
                    out[str(r["jamendo_id"])] = None
                else:
                    try:
                        out[str(r["jamendo_id"])] = float(v)
                    except ValueError:
                        pass
    return out


def _audius_bpm_is_human(key):
    """Audius computes most BPMs itself (another algorithm); only artist-entered ones count as truth."""
    from results_index import read_meta
    return str(read_meta(key, RES).get("bpm_custom")).lower() == "true"


def t15_rhythm_candidates(R, songs, summary):
    R.h("T15 · Rhythm candidates: which tempo method matches people, and which signal spots 'no beat'?")
    taps = _load_taps()
    truth = []
    for s in songs:
        sid = str(s["meta"].get("id")); m = s["meta"]
        if sid in taps and taps[sid]:
            truth.append((s, taps[sid], "tapped"))
        elif m.get("site_bpm") not in (None, "", "None") and _audius_bpm_is_human(s["key"]):
            truth.append((s, float(m["site_bpm"]), "Audius (artist-entered)"))
    est = {"RhythmExtractor (current)": "rhythm_bpm", "TempoCNN": "cand_tempocnn_bpm", "Percival": "cand_percival_bpm"}
    tol = np.log2(1.04)
    if len(truth) >= 10:
        rows, res = [], {}
        for name, k in est.items():
            pairs = [(float(s[k]), t) for s, t, _ in truth if k in s and float(s[k]) > 0]
            if len(pairs) < 10: continue
            e = np.array([p[0] for p in pairs]); t = np.array([p[1] for p in pairs])
            acc1 = np.mean(np.abs(np.log2(e / t)) < tol)
            acc2 = np.mean(np.min([np.abs(np.log2(e * f / t)) for f in (1, 2, 0.5, 3, 1 / 3)], axis=0) < tol)
            res[name] = (acc1, acc2, len(pairs)); rows.append((name, f"{acc1*100:.0f}%", f"{acc2*100:.0f}%", len(pairs)))
        src = sorted({x for _, _, x in truth})
        R.table(["tempo method", "within 4% of the true speed", "within 4% allowing half/double/triple", "songs"], rows)
        R.p(f"True speeds from: {', '.join(src)}.")
        best = max(res, key=lambda n: (res[n][0], res[n][1]))
        R.v("Best tempo method", "PASS" if best != "RhythmExtractor (current)" or res[best][0] >= 0.6 else "WARN",
            f"{best}: {res[best][0]*100:.0f}% exact, {res[best][1]*100:.0f}% allowing half/double (n={res[best][2]})")
        summary["tempo_methods"] = {n: [round(a, 3), round(b, 3), c] for n, (a, b, c) in res.items()}
    else:
        R.v("Tempo methods vs true speed", "SKIP", f"need ≥10 songs with a tapped or Audius speed (have {len(truth)}): run make_tap_list.py and fill taps.csv")
    # beat presence
    NB = [s for s in songs if s["meta"].get("group") in ("rhythm_no_steady_beat", "mood_quiet_sad", "inst_solo_piano")
          or (str(s["meta"].get("id")) in taps and taps[str(s["meta"].get("id"))] is None)]
    BT = [s for s in songs if s["meta"].get("group") in ("rhythm_fast", "rhythm_half_double_trap", "inst_full_band")
          or (str(s["meta"].get("id")) in taps and taps[str(s["meta"].get("id"))])]
    sig = {"RhythmExtractor confidence (current)": lambda s: float(s["rhythm_confidence"]),
           "TempoCNN confidence": lambda s: float(s["cand_tempocnn_conf"]),
           "TempoCNN: share of sections agreeing on tempo": lambda s: float(s["cand_tempocnn_agree"]),
           "Danceability model: P(danceable)": lambda s: float(s["cand_danceability_whole"][cls_index("danceability", "danceable", 0)]),
           "Essentia Danceability (current)": lambda s: float(s["rhythm_danceability"]),
           "Busyness (notes per second)": lambda s: float(s["rhythm_busyness"])}
    rows, res = [], {}
    for name, f in sig.items():
        try:
            a = auc([f(s) for s in BT], [f(s) for s in NB])
        except (KeyError, IndexError):
            continue
        res[name] = a; rows.append((name, a))
    if min(len(NB), len(BT)) >= 8 and res:
        R.table(["signal", "beat songs score higher than beatless songs (0.5 = guessing)"], rows)
        best = max(res, key=res.get)
        R.v("Best 'is there a beat?' signal", verdict(res[best] >= 0.85, res[best] >= 0.75),
            f"{best}: {res[best]:.2f} vs current {res.get('RhythmExtractor confidence (current)', float('nan')):.2f} (n={len(BT)} beat / {len(NB)} beatless)")
        summary["beat_signals"] = {n: round(v, 3) for n, v in res.items()}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-pool", action="store_true", help="also score the real pool songs (no human tags)")
    ap.add_argument("--split", choices=("all", "test", "validation"), default="all",
                    help="'test' = ONLY the official MTG-Jamendo test-split songs (the final honest score, written to "
                         "report_test.html); 'validation' = everything except them (report_validation.html)")
    a = ap.parse_args()
    rows, allsongs = load()
    if a.split != "all":
        test = mtg_test_ids()
        allsongs = [s for s in allsongs if (s["key"] in test) == (a.split == "test")]
        if a.split == "test" and not allsongs:
            raise SystemExit("no test-split songs analysed yet")
    # train_* songs only train our own mood model; pool_* songs have no human tags. Neither is scored.
    # songs you marked i_agree = n are left out of every scored test (their human label is wrong)
    songs = [s for s in allsongs if not s["meta"].get("group", "").startswith("train_")
             and not s["meta"].get("group", "").endswith("_vetoed")
             and (a.with_pool or not s["meta"].get("group", "").startswith("pool_"))]
    clip_songs = [s for s in allsongs if not s["meta"].get("group", "").startswith("train_")]
    print(f"{len(allsongs)} analysed songs ({len(songs)} scored, {len(clip_songs)} in the clip test)")
    R = Report()
    t0_data(R, rows, allsongs)
    if songs:
        t1_mood(R, songs); t2_sound(R, songs); t2b_genres(R, songs); t3_instruments(R, songs); t4_rhythm(R, songs); t5_parts(R, clip_songs)
        S, M = t6_overlap(R, songs); t7_same_artist(R, songs); P = t8_earn_place(R, S, M); t9_examples(R, S, P)
        summary = {}
        t11_evidence(R, S, M, summary); t13_polarity(R, S, M, summary); t12_balance(R, S, M, summary)
        t14_mood_candidates(R, songs, summary); t15_rhythm_candidates(R, songs, summary); t10_flags(R, songs)
        summary['songs_analysed'] = len(allsongs); summary['songs_scored'] = len(songs)
        summary['checks'] = [(a, b, c) for a, b, c in R.summary]
        with open(os.path.join(HERE, 'evidence_summary.json' if a.split == "all" else f'evidence_summary_{a.split}.json'), 'w') as f:
            json.dump(summary, f, indent=1, default=str)
    out = os.path.join(HERE, "report.html" if a.split == "all" else f"report_{a.split}.html"); R.write(out)
    for a_, b, c in R.summary:
        print(f"{b:5s} {a_}: {c}")
    print("\nreport written to", out)


if __name__ == "__main__":
    main()
