"""Voice numbers for a list of songs (resumable). Run inside the GPU environment:

  source .venv-voice/bin/activate
  bash -ic 'cd ~/groovyeverywhere && source .venv-voice/bin/activate && python -u run_voice.py --list voice_dev.csv'

Same rules as run_tests.py: one song at a time, audio only in a TemporaryDirectory (deleted straight away), the separated
vocals live in memory only, and only numbers are written: results/voice/<key>.npz + results/voice/index.csv.
Never run two analysis runs at once (the GPU run and a run_tests.py run are different files, but both download).

  --list FILE      CSV with a jamendo_id column (voice_dev.csv, test_split.csv, voice_test_extra.csv ...)
  --limit N        first N songs only (quick try / timing)
  --recheck-missing  try again songs earlier marked 'no longer available'
"""
import argparse, csv, os, sys, time, traceback
import numpy as np

import analyze_voice, sources

HERE = os.path.dirname(os.path.abspath(__file__))
VRES = os.path.join(HERE, "results", "voice")
INDEX = os.path.join(VRES, "index.csv")
FIELDS = ["key", "status", "error", "duration", "n_windows", "t_decode", "t_separate", "t_embed", "t_total"]
MAX_FAILS = 3
MAX_IN_A_ROW = 5          # this many failed songs in a row means something systemic is wrong (GPU, disk, network): stop


def done_keys(recheck_missing=False):
    if not os.path.exists(INDEX):
        return set()
    last, fails = {}, {}
    with open(INDEX, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            last[r["key"]] = r["status"]
            if r["status"] == "failed":
                fails[r["key"]] = fails.get(r["key"], 0) + 1
    keep = ("done", "not_downloadable") if recheck_missing else ("done", "not_downloadable", "missing")
    given_up = set() if recheck_missing else {k for k, n in fails.items() if n >= MAX_FAILS and last[k] == "failed"}
    return {k for k, s in last.items() if s in keep and (s != "done" or os.path.exists(os.path.join(VRES, f"{k}.npz")))} | given_up


def write_row(row):
    new = not os.path.exists(INDEX)
    with open(INDEX, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush(); os.fsync(f.fileno())


def process(key, ctx):
    """Analyse one song and record the outcome. Returns the status ('done', 'failed', ...)."""
    row = {"key": key}
    try:
        with ctx as path:
            feats, T = analyze_voice.analyse(path)
        final = os.path.join(VRES, f"{key}.npz"); tmp = final[:-4] + ".tmp.npz"
        np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in feats.items()})
        os.replace(tmp, final)
        row.update(status="done", duration=round(float(feats["duration"]), 1), n_windows=len(feats["win_start"]),
                   **{f"t_{k}": round(v, 2) for k, v in T.items()})
        print(f"  ok  {key:22s} {float(feats['duration']):6.0f}s  {len(feats['win_start'])} windows  "
              f"{T['total']:5.1f}s (separate {T['separate']:.1f}, embed {T['embed']:.1f})")
    except PermissionError:
        row.update(status="not_downloadable"); print(f"  --  {key}: not downloadable, skipped")
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):
            row.update(status="missing", error=f"gone ({code})"); print(f"  --  {key}: no longer available ({code})")
        else:
            row.update(status="failed", error=str(sources.safe_exc(e))[:200])      # safe_exc hides API keys in the text
            print(f"  !!  {key}: {row['error']}"); traceback.print_exc(limit=1)
    write_row(row)
    return row["status"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--recheck-missing", action="store_true")
    a = ap.parse_args()
    os.makedirs(VRES, exist_ok=True)
    if not os.environ.get("JAMENDO_CLIENT_ID"):
        sys.exit("JAMENDO_CLIENT_ID is not set: start this with `bash -ic` (or source env_keys.sh) so the key is loaded.")
    if not analyze_voice.FAKE:
        import torch
        if not torch.cuda.is_available():
            sys.exit("No GPU visible to PyTorch: on a CPU this would take days. Stopping (see VOICE_PIPELINE.md section 6).")
    n_old = sources.sweep_stale_temp()
    if n_old:
        print(f"removed {n_old} leftover audio folder(s) from an earlier run that was stopped hard")
    skip = done_keys(a.recheck_missing)
    with open(os.path.join(HERE, a.list), encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)]
    rows = [r for r in rows if (r.get("i_agree") or "").strip().lower() not in ("n", "no")]
    ids = []
    for r in rows:
        if not r.get("jamendo_id"):
            continue
        if f"jamendo_{r['jamendo_id']}" not in skip and int(r["jamendo_id"]) not in ids:
            ids.append(int(r["jamendo_id"]))
    if a.limit:
        ids = ids[: a.limit]
    print(f"{len(rows)} songs in {a.list}, {len(ids)} still to do")
    t0, n, in_a_row = time.time(), 0, 0
    meta = {}
    for i in range(0, len(ids), 100):             # look up 100 at a time so a long list starts working at once
        meta.update(sources.jamendo_tracks(ids[i:i + 100]))
        for jid in ids[i:i + 100]:
            key = f"jamendo_{jid}"
            info = meta.get(jid)
            if info is None:
                write_row({"key": key, "status": "missing", "error": "not on Jamendo"})
                print(f"  --  {key}: no longer on Jamendo"); continue
            status = process(key, sources.temp_audio(info))
            n += 1
            in_a_row = in_a_row + 1 if status == "failed" else 0
            if in_a_row >= MAX_IN_A_ROW:
                sys.exit(f"!! {in_a_row} songs failed in a row: stopping instead of working through the whole list. "
                         "Fix the cause (see the errors above), then run the same command again; finished songs are skipped.")
    print(f"done {n} songs in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
