"""Channels that post AI music: build ai_block.txt from your listening answers, and see what the AI rules remove from the pool.

  python ai_channels.py --from-sheet ai_check_sheet.csv            # preview: the channels where you answered y, and every pool song they would take out
  python ai_channels.py --from-sheet ai_check_sheet.csv --write    # add those channels to ai_block.txt
  python ai_channels.py --suggest                                  # other channels whose songs are mostly tagged AI (not applied: a list to read)

How the pool filter now works (blind_test.apply_quality):
  1. ai_keep.txt   artists or channels that always stay (kanegi, clouds.rap ...). This wins over everything below.
  2. ai_block.txt  every song of a listed channel leaves the pool, tagged or not (this catches the AI songs the tagger misses).
  3. the tags      every song tagged confirmed or likely AI leaves (HG_AI_POLICY=hide, the default since 11 Oct; hide-low kept those with 10,000+ views).
Nothing is deleted: the stored numbers stay, and a song comes back by taking the channel out of ai_block.txt or adding the artist to ai_keep.txt.
A channel is blocked as a whole: if you answered y for one song of a channel, all its songs go (unless the artist is in ai_keep.txt). The preview warns when
you also answered n for a song of the same channel, so you can decide.
"""
import argparse, collections, csv, os, sys

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
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(f"{n}\n" for n in add))
    return len(add)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-sheet", metavar="FILLED_SHEET")
    ap.add_argument("--write", action="store_true", help="add the flagged channels to ai_block.txt")
    ap.add_argument("--suggest", action="store_true", help="list other channels whose songs are mostly tagged AI")
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
    if not a.from_sheet and not a.suggest:
        ap.print_help()


if __name__ == "__main__":
    main()
