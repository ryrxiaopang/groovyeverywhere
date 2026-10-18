"""Back up everything that took time to make: results/ (all song numbers), the song lists, your hand-made files
(taps.csv, i_agree marks), the trained mood model, and a full copy of the PostgreSQL database.

  python backup.py                                   # makes backups/hidden-gems-<date>.zip and checks it
  python backup.py --to /mnt/c/Users/NAME/OneDrive/HiddenGemsBackups    # ... and copies it to Windows / OneDrive
  echo 'export HG_BACKUP_DIR=/mnt/c/Users/NAME/OneDrive/HiddenGemsBackups' >> ~/.bashrc
                                                     # then every analysis run backs up by itself when it finishes

The zip is checked after writing (every file read back) and the copy is checked by size. Only the 2 newest
backups are kept in backups/ and in the --to folder (--keep-to N or HG_BACKUP_KEEP=N to change; 0 keeps all).
Only older backup ZIPS are removed, never the results themselves, and only after the new copy is checked.
To restore on any machine, see RESTORE.txt inside the zip.
"""
import argparse, glob, json, os, shutil, subprocess, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "backups")
DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")
FILES = ["edge_cases.csv", "bigpass.csv", "pool_list.csv", "pool_audius.csv", "pool_korean.csv",
         "pool_audius_more.csv", "pool_vocal.csv", "pool_fma.csv", "pool_youtube.csv", "test_split.csv", "test_split_freeze.json", "taps.csv", "own_mood.npz", "catalogue.csv", "evidence_summary.json"]
HAND_MADE = ["pool_*.csv", "pool_audit_log.csv", "ai_keep.txt", "ai_block.txt", "deezer_skip.txt", "deezer_genres.txt", "ai_check_sheet*.csv", "friends_inputs.csv",
             "friends_songs.csv", "spotify_artists*.json", "spotify_tracks.json", "deezer_artists*.json", "rap_artists*.json", "underrated_*.csv", "pending_artists.md", "youtube_listen_sheet*.csv", "demo_samples.csv"]
RESTORE = """How to restore this backup (inside Ubuntu, in ~/hidden-gems-tests with the test kit unzipped):
  1. unzip -o hidden-gems-<date>.zip          # puts back results/ and the lists
  2. sudo service postgresql start
     pg_restore --clean --if-exists --no-owner -d "$HG_DB" database.dump
     (or, if that fails: python import_results.py   -- rebuilds the database from results/)
Nothing in results/ depends on the database: the files alone are enough to rebuild everything.
"""


def dump_db(path):
    if not shutil.which("pg_dump"):
        print("  pg_dump not found: database not dumped (results/ alone can rebuild it with import_results.py)")
        return False
    r = subprocess.run(["pg_dump", "--dbname", DB, "-Fc", "-f", path], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  database dump failed: {r.stderr.strip()[:200]}\n  (results/ alone can rebuild it: import_results.py)")
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", help="also copy the backup here (e.g. a OneDrive folder under /mnt/c/...)")
    ap.add_argument("--keep", type=int, default=2)
    ap.add_argument("--keep-to", type=int, default=int(os.environ.get("HG_BACKUP_KEEP", 2)),
                    help="how many backups to keep in the --to folder (0 = keep all)")
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    zpath = os.path.join(OUT, f"hidden-gems-{stamp}.zip")
    dump = os.path.join(OUT, f"database-{stamp}.dump")
    t0 = time.time()
    print(f"backing up to {zpath} ...")
    has_db = dump_db(dump)
    members = []
    for root, _, files in os.walk(os.path.join(HERE, "results")):
        for fn in files:
            if not fn.endswith((".tmp", ".tmp.npz")):
                members.append(os.path.join(root, fn))
    members += [os.path.join(HERE, f) for f in FILES if os.path.exists(os.path.join(HERE, f))]
    members += glob.glob(os.path.join(HERE, "blind_sheets", "*.csv*"))         # friends' filled-in sheets (and the .orig copies)
    for pat in HAND_MADE:                                                       # lists and files made by hand: not in git, not rebuildable
        members += glob.glob(os.path.join(HERE, pat))
    members += glob.glob(os.path.join(HERE, "fma", "*.csv"))                   # FMA song list + credit links
    members = list(dict.fromkeys(members))                                      # a file matched twice (FILES and a pattern) is stored once
    n_songs = len(glob.glob(os.path.join(HERE, "results", "*.npz")))
    manifest = dict(created=time.strftime("%Y-%m-%d %H:%M"), songs_with_numbers=n_songs, files=len(members),
                    database_dump=has_db)
    with zipfile.ZipFile(zpath + ".part", "w", allowZip64=True) as z:
        for p in members:
            comp = zipfile.ZIP_STORED if p.endswith(".npz") else zipfile.ZIP_DEFLATED   # .npz is already compressed
            z.write(p, os.path.relpath(p, HERE), compress_type=comp)
        if has_db:
            z.write(dump, "database.dump", compress_type=zipfile.ZIP_STORED)
        z.writestr("RESTORE.txt", RESTORE)
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    with zipfile.ZipFile(zpath + ".part") as z:                       # read every file back before trusting it
        bad = z.testzip()
        n_in = len(z.namelist())
    if bad:
        raise SystemExit(f"!! backup is damaged at {bad}; the old backups were left untouched")
    os.replace(zpath + ".part", zpath)
    if has_db:
        os.remove(dump)
    size = os.path.getsize(zpath)
    print(f"  ok: {n_in} files, {n_songs} songs' numbers, database {'included' if has_db else 'NOT included'}, "
          f"{size/1e9:.2f} GB, checked, {time.time()-t0:.0f}s")
    if a.to:
        os.makedirs(a.to, exist_ok=True)
        dest = os.path.join(a.to, os.path.basename(zpath))
        shutil.copyfile(zpath, dest + ".part"); os.replace(dest + ".part", dest)
        if os.path.getsize(dest) != size:
            raise SystemExit(f"!! copy to {a.to} is incomplete; the backup in backups/ is fine")
        print(f"  copied to {dest}")
        # only after the new copy is checked: drop older copies there and leftovers of failed copies
        stale = sorted(glob.glob(os.path.join(a.to, "hidden-gems-*.zip")))[:-a.keep_to] if a.keep_to > 0 else []
        stale += [p for p in glob.glob(os.path.join(a.to, "hidden-gems-*.zip.part")) if p != dest + ".part"]
        for p in stale:
            try:
                os.remove(p)
            except OSError as e:
                print(f"  could not remove {os.path.basename(p)}: {e}")
        if stale:
            print(f"  removed {len(stale)} older file(s) from {a.to} (keeping the newest {a.keep_to})")
    old = sorted(glob.glob(os.path.join(OUT, "hidden-gems-*.zip")))[:-a.keep]
    for p in old:
        os.remove(p)
    if old:
        print(f"  removed {len(old)} older backup zip(s) from backups/ (keeping the newest {a.keep})")


if __name__ == "__main__":
    main()
