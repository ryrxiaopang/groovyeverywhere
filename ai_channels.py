"""Channels that post AI music: build ai_block.txt from your listening answers, and see what the AI rules remove from the pool.

  python ai_channels.py --from-sheet ai_check_sheet.csv            # preview: the channels where you answered y, and every pool song they would take out
  python ai_channels.py --from-sheet ai_check_sheet.csv --write    # add those channels to ai_block.txt
  python ai_channels.py --suggest                                  # other channels whose songs are mostly tagged AI (not applied: a list to read)
  python ai_channels.py --check ai_check_names.txt                 # channel names you were given: which are in the pool, with how many songs (preview)
  python ai_channels.py --check ai_check_names.txt --write         # add the ones found to ai_block.txt (names starting with ? are only looked up, never added)
  python ai_channels.py --patterns                                 # pool channels whose NAME looks like a mood / lofi / AI mill (a list to read)

How the pool filter now works (blind_test.apply_quality):
  1. ai_keep.txt   artists or channels that always stay (kanegi, clouds.rap ...). This wins over everything below.
  2. ai_block.txt  every song of a listed channel leaves the pool, tagged or not (this catches the AI songs the tagger misses).
  3. the tags      every song tagged confirmed or likely AI leaves (HG_AI_POLICY=hide, the default since 11 Oct; hide-low kept those with 10,000+ views).
Nothing is deleted: the stored numbers stay, and a song comes back by taking the channel out of ai_block.txt or adding the artist to ai_keep.txt.
A channel is blocked as a whole: if you answered y for one song of a channel, all its songs go (unless the artist is in ai_keep.txt). The preview warns when
you also answered n for a song of the same channel, so you can decide.
"""
import argparse, csv, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tag_ai
from tag_ai import norm_name

BLOCK = os.path.join(HERE, "ai_block.txt")
ANSWER_COL = "ai? (y / n / unsure)"


