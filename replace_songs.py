"""Replace pool songs by another YouTube video you chose (e.g. the artist's official upload instead of a re-upload).

  python replace_songs.py ai_check_sheet.csv                         # preview: reads the 'how you decided' comments of a listening sheet
  python replace_songs.py ai_check_sheet.csv --apply                 # make the changes
  python replace_songs.py --pair OLD_URL NEW_URL [--pair ...] [--apply]
  python replace_songs.py --proposals results/official_proposals.csv [--apply]     # rows with approve = y (from find_official_versions.py)

A comment such as  "replace with https://www.youtube.com/watch?v=XXXX"  on a sheet row means: drop that row's song (its link is in `listen_here`) and use the
video in the comment instead. For each pair, --apply
  1. fetches the new video's title, channel, length and views (YouTube Data API: needs YOUTUBE_API_KEY, so start with `source env_keys.sh` or `bash -ic`),
  2. adds it to the SAME pool list as the old song, with the old song's genre group (so it stays in its style),
  3. marks the old song i_agree = n (its stored numbers stay), and logs both in pool_audit_log.csv.
The new video is analysed afterwards:  python -u run_tests.py --list pool_youtube.csv   (about 15 s a song; never run two analyses at once).
Nothing is changed without --apply. A song whose new video is already in the pool is not added twice. Sent friend sheets keep their original links:
this only changes which songs future lists can use. Run pool_duplicates.py afterwards, since the official upload may already have a twin in the pool.
"""
import argparse, csv, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import POOL_LISTS, list_key, write_list

LOG = os.path.join(HERE, "pool_audit_log.csv")
_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")
_COMMENT = re.compile(r"\breplace\b", re.I)
COMMENT_COL = "how you decided (optional)"


def video_id(text):
    """The 11-character YouTube id in a link (watch?v=, youtu.be/, shorts/, embed/), or None."""
    m = _ID.search(text or "")
    return m.group(1) if m else None


def pairs_from_sheet(path):
    """[(item, old_id, new_id, title)] from the rows whose comment says 'replace' and contains a YouTube link; also returns the problems found."""
    out, problems = [], []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get(COMMENT_COL) or "").strip()
            if not c or not _COMMENT.search(c):
                continue
            new, old = video_id(c), video_id(r.get("listen_here"))
            if not new:
                problems.append(f"{r.get('item')}: the comment has no YouTube link ({c[:40]!r})")
            elif not old:
                problems.append(f"{r.get('item')}: the row has no YouTube link to replace")
            elif new == old:
                problems.append(f"{r.get('item')}: the new link is the same video")
            else:
                out.append((r.get("item") or "", old, new, r.get("title") or ""))
    return out, problems


def pairs_from_proposals(path):
    """[(old key, old_id, new_id, old title)] from a review file made by find_official_versions.py: only rows whose `approve` starts with y."""
    out, problems = [], []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("approve") or "").strip().lower()[:1] != "y":
                continue
            old = (r.get("old_key") or "").split("_", 1)[-1] or video_id(r.get("old_link"))
            new = video_id(r.get("new_link"))
            if not old or not new or old == new:
                problems.append(f"{r.get('old_key')}: needs a different new_link")
            else:
                out.append((r.get("old_key") or "", old, new, r.get("old_title") or ""))
    return out, problems


def load_lists(here=HERE):
    """{file name: (rows, columns)} for every pool list that exists."""
    lists = {}
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if os.path.exists(p):
            rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
            if rows:
                lists[fn] = (rows, list(rows[0].keys()))
    return lists


def fetch_details(ids):
    """{video id: dict(title, channel, duration, views, licence)} from the YouTube Data API, or {} if there is no key."""
    if not os.environ.get("YOUTUBE_API_KEY"):
        return {}
    import build_youtube as by
    return by.video_details(list(ids))


def plan(pairs, lists, details):
    """One dict per pair: where the old song is, whether the new one is already in the pool, and the new row to add."""
    have = {list_key(r) for rows, _ in lists.values() for r in rows}
    out = []
    for item, old, new, title in pairs:
        where = next((fn for fn, (rows, _) in lists.items() if any(list_key(r) == f"youtube_{old}" for r in rows)), None)
        d = details.get(new)
        row = None
        if where and d:
            old_row = next(r for r in lists[where][0] if list_key(r) == f"youtube_{old}")
            import build_youtube as by
            row = dict.fromkeys(lists[where][1], "")
            row.update(source="youtube", track_id=new, title=d["title"], artist=by._clean_artist(d["channel"]), duration=d["duration"],
                       listens=d["views"], licence=d["licence"], listen=f"https://www.youtube.com/watch?v={new}",
                       site_genre=old_row.get("site_genre", ""), group=old_row.get("group", ""))
        out.append(dict(item=item, old=old, new=new, title=title, list=where, details=d, row=row, new_already=f"youtube_{new}" in have))
    return out


