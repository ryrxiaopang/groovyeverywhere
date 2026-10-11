"""Read and mark the proposals of find_official_versions.py without editing a CSV by hand.

  python review_proposals.py                       # numbered list of every proposal, with warning flags
  python review_proposals.py --only blank          # only rows with approve empty (also: y, official-no, flagged)
  python review_proposals.py --approve "3 5 7-12"  # put y on those row numbers      (--clear "4" removes a y)
  python review_proposals.py --approve "3 5" --clear "4"

Row numbers are the numbers in the list (1 = first data row of results/official_proposals.csv), so list first, then approve.
Flags: len = the new video is much shorter / longer than the old one (outside 0.67x-1.5x); lyr = the new video itself looks like a lyric video / cover /
live recording; x2 = the same new video is proposed for 2+ old songs (fine: they all collapse onto one); chan = the new channel is not recognised as the
artist's own or a Topic channel (official_channel = no). Nothing in the pool changes here: that happens only in replace_songs.py --apply.
"""
import argparse, collections, csv, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES

PROPOSALS = os.path.join(RES, "official_proposals.csv")


def load(path=PROPOSALS):
    with open(path, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return list(r), list(r.fieldnames or [])


def save(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def parse_numbers(text, n):
    """'3 5 7-9' -> {3, 5, 7, 8, 9}; numbers outside 1..n are reported by raising ValueError."""
    out = set()
    for part in re.split(r"[\s,]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"not a row number: {part!r}")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b > n or a > b:
            raise ValueError(f"row numbers must be between 1 and {n}: {part!r}")
        out.update(range(a, b + 1))
    return out


def _secs(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def flags(row, link_counts):
    """Short warning flags for one proposal row."""
    import find_official_versions as fo
    out = []
    old, new = _secs(row.get("old_seconds")), _secs(row.get("new_seconds"))
    if old and new and not 0.67 <= new / old <= 1.5:
        out.append("len")
    if fo.kind_of(row.get("new_title"), row.get("new_channel")) or fo.ALTERED.search(row.get("new_title") or ""):
        out.append("lyr")
    if link_counts.get(row.get("new_link"), 0) > 1:
        out.append("x2")
    if (row.get("official_channel") or "").lower() != "yes":
        out.append("chan")
    return out


def apply_marks(rows, approve=(), clear=()):
    """Set approve = y on the 1-based row numbers in `approve`, empty it on `clear`. Returns (set, cleared)."""
    a = c = 0
    for i, r in enumerate(rows, 1):
        if i in approve and (r.get("approve") or "").strip().lower()[:1] != "y":
            r["approve"] = "y"; a += 1
        elif i in clear and (r.get("approve") or "").strip():
            r["approve"] = ""; c += 1
    return a, c


def show(rows, only=None):
    counts = collections.Counter(r.get("new_link") for r in rows)
    shown = 0
    for i, r in enumerate(rows, 1):
        fl = flags(r, counts)
        ap = (r.get("approve") or "").strip().lower()[:1] == "y"
        if only == "y" and not ap or only == "blank" and ap or only == "official-no" and "chan" not in fl or only == "flagged" and not [f for f in fl if f != "x2"]:
            continue
        shown += 1
        print(f"{i:3d} {'y' if ap else '-'} {(r.get('kind') or '')[:5]:5s} {','.join(fl):12s}| {(r.get('old_title') or '')[:36]:36s} | {(r.get('old_channel') or '')[:13]:13s} "
              f"-> {(r.get('new_title') or '')[:36]:36s} | {(r.get('new_channel') or '')[:16]:16s} {r.get('old_seconds') or '?'}s->{r.get('new_seconds') or '?'}s")
    print(f"\n{shown} of {len(rows)} rows shown; {sum((r.get('approve') or '').strip().lower()[:1] == 'y' for r in rows)} are marked y")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=PROPOSALS)
    ap.add_argument("--only", choices=["y", "blank", "official-no", "flagged"])
    ap.add_argument("--approve", default="", help="row numbers to mark y, e.g. \"3 5 7-12\"")
    ap.add_argument("--clear", default="", help="row numbers whose y is removed")
    a = ap.parse_args()
    rows, cols = load(a.file)
    if a.approve or a.clear:
        try:
            ap_set, cl_set = parse_numbers(a.approve, len(rows)), parse_numbers(a.clear, len(rows))
        except ValueError as e:
            raise SystemExit(str(e))
        n_a, n_c = apply_marks(rows, ap_set, cl_set)
        save(a.file, rows, cols)
        print(f"marked y on {n_a} row(s), cleared {n_c}. Saved {a.file}\n")
    show(rows, a.only)


if __name__ == "__main__":
    main()
