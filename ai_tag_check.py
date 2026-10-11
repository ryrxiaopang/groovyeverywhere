"""Check the AI-music tagger against a person's judgement: how often is it right, and how much AI music does it miss?

  python ai_tag_check.py --make                       # writes ai_check_sheet.csv (tags hidden) and results/ai_check_key.csv (do not open the key)
  python ai_tag_check.py --score ai_check_sheet.csv    # after you filled the last column: precision, misses, and a PASS / FAIL on the marks below

Why: tag_ai.py was tuned on 5 songs and has never had a measured error rate. It decides which songs leave the pool (AI songs under 10,000 views), so
every false alarm removes a real small artist and every miss leaves AI filler in the lists.

The sample is 100 YouTube pool songs in five groups (the tag decides the group, the sheet never shows it):
  C  confirmed (the text says AI)                 12      LL likely, under 10,000 views (dropped by the policy)   20
  LH likely, 10,000+ views (kept)                 10      NL untagged, under 10,000 views (where missed AI hides)  28
  NH untagged, 10,000+ views (the control)        30
Order is shuffled. Group sizes in the whole pool are stored with the key, so the results are scaled to the real pool, not to the sample.

HOW TO JUDGE (about a minute a song, 90 minutes in all). Listen 30 s, then look at the channel and the description:
  y       you are fairly sure the song is AI-made: the description says so, the channel posts many similar songs with generic titles / thumbnails,
          or the voice and lyrics sound like typical AI output
  n       a real artist or a real recording: other releases, live clips, social links, a distinct voice and style
  unsure  you cannot tell. Do not spend more time; unsure answers are left out of the main numbers and reported separately
Your judgement is the reference here, so it can be wrong too; the numbers below are only as good as it is.

PASS MARKS, fixed before anyone listens (11 Oct 2026; do not change after seeing results):
  * of songs tagged LIKELY, at least 70% are judged AI-made       (below that, the policy removes too many real artists)
  * of songs tagged CONFIRMED, at least 90% are judged AI-made     (confirmed is meant to be near-certain)
  * of UNTAGGED songs, at most 10% are judged AI-made              (above that, the tagger misses too much)
Each is judged on the point estimate; the 95% range is printed beside it (with 100 songs the ranges are wide: a result near a mark is "not settled").
"""
import argparse, csv, math, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES

HIGH_VIEWS = 10_000                       # the hide-low policy keeps AI songs at or above this (tag_ai.HIGH_VIEWS)
SIZES = {"C": 12, "LL": 20, "LH": 10, "NL": 28, "NH": 30}
NAMES = {"C": "confirmed", "LL": "likely, under 10,000 views", "LH": "likely, 10,000+ views",
         "NL": "untagged, under 10,000 views", "NH": "untagged, 10,000+ views"}
MARK_LIKELY, MARK_CONFIRMED, MARK_MISSED = 0.70, 0.90, 0.10
SHEET = os.path.join(HERE, "ai_check_sheet.csv")
KEY = os.path.join(RES, "ai_check_key.csv")


def stratum(status, views):
    if status == "confirmed":
        return "C"
    if status == "likely":
        return "LL" if views < HIGH_VIEWS else "LH"
    return "NL" if views < HIGH_VIEWS else "NH"


