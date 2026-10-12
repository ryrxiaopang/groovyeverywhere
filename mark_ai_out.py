"""Mark AI-generated songs and blocked channels out of the pool lists for good (i_agree = n), so every tool sees the same pool without a filter running each time.

  python mark_ai_out.py                    # preview: how many songs, why, which channels
  python mark_ai_out.py --apply            # mark them (a .bak copy of each changed list is kept; every song is logged in pool_audit_log.csv with its reason)
  python mark_ai_out.py --restore          # preview: marked songs that no longer match the AI rules (a channel was unblocked, an artist added to ai_keep.txt, a tag changed)
  python mark_ai_out.py --restore --apply  # put those songs back

The rules are the ones the pool filter already used (tag_ai.ai_reason): ai_keep.txt wins; then a channel in ai_block.txt (every song of it); then any song tagged
'confirmed' or 'likely' by tag_ai.py (policy HG_AI_POLICY, default hide). Nothing is deleted: the numbers stay stored, and --restore undoes a mark made here
(only marks logged as "AI: ..." are ever restored, never the duplicate or wrong-genre marks). Run it again after tag_ai.py has tagged new songs (quality_pass.sh does).
The marks change the pool, so the Sound scale refits on the next run.
"""
import argparse, collections, csv, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tag_ai
from tag_ai import norm_name
from results_index import list_key

LOG = os.path.join(HERE, "pool_audit_log.csv")


def is_marked(r):
    return (r.get("i_agree") or "").strip().lower() in ("n", "no")


def decide(r, tags, channels, keep, block, policy):
    """The reason this song should be marked out, or None. Only YouTube songs are looked at (the other sites are never recommended anyway)."""
    k = list_key(r)
    if not k.startswith("youtube_"):
        return None
    st, _, views = tags.get(k, ("none", "", 0.0))
    return tag_ai.ai_reason(st, views, norm_name(channels.get(k, "")), norm_name(r.get("artist") or ""), policy, keep, block)


def plan_mark(lists, tags, channels, keep, block, policy):
    """[(list file, row, reason text)] for every song in the lists that is not marked yet and should be."""
    out = []
    for fn, (rows, _) in lists.items():
        for r in rows:
            if is_marked(r):
                continue
            why = decide(r, tags, channels, keep, block, policy)
            if why:
                chan = channels.get(list_key(r), "")
                out.append((fn, r, f"AI: blocked channel ({chan})" if why == "blocked channel" else f"AI: {why}"))
    return out


def read_log(log=LOG):
    """{song key: its latest reason in the audit log}."""
    out = {}
    if os.path.exists(log):
        with open(log, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                out[r.get("key") or ""] = r.get("reason") or ""
    return out


def plan_restore(lists, tags, channels, keep, block, policy, log=LOG):
    """[(list file, row)] for songs marked out by THIS tool (latest log reason starts with 'AI:') that the rules no longer remove."""
    reasons = read_log(log)
    out = []
    for fn, (rows, _) in lists.items():
        for r in rows:
            k = list_key(r)
            if is_marked(r) and reasons.get(k, "").startswith("AI:") and decide(r, tags, channels, keep, block, policy) is None:
                out.append((fn, r))
    return out


def write_changes(lists, changed_files, here=HERE):
    """Rewrite only the lists that changed, exactly as they are in memory (results_index.write_list would carry the OLD marks over, so a cleared mark could never stick);
    each file keeps a .bak copy and appears all at once."""
    import shutil
    for fn in sorted(changed_files):
        path = os.path.join(here, fn)
        rows, cols = lists[fn]
        with open(path + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
        shutil.copy2(path, path + ".bak")
        os.replace(path + ".tmp", path)


def append_log(rows, log=LOG):
    new = not os.path.exists(log)
    with open(log, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "key", "title", "artist", "reason"])
        for r, why in rows:
            w.writerow([time.strftime("%Y-%m-%d"), list_key(r), r.get("title"), r.get("artist"), why])


def apply_mark(lists, plan, here=HERE, log=LOG):
    for fn, r, _ in plan:
        r["i_agree"] = "n"
    write_changes(lists, {fn for fn, _, _ in plan}, here)
    append_log([(r, why) for _, r, why in plan], log)
    return len(plan)


def apply_restore(lists, plan, here=HERE, log=LOG):
    for fn, r in plan:
        r["i_agree"] = ""
    write_changes(lists, {fn for fn, _ in plan}, here)
    append_log([(r, "AI mark removed: no longer matches the AI rules") for _, r in plan], log)
    return len(plan)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true", help="put back songs that no longer match the AI rules")
    a = ap.parse_args()
    from replace_songs import load_lists
    lists = load_lists()
    tags, channels = tag_ai.load_tags(), tag_ai.load_channels()
    keep, block = tag_ai.load_name_list("ai_keep.txt"), tag_ai.load_name_list("ai_block.txt")
    policy = os.environ.get("HG_AI_POLICY", "hide")
    if not tags:
        raise SystemExit("results/ai_tags.csv is missing: run python tag_ai.py first (it needs YOUTUBE_API_KEY: source env_keys.sh)")
    if a.restore:
        plan = plan_restore(lists, tags, channels, keep, block, policy)
        print(f"{len(plan)} song(s) were marked out as AI but no longer match the rules (policy {policy}; ai_keep: {len(keep)} names, ai_block: {len(block)} channels)")
        for fn, r in plan[:15]:
            print(f"   {(r.get('title') or '')[:50]:50s} | {(r.get('artist') or '')[:24]}")
        if a.apply and plan:
            print(f"\nput back {apply_restore(lists, plan)} song(s). The Sound scale refits on the next run.")
        elif plan:
            print("\n(preview: nothing changed. Add --apply to put them back)")
        return
    plan = plan_mark(lists, tags, channels, keep, block, policy)
    by_reason = collections.Counter(why.split(" (")[0] for _, _, why in plan)
    print(f"{len(plan)} song(s) to mark out (policy {policy}; {len(keep)} names in ai_keep.txt keep their songs, {len(block)} channels in ai_block.txt): "
          + (", ".join(f"{k} {v}" for k, v in by_reason.most_common()) or "nothing to do"))
    chans = collections.Counter(channels.get(list_key(r), "?") for _, r, _ in plan)
    for name, n in chans.most_common(12):
        print(f"   {n:4d}  {name[:40]}")
    if a.apply and plan:
        print(f"\nmarked {apply_mark(lists, plan)} song(s) i_agree = n (stored numbers kept, logged in pool_audit_log.csv). The Sound scale refits on the next run.")
    elif plan:
        print("\n(preview: nothing changed. Add --apply to mark them)")


if __name__ == "__main__":
    main()
