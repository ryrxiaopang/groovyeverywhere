"""Carry a day's work from the laptop back to the desktop, without losing anything on either side.

On the LAPTOP, at the end of the day:
  python carry.py --pack /mnt/c/Users/<you>/Downloads        # makes laptop-work-<date>.zip there
On the DESKTOP:
  python carry.py --unpack /mnt/c/Users/Ryanc/Downloads/laptop-work-<date>.zip

What it carries (everything the laptop can produce in a day): taps.csv, the blind test (results/blind/ captures and
answer key, blind_sheets/), results/capture_log.csv, results/youtube_links.csv, results/platform_links.csv.
Unpacking MERGES, it never replaces: taps filled on either machine are kept, captures and sheets are only added,
log rows are added once. Every desktop file it changes is first copied to <name>.before-carry.
Song analysis (results/*.npz) is NOT carried: the desktop does the analysing.
"""
import argparse, csv, glob, io, os, shutil, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
LOGS = ["results/capture_log.csv", "results/youtube_links.csv", "results/platform_links.csv"]


def members():
    m = [p for p in ["taps.csv"] + LOGS + ["results/blind/key.csv"] if os.path.exists(os.path.join(HERE, p))]
    m += [os.path.relpath(p, HERE) for p in glob.glob(os.path.join(RES, "blind", "*.json"))]
    m += [os.path.relpath(p, HERE) for p in glob.glob(os.path.join(HERE, "blind_sheets", "*.csv"))]
    return m


def pack(dest):
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, f"laptop-work-{time.strftime('%Y%m%d-%H%M')}.zip")
    m = members()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in m:
            z.write(os.path.join(HERE, p), p)
    print(f"packed {len(m)} files into {out}\nOn the desktop: python carry.py --unpack <that file>")


def read_csv(text):
    rd = csv.DictReader(io.StringIO(text, newline=""))        # (not splitlines(): a title may contain a line break)
    return rd.fieldnames or [], list(rd)


def carried(name):
    """True only for the files this tool packs, and only if they land inside this folder (a zip entry named
    ../../x must never write outside it)."""
    if name.endswith("/") or ".." in name.replace("\\", "/").split("/"):
        return False
    ok = (name == "taps.csv" or name in LOGS or name == "results/blind/key.csv"
          or (name.startswith("results/blind/") and name.endswith(".json"))
          or (name.startswith("blind_sheets/") and name.endswith(".csv")))
    root = os.path.realpath(HERE)
    return ok and os.path.realpath(os.path.join(HERE, name)).startswith(root + os.sep)


def write_csv(path, fields, rows):
    if os.path.exists(path):
        shutil.copy2(path, path + ".before-carry")
    with open(path + ".tmp", "w", newline="", encoding="utf-8-sig" if path.endswith("taps.csv") else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    os.replace(path + ".tmp", path)


def local_csv(path):
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8-sig") as f:
        return read_csv(f.read())


def unpack(zpath):
    added = {}
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if not carried(name):
                print(f"  skipped {name}: not a file this tool carries"); continue
            text = z.read(name).decode("utf-8-sig")
            dst = os.path.join(HERE, name)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if name == "taps.csv":                        # keep every tap, from either machine
                f_l, here = local_csv(dst)
                f_z, there = read_csv(text)
                if not here:
                    write_csv(dst, f_z, there); added[name] = len(there); continue
                by = {r["jamendo_id"]: r for r in here}
                n = 0
                for r in there:
                    o = by.get(r["jamendo_id"])
                    if o is None:
                        here.append(r); n += 1
                    elif (r.get("tapped_bpm") or "").strip() and not (o.get("tapped_bpm") or "").strip():
                        o["tapped_bpm"] = r["tapped_bpm"]; n += 1
                write_csv(dst, f_l or f_z, here); added[name] = n
            elif name.endswith(".csv") and (name in LOGS or name == "results/blind/key.csv"):
                f_l, here = local_csv(dst)              # add rows the desktop doesn't have yet
                f_z, there = read_csv(text)
                fields = f_l + [c for c in f_z if c not in f_l]
                seen = {tuple(r.get(c, "") for c in f_z) for r in here}
                new = [r for r in there if tuple(r.get(c, "") for c in f_z) not in seen]
                if new:
                    write_csv(dst, fields, here + new)
                added[name] = len(new)
            else:                                       # blind captures and sheets: only ever added
                if os.path.exists(dst):
                    with open(dst, encoding="utf-8-sig") as f:
                        if f.read() == text:
                            continue
                    base, ext = os.path.splitext(dst)
                    dst = base + "_laptop" + ext
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(text)
                added[name] = 1
    for k, v in added.items():
        print(f"  {k}: {v} added")
    print("done. Desktop files that changed were copied to <name>.before-carry first.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", metavar="FOLDER")
    ap.add_argument("--unpack", metavar="ZIP")
    a = ap.parse_args()
    if a.pack:
        pack(a.pack)
    elif a.unpack:
        unpack(a.unpack)
    else:
        ap.print_help()