def load_frame(here=HERE, res=RES):
    """YouTube pool songs with a tag record: key, title, channel, link, status, views."""
    from pool_summary import read_pool
    tags = {}
    with open(os.path.join(res, "ai_tags.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            tags[r["key"]] = r
    out = []
    for r in read_pool(here):
        t = tags.get(r["key"])
        if r["site"] != "youtube" or t is None:
            continue
        vid = r["key"].split("_", 1)[1]
        out.append(dict(key=r["key"], title=r.get("title") or "", channel=t.get("channel") or r.get("artist") or "",
                        link=r.get("listen") or f"https://www.youtube.com/watch?v={vid}", status=t["status"],
                        views=float(t.get("views") or 0)))
    return out


def draw_sample(frame, seed=11, sizes=SIZES):
    """(sample rows with their group, population size per group). A group smaller than its quota is taken whole. Shuffled."""
    rng = random.Random(seed)
    groups = {g: [] for g in sizes}
    for r in sorted(frame, key=lambda r: r["key"]):
        groups[stratum(r["status"], r["views"])].append(r)
    pops = {g: len(v) for g, v in groups.items()}
    sample = []
    for g, rows in groups.items():
        for r in rng.sample(rows, min(sizes[g], len(rows))):
            sample.append(dict(r, group=g))
    rng.shuffle(sample)
    return sample, pops


def make(frame=None, sheet=SHEET, key=KEY, seed=11):
    frame = frame if frame is not None else load_frame()
    sample, pops = draw_sample(frame, seed)
    n_conf_low = sum(1 for r in frame if r["status"] == "confirmed" and r["views"] < HIGH_VIEWS)
    os.makedirs(os.path.dirname(key), exist_ok=True)
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "listen_here", "title", "channel", "ai? (y / n / unsure)", "how you decided (optional)"])
        for i, r in enumerate(sample, 1):
            w.writerow([f"ai-{i:03d}", r["link"], r["title"], r["channel"], "", ""])
    with open(key, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "key", "group", "status", "views", "pop_C", "pop_LL", "pop_LH", "pop_NL", "pop_NH", "pop_C_under_10k"])
        for i, r in enumerate(sample, 1):
            w.writerow([f"ai-{i:03d}", r["key"], r["group"], r["status"], int(r["views"]), pops["C"], pops["LL"], pops["LH"], pops["NL"], pops["NH"], n_conf_low])
    return len(sample), pops


def wilson(k, n, z=1.96):
    """95% range for a share k out of n (Wilson). (nan, nan) when n = 0."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def read_answers(paths, key=None):
    """{group: [yes, no, unsure]} and the population sizes, from the filled sheets and the key."""
    info = {}
    with open(key or KEY, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            info[r["item"]] = r
    counts = {g: [0, 0, 0] for g in SIZES}
    pops = {}
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = info.get(r["item"])
                a = (r.get("ai? (y / n / unsure)") or "").strip().lower()[:1]
                if not k or a not in ("y", "n", "u"):
                    continue
                counts[k["group"]][{"y": 0, "n": 1, "u": 2}[a]] += 1
                pops = {g: int(k["pop_" + g]) for g in SIZES}
                pops["C_under_10k"] = int(k["pop_C_under_10k"])
    return counts, pops


def estimates(counts, pops, draws=4000, seed=0, unsure="exclude"):
    """Point estimates and 95% ranges of the tagger's quality, scaled to the pool. unsure: 'exclude' (main), 'ai' or 'real' (bounds)."""
    def k_n(g):
        y, n_, u = counts[g]
        return (y + (u if unsure == "ai" else 0), y + n_ + (u if unsure != "exclude" else 0))
    p = {g: (k_n(g)[0] / k_n(g)[1] if k_n(g)[1] else float("nan")) for g in SIZES}
    rng = np.random.default_rng(seed)
    d = {g: (rng.beta(k_n(g)[0] + 0.5, k_n(g)[1] - k_n(g)[0] + 0.5, draws) if k_n(g)[1] else np.full(draws, np.nan)) for g in SIZES}

    def metrics(q):
        likely = (pops["LL"] * q["LL"] + pops["LH"] * q["LH"]) / max(pops["LL"] + pops["LH"], 1)
        untagged = (pops["NL"] * q["NL"] + pops["NH"] * q["NH"]) / max(pops["NL"] + pops["NH"], 1)
        c_low = pops["C_under_10k"]
        ai_total = sum(pops[g] * q[g] for g in SIZES)
        caught = pops["C"] * q["C"] + pops["LL"] * q["LL"] + pops["LH"] * q["LH"]
        wrongly_dropped = c_low * (1 - q["C"]) + pops["LL"] * (1 - q["LL"])            # real songs the hide-low policy removes
        ai_left = (pops["C"] - c_low) * q["C"] + pops["LH"] * q["LH"] + pops["NL"] * q["NL"] + pops["NH"] * q["NH"]   # AI songs still in the pool
        return dict(confirmed=q["C"], likely=likely, untagged=untagged, recall=caught / ai_total if ai_total else float("nan"),
                    wrongly_dropped=wrongly_dropped, ai_left=ai_left, ai_total=ai_total)

    point = metrics(p)
    ranges = {}
    keys = list(point)
    out = [metrics({g: d[g][i] for g in SIZES}) for i in range(draws)]
    for k in keys:
        v = np.array([o[k] for o in out], float)
        ranges[k] = tuple(np.nanpercentile(v, [2.5, 97.5])) if np.isfinite(v).any() else (float("nan"), float("nan"))
    return point, ranges


