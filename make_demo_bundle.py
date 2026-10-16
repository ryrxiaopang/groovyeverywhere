"""Pack the smallest set of files the demo needs, to copy to the booth laptop (the full backup is about 10 GB; the demo needs a few hundred MB).

  python make_demo_bundle.py --out /mnt/c/Users/NAME/Downloads         # makes demo-bundle-<date>.zip there and prints what is in it
  python make_demo_bundle.py --out DIR --dry-run                       # only count, write nothing

Run it on the machine that has the analysed songs (the desktop), AFTER the pool is frozen. On the laptop (see DEMO.md, "The booth laptop"):
  unzip -o demo-bundle-<date>.zip   inside ~/groovyeverywhere, then  python demo_server.py --check

What goes in (everything is NUMBERS and text: no audio exists anywhere in this project):
  * results/<key>.npz for every pool song, cut down to the arrays the recommender reads (Sound whole + parts, Instruments whole + parts, Mood whole + parts + the VGGish
    mood, the four rhythm numbers). The full files hold much more; the demo never reads it. A cut-down file gives the same query: tested.
  * results/index.csv (only the pool songs' latest rows), results/meta/<key>.json (titles and artists), results/ai_tags.csv, results/pool_links.csv, results/link_alternatives.csv
  * the pool lists (pool_*.csv etc.: they say which songs are in the pool), ai_keep.txt, ai_block.txt, demo_samples.csv if it exists
Not in it: the code (git pull on the laptop), the models (python models.py on the laptop, about 60 MB), the Sound scale (refitted on the laptop at the first start, a few seconds).
"""
import argparse, csv, io, os, sys, time, zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import POOL_LISTS, latest_rows, pool_keys

KEEP_KEYS = ("effnet_whole", "effnet_parts", "instruments_whole", "instruments_parts", "emomusic_whole", "emomusic_parts", "cand_emomusic_vggish_whole",
             "rhythm_bpm", "rhythm_confidence", "rhythm_steadiness", "rhythm_busyness")
RES_FILES = ("ai_tags.csv", "pool_links.csv", "link_alternatives.csv")
TOP_FILES = ("ai_keep.txt", "ai_block.txt", "demo_samples.csv")
README = """DEMO BUNDLE (made {when}, {songs} pool songs)

On the booth laptop, in Ubuntu (WSL):
  1. cd ~/groovyeverywhere && git fetch origin && git checkout claude/brave-rubin-xs7hbb && git pull      (the code)
  2. unzip -o <this zip> -d ~/groovyeverywhere                                                              (the numbers: results/ and the pool lists)
  3. source .venv/bin/activate && pip install -r requirements.txt && pip install -U yt-dlp && python models.py && sudo apt install -y ffmpeg
  4. python demo_server.py --check          # fix every [FAIL]
  5. python demo_server.py --rehearse links.txt   # real timings ON THIS LAPTOP: new songs take longer than on the desktop
  6. python demo_server.py                  # then open http://localhost:8765 in Chrome
The pool must be the same as on the desktop: if the pool changes there, make a new bundle.
"""


def slim_npz(path):
    """The bytes of a .npz holding only the arrays the demo reads (those that exist in the full file)."""
    with np.load(path, allow_pickle=False) as d:
        keep = {k: d[k] for k in KEEP_KEYS if k in d.files}
    buf = io.BytesIO()
    np.savez_compressed(buf, **keep)
    return buf.getvalue()


def pool_members(here=HERE):
    """The keys of the songs the recommender uses: the pool lists, limited to the sites in HG_POOL_SOURCES (default youtube; the older FMA / Jamendo / Audius songs would only make the zip bigger)."""
    import blind_test as bt
    members = pool_keys(here)
    if "all" not in bt.POOL_SOURCES:
        members = {k for k in members if k.split("_", 1)[0] in bt.POOL_SOURCES}
    return members


def pool_rows(here=HERE):
    """{key: its latest index row} for every pool song that has finished numbers."""
    res = os.path.join(here, "results")
    members = pool_members(here)
    return {k: r for k, r in latest_rows(res).items() if k in members and r.get("status") == "done" and os.path.exists(os.path.join(res, f"{k}.npz"))}, res


def build(here=HERE, out_dir=".", dry_run=False, when=None):
    """Write demo-bundle-<date>.zip. Returns dict(zip, songs, mb, listed, missing) (zip is None for a dry run)."""
    rows, res = pool_rows(here)
    listed = len(pool_members(here))
    when = when or time.strftime("%Y%m%d-%H%M")
    out = os.path.join(out_dir, f"demo-bundle-{when}.zip")
    total = 0
    zf = None
    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
        zf = zipfile.ZipFile(out, "w", zipfile.ZIP_STORED)               # the .npz files are compressed already
    try:
        for k in sorted(rows):
            data = slim_npz(os.path.join(res, f"{k}.npz"))
            total += len(data)
            if zf:
                zf.writestr(f"results/{k}.npz", data)
            meta = os.path.join(res, "meta", f"{k}.json")
            if os.path.exists(meta):
                total += os.path.getsize(meta)
                if zf:
                    zf.write(meta, f"results/meta/{k}.json")
        if rows:                                                          # the index: only the pool songs' latest rows, same columns
            with open(os.path.join(res, "index.csv"), encoding="utf-8-sig") as f:
                cols = csv.DictReader(f).fieldnames
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows.values())
            total += len(buf.getvalue())
            if zf:
                zf.writestr("results/index.csv", buf.getvalue().encode("utf-8-sig"))
        extra = [(os.path.join(res, n), f"results/{n}") for n in RES_FILES] + [(os.path.join(here, n), n) for n in TOP_FILES + tuple(POOL_LISTS)]
        for src, name in extra:
            if os.path.exists(src):
                total += os.path.getsize(src)
                if zf:
                    zf.write(src, name)
        if zf:
            zf.writestr("DEMO_BUNDLE_README.txt", README.format(when=when, songs=len(rows)))
    finally:
        if zf:
            zf.close()
    return dict(zip=None if dry_run else out, songs=len(rows), mb=round(total / 1e6, 1), listed=listed, missing=listed - len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="the folder for the zip (e.g. /mnt/c/Users/NAME/Downloads)")
    ap.add_argument("--dry-run", action="store_true", help="count and report, write nothing")
    a = ap.parse_args()
    r = build(HERE, a.out, a.dry_run)
    print(f"{r['songs']} pool songs with numbers ({r['listed']} in the pool lists, {r['missing']} without finished numbers: they are left out), about {r['mb']} MB")
    if r["missing"] > 0.02 * max(r["listed"], 1):
        print(f"!! {r['missing']} pool songs have no numbers yet: finish the analysis (python -u run_tests.py --list pool_youtube.csv) before making the bundle")
    if r["zip"]:
        print(f"written: {r['zip']} ({os.path.getsize(r['zip']) / 1e6:.0f} MB). Copy it to the laptop (USB stick or Drive) and follow DEMO_BUNDLE_README.txt inside it (or DEMO.md).")
    else:
        print("(dry run: nothing written)")


if __name__ == "__main__":
    main()
