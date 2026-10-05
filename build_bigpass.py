"""Song lists for the big overnight pass (MTG-Jamendo songs, all with human tags).

  python build_bigpass.py        -> bigpass.csv

Two parts, from DIFFERENT official splits so nothing leaks:
  eval_*   ~1,500 songs from the VALIDATION split (not already in edge_cases.csv):
           every song tagged happy or sad, plus up to 60 per genre family, plus a random fill.
           Used to measure the models with bigger, steadier numbers.
  train_*  ~800 songs from the TRAINING split, tagged happy or sad (not both):
           used ONLY to train our own small happy/sad model (train_mood.py), never to score it.
The TEST split is not touched: it is kept for the final score.
About 30% of songs are expected to be gone from Jamendo, so the lists are over-filled.
"""
import csv, random
import select_edge_cases as base
from expand_edge_cases import GENRES

random.seed(23)
N_EVAL_GENRE = 60          # per genre family
N_EVAL_TOTAL = 1500
N_TRAIN_PER_SIDE = 400

HAPPY = base.HAPPY
SAD = {"sad", "melancholic", "dark"}


def pick(rows, n, used, per_artist=2):
    random.shuffle(rows)
    out, artists = [], {}
    for r in rows:
        if len(out) >= n:
            break
        if r["jamendo_id"] in used or artists.get(r["artist"], 0) >= per_artist:
            continue
        out.append(r); used.add(r["jamendo_id"]); artists[r["artist"]] = artists.get(r["artist"], 0) + 1
    return out


def row(r, group, why):
    return dict(group=group, jamendo_id=r["jamendo_id"], mtg_track=r["track"], artist=r["artist"], album=r["album"],
                duration=r["duration"], tags=r["tags"], expect=why,
                listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree="")


def main():
    with open("edge_cases.csv") as f:
        fields = list(csv.DictReader(f).fieldnames)
        f.seek(0); used = {int(r["jamendo_id"]) for r in csv.DictReader(f)}
    val = [r for r in base.load(base.SPLIT) if base.normal_len(r)]
    out = []
    # 1. every happy-only / sad-only validation song
    for side, flt in (("happy", lambda r: r["mood"] & HAPPY and not r["mood"] & SAD),
                      ("sad", lambda r: r["mood"] & SAD and not r["mood"] & HAPPY)):
        got = pick([r for r in val if flt(r)], 400, used, per_artist=3)
        out += [row(r, f"eval_mood_{side}", f"{side}-tagged, any genre: steadier happy-vs-sad tests") for r in got]
        print(f"eval_mood_{side:6s} {len(got)}")
    # 2. genre families
    allg = set().union(*GENRES.values())
    for g, tags in GENRES.items():
        other = allg - tags
        got = pick([r for r in val if r["genre"] & tags and not r["genre"] & other], N_EVAL_GENRE, used)
        out += [row(r, f"eval_genre_{g}", f"genre family '{g}': Sound-vs-genre test") for r in got]
        print(f"eval_genre_{g:14s} {len(got)}")
    # 3. random fill up to the total
    left = N_EVAL_TOTAL - len(out)
    if left > 0:
        got = pick(list(val), left, used)
        out += [row(r, "eval_random", "random validation song: realistic mix") for r in got]
        print(f"eval_random         {len(got)}")
    # 4. training songs for our own happy/sad model (TRAIN split only)
    train = [r for r in base.load("data/split0-autotagging-train.tsv") if base.normal_len(r)]
    for side, flt in (("happy", lambda r: r["mood"] & HAPPY and not r["mood"] & SAD),
                      ("sad", lambda r: r["mood"] & SAD and not r["mood"] & HAPPY)):
        got = pick([r for r in train if flt(r)], N_TRAIN_PER_SIDE, used, per_artist=3)
        out += [row(r, f"train_mood_{side}", "TRAINING ONLY for our own mood model; never used to score") for r in got]
        print(f"train_mood_{side:5s} {len(got)}")
    with open("bigpass.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(out)
    print(f"\nbigpass.csv: {len(out)} songs (expect ~70% to be downloadable)")


if __name__ == "__main__":
    main()
