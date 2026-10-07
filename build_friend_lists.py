"""Build every friend's three blind-test lists (A Sound only, B Sound + what they love, C random same genre) from the
songs in friends_inputs.csv, using the full analysis of each friend's song (results/youtube_<id>.npz) against the pool.

  python build_friend_lists.py                 # PREVIEW: writes results/blind_preview/*.json, never results/blind/
  python build_friend_lists.py --final         # the real captures (results/blind/), for blind_test.py --sheets

The experimenter should not read the lists (blind_test.py's rule: "Don't look at results/blind/ yourself"): this script
prints only checks that do not reveal which song is in which list (sizes, closest-match strength, genre group).
Feature for list B = the `confirmed` column of friends_inputs.csv, else the proposed one.
"""
import argparse, csv, os
import numpy as np
import blind_test as bt

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if not a.final:
        bt.BLIND = os.path.join(bt.RES, "blind_preview")
    rows = list(csv.DictReader(open(os.path.join(HERE, "friends_inputs.csv"), encoding="utf-8-sig")))
    print(f"{len(rows)} friend answers -> {'results/blind (FINAL)' if a.final else 'results/blind_preview (preview)'}")
    bt.pool()
    made = 0
    for r in rows:
        feature = (r.get("confirmed") or r.get("proposed_feature_for_list_B") or "sound").strip()
        label = f"{r['friend']}: {r['song']}"
        if not bt.valid_feature(feature):
            print(f"  !! {label}: unknown feature {feature!r}"); continue
        p = os.path.join(bt.RES, f"youtube_{r['youtube_id']}.npz")
        if not os.path.exists(p):
            print(f"  -- {label}: not analysed yet, skipped"); continue
        with np.load(p) as d:
            q = bt.query_from_analysis(dict(d))
        lists = bt.make_lists(q, feature, seed=a.seed)
        sizes = {k: len(lists[k]) for k in "ABC"}
        fn = bt.save_capture(r["friend"], f"{r['song']} - {r['artist']}", feature, q, lists, signal="full song, YouTube")
        flag = []
        if lists["weak_capture"]:
            flag.append("weak match")
        if min(sizes.values()) < bt.K:
            flag.append("a list is short")
        print(f"  ok {label:42.42s} feature={feature:18s} lists A/B/C={sizes['A']}/{sizes['B']}/{sizes['C']} "
              f"closest Sound {lists['best_sound_cosine']:.2f} genre={lists['genre_group']} {' '.join(flag)}")
        made += 1
    print(f"{made} captures written")


if __name__ == "__main__":
    main()
