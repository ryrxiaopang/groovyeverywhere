"""Put working links and AI notes into the friends' EXISTING sheets, keeping every item id and order (answers stay matched).

  python refresh_sheets.py                       # rewrite blind_sheets/sheet_*.csv in place (blank sheets only)
  python refresh_sheets.py --rerate FILLED.csv   # a mini sheet with just the rows that friend could not rate because a link was broken

For each item (via results/blind/key.csv -> song key): listen_here = the best verified link (an https page, or a YouTube version when the
original page is gone); also_on = the original page when different (and for FMA the direct mp3, which plays in any browser);
note = 'likely AI-generated' / 'AI-generated (confirmed)' / '' (only with HG_AI_NOTE=1; otherwise there is no note column). A song with no working link anywhere is marked 'LINK DEAD' so it
is not rated.
"""
import argparse, csv, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES
import tag_ai
from blind_test import friend_note, AI_NOTE_FOR_FRIENDS

# the AI note column only exists when HG_AI_NOTE=1 (round 2 leaves it out: it could steer the ratings); an old 'note' column is dropped
COLS = (["item", "your_song", "listen_here", "also_on", "title", "artist"] + (["note"] if AI_NOTE_FOR_FRIENDS else [])
        + ["would_add (y/n)", "heard_before (y/n)", "rating (1-5)"])


def load():
    key = {r["item"]: r["key"] for r in csv.DictReader(open(os.path.join(RES, "blind", "key.csv"), encoding="utf-8"))}
    links = {r["key"]: r for r in csv.DictReader(open(os.path.join(RES, "pool_links.csv"), encoding="utf-8-sig"))}
    alts = {}
    ap = os.path.join(RES, "link_alternatives.csv")
    if os.path.exists(ap):
        alts = {r["key"]: r["youtube_link"] for r in csv.DictReader(open(ap, encoding="utf-8-sig")) if r["youtube_link"]}
    return key, links, alts, tag_ai.load_tags()


def fix_row(r, key, links, alts, tags):
    k = key.get(r["item"])
    if not k:
        return r
    L = links.get(k)
    orig = (r.get("also_on") or "") if "youtube.com" in (r.get("listen_here") or "") and r.get("also_on") else r.get("listen_here", "")
    primary, also = r.get("listen_here", ""), ""
    if L is not None:
        if L["status"] == "ok":
            primary = L["link"]
            if L.get("audio_url"):
                also = L["audio_url"]
        elif k in alts:
            primary, also = alts[k], L.get("original", "")
        else:
            primary, also = "LINK DEAD: do not rate this one", ""
    elif k in alts:
        primary = alts[k]
    # a YouTube link found earlier for a non-YouTube song (add_listen_links.py) stays the primary link
    if "youtube.com" in (r.get("listen_here") or "") and L is not None and L["status"] == "ok" and L["source"] != "youtube":
        primary, also = r["listen_here"], L["link"]
    r["listen_here"], r["also_on"] = primary, also
    r["note"] = friend_note(tags.get(k, ("none",))[0])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerate")
    a = ap.parse_args()
    key, links, alts, tags = load()
    if a.rerate:
        rows = list(csv.DictReader(open(a.rerate, encoding="utf-8-sig")))
        bad = [r for r in rows if re.search(r"link|don.?t work|broken", r.get("would_add (y/n)", "") + r.get("rating (1-5)", ""), re.I)]
        out = []
        for r in bad:
            r = fix_row(dict(r), key, links, alts, tags)
            for c in ("would_add (y/n)", "heard_before (y/n)", "rating (1-5)"):
                r[c] = ""
            out.append(r)
        name = os.path.splitext(os.path.basename(a.rerate))[0] + "_rerate.csv"
        dest = os.path.join(HERE, "blind_sheets", name)
        with open(dest, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(out)
        print(f"{len(out)} songs to rate again -> {dest}")
        for r in out:
            print("  ", r["item"], "|", r["title"][:40], "|", r["listen_here"][:70])
        return
    for p in sorted(glob.glob(os.path.join(HERE, "blind_sheets", "sheet_*.csv"))):
        if p.endswith("_rerate.csv"):
            continue
        rows = [fix_row(r, key, links, alts, tags) for r in csv.DictReader(open(p, encoding="utf-8-sig"))]
        dead = sum(1 for r in rows if r["listen_here"].startswith("LINK DEAD"))
        ai = sum(1 for r in rows if tags.get(key.get(r["item"], ""), ("none",))[0] != "none")
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
        print(f"{os.path.basename(p)}: {len(rows)} songs, {ai} tagged AI (not shown to the friend unless HG_AI_NOTE=1), {dead} with no working link")


if __name__ == "__main__":
    main()