def verdict(point):
    def mark(x, ok):
        return "unknown" if not np.isfinite(x) else ("PASS" if ok else "FAIL")
    return {"likely": mark(point["likely"], point["likely"] >= MARK_LIKELY),
            "confirmed": mark(point["confirmed"], point["confirmed"] >= MARK_CONFIRMED),
            "untagged": mark(point["untagged"], point["untagged"] <= MARK_MISSED)}


def score(paths, key=None):
    counts, pops = read_answers(paths, key)
    n_all = sum(sum(c) for c in counts.values())
    if not n_all:
        raise SystemExit("no answers found: fill the last-but-one column with y, n or unsure")
    print(f"{n_all} songs answered, {sum(c[2] for c in counts.values())} of them 'unsure' (left out of the main numbers)\n")
    print(f"{'group':32s} {'pool':>6s} {'judged AI':>10s} {'share':>7s}  95% range    unsure")
    for g in SIZES:
        y, n_, u = counts[g]
        lo, hi = wilson(y, y + n_)
        share = f"{100 * y / (y + n_):5.0f}%" if y + n_ else "    -"
        print(f"{NAMES[g]:32s} {pops[g]:6d} {y:4d} of {y + n_:<3d} {share}  ({100 * lo:3.0f}-{100 * hi:3.0f}%)  {u:4d}")
    point, rng = estimates(counts, pops)
    v = verdict(point)
    print("\nScaled to the whole pool (95% ranges):")
    pct = lambda k: f"{100 * point[k]:4.0f}% ({100 * rng[k][0]:.0f}-{100 * rng[k][1]:.0f}%)"
    print(f"  tagged LIKELY that really are AI:      {pct('likely')}   mark: at least {100 * MARK_LIKELY:.0f}%   {v['likely']}")
    print(f"  tagged CONFIRMED that really are AI:   {pct('confirmed')}   mark: at least {100 * MARK_CONFIRMED:.0f}%   {v['confirmed']}")
    print(f"  UNTAGGED songs that are really AI:     {pct('untagged')}   mark: at most {100 * MARK_MISSED:.0f}%   {v['untagged']}")
    print(f"  share of all AI music the tagger finds: {pct('recall')}")
    print(f"  real songs the hide-low policy removes: about {point['wrongly_dropped']:.0f} (range {rng['wrongly_dropped'][0]:.0f}-{rng['wrongly_dropped'][1]:.0f})")
    print(f"  AI songs still in the pool:             about {point['ai_left']:.0f} (range {rng['ai_left'][0]:.0f}-{rng['ai_left'][1]:.0f})")
    if sum(c[2] for c in counts.values()):
        lo_p, _ = estimates(counts, pops, unsure="real")
        hi_p, _ = estimates(counts, pops, unsure="ai")
        print(f"\nIf every 'unsure' were real: likely {100 * lo_p['likely']:.0f}%, untagged {100 * lo_p['untagged']:.0f}%. "
              f"If every 'unsure' were AI: likely {100 * hi_p['likely']:.0f}%, untagged {100 * hi_p['untagged']:.0f}%.")
    print("\nA result close to a mark, or with a range that crosses it, is not settled with this many songs. Your judgement is the reference, so it can be wrong too.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--score", nargs="+", metavar="FILLED_SHEET")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    if a.make:
        if os.path.exists(SHEET):
            raise SystemExit(f"{SHEET} exists: move it away first (a new sample would not match the answers already given)")
        n, pops = make(seed=a.seed)
        print(f"wrote {SHEET} ({n} songs) and {KEY}. Pool sizes of the groups: " + ", ".join(f"{g} {v}" for g, v in pops.items()))
        print("Fill the column 'ai? (y / n / unsure)' (see the top of ai_tag_check.py for how), do not open the key file, then:\n"
              "  python ai_tag_check.py --score ai_check_sheet.csv")
    elif a.score:
        score(a.score)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
