"""Step 1 of testing: analyse the edge-case songs (resumable, runs in the background).

  python run_tests.py                       # all edge-case songs from edge_cases.csv (Jamendo)
  python run_tests.py --limit 10            # quick first try (also gives the timing estimate)
  python run_tests.py --groups mood_loud_happy mood_loud_sad_dark
  python run_tests.py --audius 5            # + 5 downloadable Audius songs per search query
  python run_tests.py --local-dir some/dir  # your own test files (not stored or uploaded)

Results go to results/<source>_<id>.npz (numbers only) + results/index.csv.
Songs already in results/ are skipped, so you can stop and restart any time.
Then run:  python evaluate.py
"""
import argparse, csv, glob, json, os, time, traceback
import numpy as np

import analyze, sources

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
INDEX = os.path.join(RES, "index.csv")
FIELDS = ["key", "source", "id", "group", "title", "artist", "album", "mtg_artist", "mtg_album", "duration_listed",
          "file_duration", "trimmed_duration", "full_length_ok", "download_allowed", "status", "error",
          "listens", "licence", "vocalinstrumental", "speed", "acousticelectric", "gender", "site_bpm",
          "site_genre", "site_mood", "page", "tags", "t_decode", "t_effnet", "t_effnet_heads", "t_mood",
          "t_rhythm", "t_total"]

AUDIUS_QUERIES = ["acoustic guitar", "piano", "drum and bass", "lofi", "ambient", "punk", "sad", "happy",
                  "jazz", "reggae", "latin", "country", "metal", "classical", "house", "folk", "soul", "afrobeat"]


MAX_FAILS = 3