def flagged_channels(sheet):
    """{normalised channel: dict(name, y, n, unsure)} from a filled listening sheet."""
    out = {}
    with open(sheet, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            a = (r.get(ANSWER_COL) or "").strip().lower()[:1]
            ch = (r.get("channel") or "").strip()
            if a not in ("y", "n", "u") or not norm_name(ch):
                continue
            d = out.setdefault(norm_name(ch), dict(name=ch, y=0, n=0, unsure=0))
            d[{"y": "y", "n": "n", "u": "unsure"}[a]] += 1
    return out


def by_channel(rows, channels, tags):
    """{normalised channel: dict(name, keys, tagged, untagged)} for the YouTube pool songs."""
    out = {}
    for r in rows:
        if r["site"] != "youtube":
            continue
        name = channels.get(r["key"], "")
        c = norm_name(name)
        if not c:
            continue
        d = out.setdefault(c, dict(name=name, keys=[], tagged=0, untagged=0, untagged_keys=[]))
        d["keys"].append(r["key"])
        if tags.get(r["key"], ("none",))[0] != "none":
            d["tagged"] += 1
        else:
            d["untagged"] += 1; d["untagged_keys"].append(r["key"])
    return out


def preview(flags, pool, keep, titles):
    """Print what blocking the flagged channels would remove; returns the normalised channel names that would be blocked."""
    blocked, new_songs = [], 0
    print(f"{len(flags)} channels with an answer in the sheet; {sum(1 for f in flags.values() if f['y'])} with at least one y\n")
    print(f"{'channel':34s} {'answers':>14s} {'pool songs':>10s} {'already tagged AI':>18s} {'newly removed':>14s}")
    for c, f in sorted(flags.items(), key=lambda x: -x[1]["y"]):
        if not f["y"]:
            continue
        p = pool.get(c, dict(keys=[], tagged=0, untagged=0, untagged_keys=[]))
        kept = c in keep
        ans = f"{f['y']}y {f['n']}n {f['unsure']}?"
        note = "  KEPT (ai_keep.txt)" if kept else ("  !! you also answered n: check this channel" if f["n"] else "")
        print(f"{f['name'][:34]:34s} {ans:>14s} {len(p['keys']):10d} {p['tagged']:18d} {0 if kept else p['untagged']:14d}{note}")
        if not kept:
            blocked.append(c); new_songs += p["untagged"]
    print(f"\nblocking these {len(blocked)} channels would remove {new_songs} more songs than the AI tags alone remove. Some of them:")
    shown = 0
    for c in blocked:
        for k in pool.get(c, {}).get("untagged_keys", []):
            if shown < 25:
                print(f"   {titles.get(k, ('', False))[0][:60]:60s} | {flags[c]['name'][:24]}")
                shown += 1
    return blocked


def suggest(pool, keep, min_songs=3, min_share=0.5, limit=30):
    """Channels not blocked yet whose songs are mostly tagged AI: [(name, songs, tagged, untagged)], the biggest untagged count first."""
    block = tag_ai.load_name_list("ai_block.txt")
    rows = [(d["name"], len(d["keys"]), d["tagged"], d["untagged"]) for c, d in pool.items()
            if c not in block and c not in keep and len(d["keys"]) >= min_songs and d["tagged"] / len(d["keys"]) >= min_share and d["untagged"] > 0]
    return sorted(rows, key=lambda r: -r[3])[:limit]


def write_block(names, path=BLOCK):
    """Append channel names that are not in the file yet. Returns how many were added."""
    have = tag_ai.load_name_list(os.path.basename(path), os.path.dirname(path))
    add = [n for n in names if norm_name(n) not in have]
    if add:
        glue = ""
        if os.path.exists(path) and os.path.getsize(path):
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                glue = "" if f.read(1) == b"\n" else "\n"                  # a hand-edited file may end without a newline: the first new name would stick to the last line
        with open(path, "a", encoding="utf-8") as f:
            f.write(glue + "".join(f"{n}\n" for n in add))
    return len(add)


MILL = re.compile(r"\b(ai|a\.i|lo ?fi|lofi\w*|synth ?pop|bgm|mood|chill|study|sleep|aesthetic|vibes?|radio|fm|playlist|mix(es)?|"
                                r"beats?|instrumentals?|relax\w*|cafe|ambient|guofeng)\b", re.I)


def read_names(path):
    """[(name, block?)] from a text file: one channel per line, # comments, a leading ? = look it up but never block it."""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            t = line.split("#")[0].strip()
            if t:
                out.append((t[1:].strip(), False) if t.startswith("?") else (t, True))
    return out


def check(names, pool, keep, block, printer=print):
    """For each given name: the pool channel(s) it matches exactly (normalised) and near matches (one name inside the other).
    Returns the exact pool channel names to block (only names marked to block, not kept, not blocked already)."""
    to_block = []
    printer(f"{'given name':34s} {'in pool as':34s} {'songs':>5s}  status")
    for name, may_block in names:
        c = norm_name(name)
        exact = [p for p in pool if p == c]
        near = [p for p in pool if p != c and c and (c in p or (len(p) > 3 and p in c))]
        if not exact and not near:
            printer(f"{name[:34]:34s} {'-':34s} {0:5d}  not in the pool")
            continue
        for p in exact + near:
            d = pool[p]
            status = ("KEPT (ai_keep.txt)" if p in keep else "already in ai_block.txt" if p in block else
                      ("will be blocked with --write" if may_block else "look only (? in the file)") if p in exact else "NEAR MATCH: check by hand")
            printer(f"{name[:34]:34s} {d['name'][:34]:34s} {len(d['keys']):5d}  {status}")
            if p in exact and may_block and p not in keep and p not in block:
                to_block.append(d["name"])
    return to_block


def mill_channels(pool, keep, block):
    """Pool channels whose name looks like a mood / lofi / AI mill: [(name, songs)], most songs first (to read, never applied)."""
    return sorted(((d["name"], len(d["keys"])) for c, d in pool.items() if c not in keep and c not in block and MILL.search(d["name"])), key=lambda x: -x[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-sheet", metavar="FILLED_SHEET")
    ap.add_argument("--write", action="store_true", help="add the flagged channels to ai_block.txt")
    ap.add_argument("--suggest", action="store_true", help="list other channels whose songs are mostly tagged AI")
    ap.add_argument("--check", metavar="NAMES.txt", help="look up the channel names in this file (one per line; ? in front = look only)")
    ap.add_argument("--patterns", action="store_true", help="list pool channels whose name looks like a mood / lofi / AI mill")
    a = ap.parse_args()
    from pool_summary import read_pool
    rows = read_pool()
    channels, tags, keep = tag_ai.load_channels(), tag_ai.load_tags(), tag_ai.load_name_list("ai_keep.txt")
    pool = by_channel(rows, channels, tags)
    titles = {r["key"]: (r.get("title") or "", norm_name(channels.get(r["key"], "")) in keep) for r in rows}
    print(f"{len(rows)} pool songs; AI-tagged: {sum(1 for r in rows if tags.get(r['key'], ('none',))[0] != 'none')} "
          f"(the new default removes all of them); ai_keep.txt keeps: {', '.join(sorted(keep)) or 'nobody'}\n")
    if a.from_sheet:
        blocked = preview(flagged_channels(a.from_sheet), pool, keep, titles)
        if a.write:
            names = [pool[c]["name"] if c in pool else c for c in blocked]
            print(f"\nadded {write_block(names)} channel(s) to ai_block.txt")
        else:
            print("\n(preview: nothing written. Add --write to put these channels in ai_block.txt)")
    if a.suggest:
        print("\nchannels where at least half the songs are tagged AI but some are not (read them; add any you agree with to ai_block.txt):")
        for name, n, t, u in suggest(pool, keep):
            print(f"   {name[:36]:36s} {n:4d} songs, {t:4d} tagged AI, {u:4d} untagged")
    block = tag_ai.load_name_list("ai_block.txt")
    if a.check:
        found = check(read_names(a.check), pool, keep, block)
        if a.write and not a.from_sheet:
            print(f"\nadded {write_block(found)} channel(s) to ai_block.txt. Now:  python mark_ai_out.py  (preview), then  python mark_ai_out.py --apply")
        else:
            print(f"\n{len(found)} channel(s) would be added to ai_block.txt (preview: add --write)")
    if a.patterns:
        print("\npool channels whose name looks like a mood / lofi / AI mill (read them; put the ones you agree with in a names file and use --check):")
        for name, n in mill_channels(pool, keep, block)[:60]:
            print(f"   {n:4d}  {name}")
    if not (a.from_sheet or a.suggest or a.check or a.patterns):
        ap.print_help()


if __name__ == "__main__":
    main()
