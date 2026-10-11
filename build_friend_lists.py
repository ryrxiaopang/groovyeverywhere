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
    ap.add_argument("--no-exclude", action="store_true", help="allow songs already recommended to this friend in an earlier round "
                    "(by default they are left out: a friend is not asked to rate the same song twice)")
    ap.add_argument("--friend", action="append", help="only this friend (repeatable); a capture already made is never overwritten, so "
                    "use this when adding someone new")
    a = ap.parse_args()
    if not a.final:
        bt.BLIND = os.path.join(bt.RES, "blind_preview")
    rows = list(csv.DictReader(open(os.path.join(HERE, "friends_inputs.csv"), encoding="utf-8-sig")))
    if a.friend:
        rows = [r for r in rows if r["friend"] in a.friend]
    print(f"{len(rows)} friend answers -> {'results/blind (FINAL)' if a.final else 'results/blind_preview (preview)'}")
    bt.pool()
    # songs each friend was already shown in earlier captures: a snapshot taken BEFORE this run writes anything
    seen = {} if a.no_exclude else {r["friend"]: bt.previously_recommended(r["friend"]) for r in rows}
    if seen:
        print("already recommended earlier (left out): " + ", ".join(f"{f} {len(s)}" for f, s in seen.items()))
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
        lists = bt.make_lists(q, feature, seed=a.seed, start_title=r["song"], start_artist=r["artist"], exclude=seen.get(r["friend"]))
        sizes = {k: len(lists[k]) for k in bt.LISTS if lists.get(k) is not None and (k != "D" or bt.LIST_D)}
        fn = bt.save_capture(r["friend"], f"{r['song']} - {r['artist']}", feature, q, lists, signal="full song, YouTube")
        flag = []
        if lists["weak_capture"]:
            flag.append("weak match")
        if min(sizes.values()) < bt.K:
            flag.append("a list is short")
        print(f"  ok {label:42.42s} feature={feature:18s} lists {'/'.join(sizes)}={'/'.join(str(v) for v in sizes.values())} "
              f"closest Sound {lists['best_sound_cosine']:.2f} genre={lists['genre_group']} {' '.join(flag)}")
        made += 1
    print(f"{made} captures written")


if __name__ == "__main__":
    main()