def done_keys(recheck_missing=False):
    """Songs to skip: the LAST recorded status per song decides."""
    if not os.path.exists(INDEX):
        return set()
    last, ever_done, fails = {}, set(), {}
    with open(INDEX, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            last[r["key"]] = r["status"]
            if r["status"] == "done":
                ever_done.add(r["key"])
            elif r["status"] == "failed" and "damaged result file" not in (r.get("error") or ""):
                fails[r["key"]] = fails.get(r["key"], 0) + 1
    keep = ("done", "not_downloadable") if recheck_missing else ("done", "not_downloadable", "missing")
    # a song analysed once keeps its numbers even if a later lookup said "missing" (Jamendo's lookups are flaky)
    ever_done = {k for k in ever_done if os.path.exists(os.path.join(RES, f"{k}.npz"))}
    # a song that failed 3 times is given up on (it was re-downloaded every run); --recheck-missing retries it
    given_up = set() if recheck_missing else {k for k, n in fails.items() if n >= MAX_FAILS and last[k] == "failed"}
    return {k for k, s in last.items() if s in keep} | ever_done | given_up


def write_row(row):
    new = not os.path.exists(INDEX)
    with open(INDEX, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        f.flush(); os.fsync(f.fileno())        # a power cut can't leave half a line that swallows the next row


META = os.path.join(RES, "meta")


def save_meta(key, info, extra):
    """Full song details (artist id, album, licence, popularity stats, site genre/mood/BPM) in a small JSON
    beside the results, so the catalogue can list every song neatly without changing index.csv's columns."""
    os.makedirs(META, exist_ok=True)
    keep = {k: v for k, v in info.items() if k not in ("download_url",)}
    final = os.path.join(META, f"{key}.json")
    with open(final + ".tmp", "w") as f:
        json.dump({**keep, **extra}, f, default=str)
    os.replace(final + ".tmp", final)


def process(key, info, path_ctx, extra):
    save_meta(key, info, extra)
    row = {"key": key, **extra, **{k: info.get(k) for k in FIELDS if k in info},
           "duration_listed": info.get("duration"), "download_allowed": info.get("download_allowed")}
    try:
        with path_ctx as path:
            feats, T = analyze.analyse(path, listed_duration=info.get("duration") or None)
        final = os.path.join(RES, f"{key}.npz"); tmp = final[:-4] + ".tmp.npz"
        np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in feats.items()})
        os.replace(tmp, final)          # all-or-nothing: a crash mid-write never leaves a broken file
        row.update(status="done", file_duration=round(feats["file_duration"], 1),
                   trimmed_duration=round(feats["trimmed_duration"], 1), full_length_ok=feats["full_length_ok"],
                   **{f"t_{k}": round(v, 2) for k, v in T.items()})
        print(f"  ok  {key:22s} {feats['file_duration']:6.0f}s  analysed in {T['total']:5.1f}s "
              f"(effnet {T['effnet']:.1f}, mood {T['mood']:.1f}, rhythm {T['rhythm']:.1f})")
    except PermissionError:
        row.update(status="not_downloadable"); print(f"  --  {key}: not downloadable, skipped")
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (404, 410):                 # the artist deleted the song or switched off downloads:
            row.update(status="missing", error=f"gone ({code})")   # not retried (--recheck-missing tries again)
            print(f"  --  {key}: no longer available ({code}), skipped")
            write_row(row); return
        row.update(status="failed", error=str(e)[:200]); print(f"  !!  {key}: {e}")
        traceback.print_exc(limit=1)
    write_row(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--groups", nargs="*")
    ap.add_argument("--audius", type=int, default=0, help="songs per Audius query")
    ap.add_argument("--local-dir")
    ap.add_argument("--list", default="edge_cases.csv",
                    help="song list to analyse: edge_cases.csv (default), bigpass.csv or pool_list.csv")
    ap.add_argument("--upgrade", action="store_true",
                    help="re-analyse finished songs that lack the newest candidate models (needs a new download)")
    ap.add_argument("--recheck-missing", action="store_true",
                    help="try again the songs earlier runs marked 'no longer available' or gave up on after 3 failures")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True)
    n_old = sources.sweep_stale_temp()
    if n_old:
        print(f"removed {n_old} leftover audio folder(s) from an earlier run that was stopped hard")
    skip = done_keys(a.recheck_missing)
    if a.upgrade:
        import analyze
        old = set()
        for k in skip:
            p = os.path.join(RES, f"{k}.npz")
            if os.path.exists(p):
                with np.load(p) as d:
                    if "analysis_version" not in d.files or float(d["analysis_version"]) < analyze.ANALYSIS_VERSION:
                        old.add(k)
        skip -= old
        print(f"--upgrade: {len(old)} finished songs will be analysed again with the new models")
    t0, n = time.time(), 0

    if a.local_dir:
        for p in sorted(glob.glob(os.path.join(a.local_dir, "*"))):
            if not p.lower().endswith((".mp3", ".wav", ".flac", ".ogg", ".m4a")):
                continue
            key = "local_" + os.path.splitext(os.path.basename(p))[0].replace(" ", "_")[:40]
            if key in skip:
                continue
            grp = os.path.basename(p).split("__")[0] if "__" in p else "local"
            process(key, {"source": "local", "id": key, "title": os.path.basename(p)},
                    _nullctx(p), {"group": grp})
            n += 1
        print(f"done {n} local files in {time.time()-t0:.0f}s"); return

    with open(os.path.join(HERE, a.list), encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if not a.groups or r["group"] in a.groups]
    if os.path.basename(a.list).startswith("pool"):  # pool songs you marked i_agree = n are left out of the pool (also for ./pool_x.csv or a full path)
        dropped = [r for r in rows if (r.get("i_agree") or "").strip().lower() in ("n", "no")]
        rows = [r for r in rows if r not in dropped]
        if dropped:
            print(f"{len(dropped)} songs marked i_agree = n are left out")
    if a.limit:
        rows = rows[: a.limit]
    src_of = lambda r: "".join(ch for ch in (r.get("source") or "jamendo").lower() if ch.isalpha()) or "jamendo"
    aud_rows = [r for r in rows if src_of(r) == "audius"]
    fma_rows = [r for r in rows if src_of(r) == "fma"]
    yt_rows = [r for r in rows if src_of(r) == "youtube"]
    rows = [r for r in rows if src_of(r) not in ("audius", "fma", "youtube")]
    todo = [r for r in rows if f"jamendo_{r['jamendo_id']}" not in skip]
    aud_todo = [r for r in aud_rows if f"audius_{r['track_id']}" not in skip]
    fma_todo = [r for r in fma_rows if f"fma_{r['track_id']}" not in skip]
    yt_todo = [r for r in yt_rows if f"youtube_{r['track_id']}" not in skip]
    print(f"{len(rows) + len(aud_rows) + len(fma_rows) + len(yt_rows)} songs in {a.list} "
          f"({len(rows)} Jamendo, {len(aud_rows)} Audius"
          + (f", {len(fma_rows)} FMA" if fma_rows else "") + (f", {len(yt_rows)} YouTube" if yt_rows else "")
          + f"), {len(todo) + len(aud_todo) + len(fma_todo) + len(yt_todo)} still to do")
    gone = 0
    meta = sources.jamendo_tracks([int(r["jamendo_id"]) for r in todo]) if todo else {}
    for r in todo:
        jid = int(r["jamendo_id"]); key = f"jamendo_{jid}"
        extra = {"group": r["group"], "tags": r.get("tags", ""), "mtg_artist": r.get("artist", ""),
                 "mtg_album": r.get("album", "")}
        info = meta.get(jid)
        if info is None and os.path.exists(os.path.join(RES, f"{key}.npz")):
            print(f"  --  {key}: lookup failed, keeping its earlier analysis"); continue
        if info is None:
            write_row({"key": key, "source": "jamendo", "id": jid, "status": "missing", **extra})
            print(f"  --  {key}: no longer on Jamendo"); gone += 1; continue
        process(key, info, sources.temp_audio(info), extra)
        n += 1

    for r in aud_rows:                     # Audius songs from pool_list.csv
        key = f"audius_{r['track_id']}"
        if key in skip:
            continue
        info = dict(source="audius", id=r["track_id"], title=r.get("title"), artist=r.get("artist"),
                    duration=float(r.get("duration") or 0), listens=r.get("listens"), licence=r.get("licence"),
                    page=r.get("listen"), site_bpm=r.get("site_bpm"), bpm_custom=r.get("bpm_custom"),
                    genre=r.get("site_genre"), mood=r.get("site_mood"), download_allowed=True,
                    download_url=f"{sources.AUDIUS}/tracks/{r['track_id']}/download")
        process(key, info, sources.temp_audio(info),
                {"group": r["group"], "site_bpm": r.get("site_bpm"), "site_genre": r.get("site_genre"),
                 "site_mood": r.get("site_mood")})
        n += 1

    for r in fma_todo:                     # Free Music Archive songs (pool_fma.csv), read one by one from the archive
        key = f"fma_{r['track_id']}"
        info = dict(source="fma", id=r["track_id"], title=r.get("title"), artist=r.get("artist"),
                    album=r.get("album"), duration=float(r.get("duration") or 0), listens=r.get("listens"),
                    licence=r.get("licence"), page=r.get("listen"), fma_genres=r.get("fma_genres"),
                    download_allowed=True, download_url="fma")
        process(key, info, sources.temp_audio(info), {"group": r["group"]})
        n += 1

    for r in yt_todo:                      # YouTube songs from pool_youtube.csv (audio deleted straight after analysis)
        vid = r["track_id"]; key = f"youtube_{vid}"
        info = dict(source="youtube", id=vid, title=r.get("title"), artist=r.get("artist"),
                    duration=float(r.get("duration") or 0), listens=r.get("listens"),
                    licence=r.get("licence") or "youtube-standard", page=r.get("listen"),
                    site_genre=r.get("site_genre"), download_allowed=True,
                    download_url=f"https://www.youtube.com/watch?v={vid}")
        process(key, info, sources.temp_audio(info),
                {"group": r["group"], "site_genre": r.get("site_genre")})
        n += 1

    if a.audius:
        for q in AUDIUS_QUERIES:
            try:
                found = sources.audius_search(q, limit=a.audius * 3)[: a.audius]
            except Exception as e:
                print("Audius search failed:", e); break
            for info in found:
                key = f"audius_{info['id']}"
                if key in skip:
                    continue
                process(key, info, sources.temp_audio(info),
                        {"group": f"audius_{q.replace(' ', '_')}", "site_bpm": info.get("site_bpm"),
                         "site_genre": info.get("genre"), "site_mood": info.get("mood")})
                n += 1
    el = time.time() - t0
    print(f"\nfinished {n} songs in {el/60:.1f} min ({el/max(n,1):.1f} s per song incl. download)"
          + (f"; {gone} skipped as no longer on Jamendo" if gone else ""))
    after_run(n)


def after_run(n):
    """Copy the new results into PostgreSQL, then (if HG_BACKUP_DIR is set) make a backup. Neither can lose
    data: the results/ files stay the raw record, the import only adds or updates rows, never deletes."""
    if n == 0:
        return
    try:
        import import_results
        import_results.main(quiet=True)
    except Exception as e:
        print(f"\n!! could not copy results into PostgreSQL ({e}).\n   Nothing is lost: results/ has everything. "
              "Start the database (sudo service postgresql start) and run: python import_results.py")
    if os.environ.get("HG_BACKUP_DIR"):
        try:
            import backup
            backup.main(["--to", os.environ["HG_BACKUP_DIR"]])
        except SystemExit:
            pass
        except Exception as e:
            print(f"!! backup failed ({e}); run python backup.py by hand")


class _nullctx:
    def __init__(self, p): self.p = p
    def __enter__(self): return self.p
    def __exit__(self, *a): return False


if __name__ == "__main__":
    main()
