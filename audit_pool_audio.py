"""Keep NON-songs out of the pool by what the AUDIO sounds like (the genre model's stored top-5 tags for every analysed song).

  python audit_pool_audio.py            # dry run: list what would be removed and why
  python audit_pool_audio.py --apply    # mark those songs i_agree = n in their pool lists (stored numbers stay in results/)

The Discogs genre model has 13 'Non-Music' classes (audiobook, comedy, dialogue, education, interview, monolog, poetry,
political, promotional, radioplay, spoken word, religious, field recording) and 3 'Children's' classes. Rules:
  * the song's top genre is Non-Music or Children's                                     -> remove
  * spoken score (sum of the spoken-word tags in the top 5) >= 0.10 on YouTube          -> remove (talk, lessons, reviews)
    >= 0.15 on Jamendo / FMA / Audius (acapella and spoken-word songs are real songs there)
  * exception: an "(Official ...)" title with 1M+ views stays unless the score is >= 0.25
Every removal is appended to pool_audit_log.csv with the reason. Titles are checked separately (build_youtube.NOT_A_SONG).
"""
import argparse, csv, json, os, shutil, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import pool_keys, POOL_LISTS, list_key, RES

SPOKEN = ("Audiobook", "Comedy", "Dialogue", "Education", "Interview", "Monolog", "Poetry", "Political", "Promotional",
          "Radioplay", "Spoken Word")
LOG = os.path.join(HERE, "pool_audit_log.csv")


def audit():
    classes = json.load(open(os.path.join(HERE, "models", "genre_discogs400-discogs-effnet-1.json"), encoding="utf-8"))["classes"]
    members, info, out = pool_keys(), {}, []
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                if list_key(r) in members:
                    info[list_key(r)] = r
    for k, r in info.items():
        p = os.path.join(RES, f"{k}.npz")
        if not os.path.exists(p):
            continue
        try:
            with np.load(p) as d:
                idx, pr = d["genre_top5_idx"], d["genre_top5_p"]
        except Exception:
            continue
        names = [classes[int(i)] for i in idx]
        top1 = names[0].split("---")[0]
        spoken = sum(float(q) for c, q in zip(names, pr) if c.split("---")[-1] in SPOKEN and c.startswith("Non-Music"))
        views = float(r.get("listens") or 0) if k.startswith("youtube_") else 0
        official = "(official" in (r.get("title") or "").lower() and views >= 1_000_000
        why = ""
        if top1 in ("Non-Music", "Children's"):
            why = f"top genre is {names[0]}"
        elif spoken >= (0.10 if k.startswith("youtube_") else 0.15) and not (official and spoken < 0.25):
            why = f"spoken-word score {spoken:.2f}"
        if why:
            out.append((k, r, why, spoken))
    return out, len(info)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    found, n = audit()
    print(f"{len(found)} of {n} analysed pool songs fail the audio check")
    for k, r, why, s in sorted(found, key=lambda x: -x[3]):
        print(f"  {k[:22]:22s} {str(r.get('title'))[:50]:50s} | {str(r.get('artist'))[:18]:18s} {why}")
    if not a.apply or not found:
        print("(dry run: nothing changed)" if not a.apply else "")
        return
    bad = {k for k, *_ in found}
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        if not rows:
            continue
        cols, n_marked = list(rows[0].keys()), 0
        for r in rows:
            if list_key(r) in bad and (r.get("i_agree") or "").strip().lower() not in ("n", "no"):
                r["i_agree"] = "n"; n_marked += 1
        if n_marked:
            with open(p + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
            shutil.copy2(p, p + ".bak"); os.replace(p + ".tmp", p)
            print(f"  {fn}: {n_marked} marked i_agree = n")
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "key", "title", "artist", "reason"])
        for k, r, why, s in found:
            w.writerow([time.strftime("%Y-%m-%d"), k, r.get("title"), r.get("artist"), why])
    print(f"logged in {os.path.basename(LOG)}")


if __name__ == "__main__":
    main()
