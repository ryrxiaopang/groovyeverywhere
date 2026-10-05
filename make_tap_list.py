"""Make taps.csv: 50 analysed songs to tap along to (ground truth for Rhythm).

  python make_tap_list.py     -> taps.csv

How to fill it: open each song's link, find a tap-tempo page (search "tap BPM"), tap along to the
beat you would naturally clap or nod to for 15-20 taps, and type the number into tapped_bpm.
Leave it blank if there is no beat you could tap to (that is useful too: write "none").
About 1 minute per song. Then run python evaluate.py: test T15 compares every tempo method to your taps.
"""
import csv, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
random.seed(3)
from results_index import latest_rows
rows = latest_rows(os.path.join(HERE, "results"))
done = [r for r in rows.values() if r["status"] == "done" and r.get("source") == "jamendo"
        and not r.get("group", "").startswith(("train_", "pool_"))]
by = {}
for r in done:
    g = r["group"]
    fam = "rhythm" if g.startswith("rhythm_") else ("genre" if "genre_" in g else "other")
    by.setdefault(fam, []).append(r)
pick = []
for fam, n in (("rhythm", 20), ("genre", 22), ("other", 8)):
    pool = by.get(fam, []); random.shuffle(pool)
    groups = {}
    for r in pool:
        groups.setdefault(r["group"], []).append(r)
    taken = []
    while len(taken) < n and any(groups.values()):        # one song per group in turn: spread across groups
        for g in list(groups):
            if groups[g] and len(taken) < n:
                taken.append(groups[g].pop())
    pick += taken
out = os.path.join(HERE, "taps.csv")
filled = {}
if os.path.exists(out):                     # never throw away taps already typed in
    with open(out, encoding="utf-8-sig") as f:
        old = list(csv.DictReader(f))
    filled = {r["jamendo_id"]: r for r in old if (r.get("tapped_bpm") or "").strip()}
    if old and not ("--new" in sys.argv):
        print(f"taps.csv already exists ({len(filled)} of {len(old)} songs tapped); keeping it. "
              "Use the tapping page: python capture_server.py, then http://localhost:8765/tap")
        sys.exit(0)
    os.replace(out, out + ".bak")
ids = {str(r["id"]) for r in pick}
rows = [dict(jamendo_id=r["id"], title=r.get("title", ""), artist=r.get("artist", ""), group=r["group"],
             listen=f"https://www.jamendo.com/track/{r['id']}", tapped_bpm="") for r in pick]
rows += [dict(v) for k, v in filled.items() if k not in ids]          # earlier taps stay, even if not picked again
for r in rows:
    if str(r["jamendo_id"]) in filled:
        r["tapped_bpm"] = filled[str(r["jamendo_id"])]["tapped_bpm"]
with open(out + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["jamendo_id", "title", "artist", "group", "listen", "tapped_bpm"], extrasaction="ignore")
    w.writeheader(); w.writerows(rows)
os.replace(out + ".tmp", out)
print(f"taps.csv: {len(rows)} songs. Tap them on http://localhost:8765/tap (python capture_server.py), then run python evaluate.py")
