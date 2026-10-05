"""Find damaged result files (e.g. half-written when the PC was switched off) and queue those songs again.

  python check_results.py         # only reports
  python check_results.py --fix   # moves damaged files to results/damaged/ and marks those songs 'failed',
                                  # so the next run of their list analyses them again

Nothing is deleted: damaged files are moved, not removed. Files changed in the last 3 minutes are skipped
(an analysis run may be writing them right now).
"""
import csv, glob, json, os, shutil, sys, time
import numpy as np
from results_index import latest_rows, RES

NEEDED = ("effnet_whole", "effnet_parts", "instruments_whole", "emomusic_whole", "rhythm_bpm")


def check(path):
    try:
        with np.load(path) as d:
            missing = [k for k in NEEDED if k not in d.files]
            for k in NEEDED:
                if k in d.files:
                    _ = d[k]                       # actually read the data, not just the table of contents
        return f"missing {', '.join(missing)}" if missing else None
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:80]}"


def main():
    fix = "--fix" in sys.argv
    rows = latest_rows(RES)
    now = time.time()
    bad = []
    files = sorted(glob.glob(os.path.join(RES, "*.npz")))
    for p in files:
        if p.endswith(".tmp.npz") or now - os.path.getmtime(p) < 180:
            continue
        err = check(p)
        if err:
            bad.append((os.path.basename(p)[:-4], p, err))
    metas = sorted(glob.glob(os.path.join(RES, "meta", "*.json")))
    seen = {k for k, _, _ in bad}
    for p in metas:                                   # the song info files (title, artist, ...) too
        if p.endswith(".tmp") or now - os.path.getmtime(p) < 180:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                json.load(f)
        except Exception as e:
            k = os.path.basename(p)[:-5]
            if k not in seen:
                bad.append((k, os.path.join(RES, f"{k}.npz"), f"info file damaged ({type(e).__name__})"))
                seen.add(k)
    print(f"checked {len(files)} result files and {len(metas)} info files: {len(bad)} damaged")
    for k, p, err in bad:
        print(f"  {k:24s} {err}   (group: {rows.get(k, {}).get('group', '?')})")
    if not bad or not fix:
        if bad:
            print("\nrun again with --fix to move them aside and queue those songs for a new analysis")
        return
    qdir = os.path.join(RES, "damaged"); os.makedirs(qdir, exist_ok=True)
    import run_tests                                    # same index format as the analysis runs
    for k, p, err in bad:
        if os.path.exists(p):                               # move the numbers AND the info file, so the
            shutil.move(p, os.path.join(qdir, os.path.basename(p)))      # next run redoes the song completely
        mp = os.path.join(RES, "meta", f"{k}.json")
        if os.path.exists(mp):
            shutil.move(mp, os.path.join(qdir, f"{k}.json"))
        r = dict(rows.get(k, {}))
        r.update(key=k, status="failed", error=f"damaged result file ({err})"[:200])
        run_tests.write_row({c: r.get(c) for c in run_tests.FIELDS if c in r})
    print(f"\nmoved {len(bad)} file(s) to results/damaged/ and marked them failed. To analyse them again, run:")
    from results_index import list_key
    here = os.path.dirname(os.path.abspath(__file__))
    lists = set()
    for fn in ("edge_cases.csv", "bigpass.csv", "pool_list.csv", "pool_audius.csv", "pool_korean.csv", "pool_audius_more.csv", "pool_vocal.csv", "pool_fma.csv"):
        fp = os.path.join(here, fn)
        if os.path.exists(fp):
            with open(fp, encoding="utf-8-sig") as f:
                if {list_key(r) for r in csv.DictReader(f)} & {k for k, _, _ in bad}:
                    lists.add(fn)
    for fn in sorted(lists):
        print(f"  python -u run_tests.py --list {fn}" + ("   (edge-case songs)" if fn == "edge_cases.csv" else ""))
    print("(each run only redoes the songs that need it)")


if __name__ == "__main__":
    main()