def apply_plan(actions, lists, here=HERE, log=LOG):
    """Write the changes. Returns (replaced, added). Old songs are marked i_agree = n; the new row goes into the old song's list."""
    added = replaced = 0
    logrows, changed = [], set()

    def live(key):
        """Is this song in a list and not marked out? (the replacement must be, or the old song would leave the pool for nothing)"""
        return any(list_key(r) == key and (r.get("i_agree") or "").strip().lower() not in ("n", "no") for rows, _ in lists.values() for r in rows)

    for a in actions:
        if not a["list"]:
            continue
        if not (a["row"] and not a["new_already"]) and not live(f"youtube_{a['new']}"):
            print(f"  !! left alone: {a['old']} -> {a['new']} (the new video's details could not be read, or it is already in the pool but marked out): the old song stays")
            continue
        rows, cols = lists[a["list"]]
        for r in rows:
            if list_key(r) == f"youtube_{a['old']}" and (r.get("i_agree") or "").strip().lower() not in ("n", "no"):
                r["i_agree"] = "n"; replaced += 1; changed.add(a["list"])
                logrows.append((f"youtube_{a['old']}", r.get("title"), r.get("artist"), f"replaced by official upload youtube_{a['new']}"))
        if a["row"] and not a["new_already"]:
            rows.append(a["row"]); added += 1; changed.add(a["list"])
            logrows.append((f"youtube_{a['new']}", a["row"]["title"], a["row"]["artist"], f"added to replace youtube_{a['old']}"))
            a["new_already"] = True
    for fn in sorted(changed):                                   # only the lists that changed are rewritten (each keeps a .bak copy)
        write_list(os.path.join(here, fn), lists[fn][0])
    if logrows:
        new = not os.path.exists(log)
        with open(log, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "key", "title", "artist", "reason"])
            for k, t, ar, why in logrows:
                w.writerow([time.strftime("%Y-%m-%d"), k, t, ar, why])
    return replaced, added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet", nargs="?", help="a listening sheet with 'replace with <link>' comments")
    ap.add_argument("--proposals", metavar="CSV", help="a review file from find_official_versions.py: the rows with approve = y are used")
    ap.add_argument("--pair", nargs=2, action="append", metavar=("OLD_URL", "NEW_URL"), default=[])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    pairs, problems = ([], [])
    if a.sheet:
        pairs, problems = pairs_from_sheet(a.sheet)
    if a.proposals:
        more, probs = pairs_from_proposals(a.proposals)
        pairs, problems = pairs + more, problems + probs
    for old, new in a.pair:
        o, n = video_id(old), video_id(new)
        if o and n and o != n:
            pairs.append(("", o, n, ""))
        else:
            problems.append(f"--pair {old} {new}: need two different YouTube links")
    for p in problems:
        print("  !!", p)
    if not pairs:
        raise SystemExit("nothing to replace")
    lists = load_lists()
    details = fetch_details({n for _, _, n, _ in pairs})
    if a.apply and not details:
        raise SystemExit("no YOUTUBE_API_KEY (or the API returned nothing): run `source env_keys.sh` first, then try again")
    actions = plan(pairs, lists, details)
    print(f"\n{len(actions)} replacement(s):")
    for x in actions:
        d = x["details"]
        new = (f"{d['title'][:48]} | {d['channel'][:24]} | {int(d['duration'])} s | {d['views']:,} views" if d else "(details are fetched with --apply)")
        flag = "  NOT IN ANY POOL LIST: skipped" if not x["list"] else ("  (new video already in the pool)" if x["new_already"] else "")
        print(f"  {x['item'] or '-':8s} {x['old']} -> {x['new']}{flag}\n           old: {x['title'][:60]}\n           new: {new}")
        if d and not (60 <= d["duration"] <= 600):
            print("           !! length outside 60-600 s: check that this is the song, not a mix or a short")
    if not a.apply:
        print("\n(dry run: nothing changed. Check each 'new' line is the official upload, then add --apply)")
        return
    replaced, added = apply_plan(actions, lists)
    print(f"\n{replaced} old song(s) marked i_agree = n, {added} new song(s) added. Logged in {os.path.basename(LOG)}; a .bak copy of each changed list was kept.")
    print("Now analyse the new videos (no other analysis may be running):  python -u run_tests.py --list pool_youtube.csv\n"
          "then check twins:  python pool_duplicates.py")


if __name__ == "__main__":
    main()
