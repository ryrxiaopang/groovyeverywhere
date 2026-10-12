"""Find the same song uploaded more than once in the recommendation pool (read-only by default).

  python pool_duplicates.py                  # report: results/pool_duplicate_pairs.csv and results/pool_duplicate_clusters.csv
  python pool_duplicates.py --check-sheets   # how many songs on each friend's sheets have a twin in the pool (no list is shown)
  python pool_duplicates.py --apply          # mark the less-viewed copy of every CONFIDENT duplicate i_agree = n (and log it)

Why: blind_test only removes copies of the friend's own song. Two uploads of one song under different channel names (the artist's channel and a
label or lyric channel) could both sit in the pool, and both appear in a friend's lists.

A pair is
  * a CONFIDENT duplicate when the plain Sound cosine is at least blind_test.DUP_COSINE (0.97: "the same recording") AND the song titles share most of
    their words (brackets and "feat." parts removed first), and
  * a "check by ear" pair when the sound is that close but the titles differ (a different song on the same record, or a retitled upload). These are
    listed but never marked.
Copies are grouped (A = B, B = C makes one group of three). Copy kept: an official-looking title ("Official Audio", "M/V") and/or an upload on the artist's own channel first, a plain title next, a lyric /
visualiser / subtitled re-upload last; the most-viewed copy breaks ties.

--apply changes the pool, and the Sound scale is refitted whenever the pool changes. Do not apply it between sending a round's sheets and scoring
that round; apply it before the next round's lists are built. Dry run first; the stored numbers are never deleted.
"""
import argparse, collections, csv, os, re, shutil, time
import numpy as np

import blind_test as bt
from results_index import RES, HERE, POOL_LISTS, list_key

LOG = os.path.join(HERE, "pool_audit_log.csv")
SAME_COSINE = bt.DUP_COSINE              # plain cosine of the whole-song Sound numbers: the same recording
MIN_TITLE = 0.6                          # share of the shorter title's words that the other title also has


# Which copy to keep: an official-looking title beats a plain one, which beats a lyric / visualiser / subtitled re-upload; views only break ties.
_OFFICIAL = re.compile(r"official|\bm/?v\b|music video|audio\)", re.I)
_LYRIC = re.compile(r"lyrics?|lyric video|visuali[sz]er|vietsub|engsub|sub\)|\bsped\b|\bslowed\b|8d|\u6b4c\u8a5e|\u6b4c\u8bcd|\u52d5\u614b|\uac00\uc0ac|\u65e5\u672c\u8a9e", re.I)


# a live / stage / performance / extended / acoustic / dance-practice video is a different recording or cut, never the copy to keep over the plain song
_ALTERED = re.compile(r"\b(performance|perf|live|stage|dance|choreography|extended|acoustic|unplugged|session|concert|fancam|remix|sped|slowed|8d|nightcore|reaction|behind)\b|\u73fe\u5834|\u73b0\u573a|\ub77c\uc774\ube0c", re.I)


def keep_rank(title, views):
    """Sort key for the copy to keep (bigger = better): official title +1, lyric / visualiser / subtitled upload -1, live / stage / performance / extended cut -2 (so it loses even to a plain song when its own title says Official), then views."""
    t = title or ""
    return ((1 if _OFFICIAL.search(t) else 0) - (1 if _LYRIC.search(t) else 0) - (2 if _ALTERED.search(t) else 0), views)


def _left_names(titles):
    """The 'Artist' part of every 'Artist - Song' title (brackets removed), as written."""
    out = []
    for t in titles:
        m = re.match(r"^\s*(.+?)\s+[-\u2013\u2014]\s+.+$", re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", t or ""))
        if m:
            out.append(m.group(1).strip())
    return out


def own_channel(channel, titles):
    """True when the uploader looks like the artist itself ('Malcolm Todd', 'Aioz - Topic', 'JVKEVEVO'): its name matches the 'Artist' part of a title in the group."""
    from find_official_versions import channel_matches
    names = _left_names(titles)
    return bool(names) and channel_matches(channel, *names)


def title_share(a, b):
    """Words in common / words of the shorter title (brackets, 'feat.' and 'with' parts left out); 0 if either is empty."""
    ta, tb = set(bt._toks(bt._bare_title(a))), set(bt._toks(bt._bare_title(b)))
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


def close_pairs(whole, cos_min=SAME_COSINE, block=500):
    """[(i, j, cosine)] for i < j with plain cosine >= cos_min, in blocks so the n x n matrix never exists at once."""
    X = np.asarray(whole, np.float32)
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    n = len(X)
    cols, out = np.arange(n), []
    for s in range(0, n, block):
        S = X[s:s + block] @ X.T
        rows = np.arange(s, min(s + block, n))
        S[cols[None, :] <= rows[:, None]] = -1.0          # keep only j > i
        for r, j in zip(*np.where(S >= cos_min)):
            out.append((int(rows[r]), int(j), float(S[r, j])))
    return out


def analyse(P):
    """(pairs, clusters). pairs = list of dicts with category 'duplicate' or 'check by ear'; clusters = list of dicts {keep, drop: [...], members}."""
    views = np.nan_to_num(np.asarray(P["listens"], float), nan=-1.0)
    pairs, parent = [], list(range(len(P["key"])))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    for i, j, c in close_pairs(P["whole"]):
        share = title_share(P["title"][i], P["title"][j])
        cat = "duplicate" if share >= MIN_TITLE else "check by ear"
        pairs.append(dict(a=i, b=j, cosine=round(c, 4), title_share=round(share, 2), category=cat,
                          same_artist=str(P["artist"][i]).lower() == str(P["artist"][j]).lower()))
        if cat == "duplicate":
            parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for p in pairs:
        if p["category"] == "duplicate":
            for x in (p["a"], p["b"]):
                if x not in groups[find(x)]:
                    groups[find(x)].append(x)
    clusters = []
    for members in groups.values():
        titles = [P["title"][i] for i in members]
        # an upload on the artist's own channel counts like an official title (+1), so a curator / lyric channel does not win on views alone
        def rank(i):
            (score, v) = keep_rank(P["title"][i], views[i])
            return (score + (1 if own_channel(P["artist_name"][i], titles) else 0), v), P["key"][i]
        keep = max(members, key=rank)
        clusters.append(dict(keep=keep, drop=[i for i in members if i != keep], members=sorted(members)))
    clusters.sort(key=lambda c: -len(c["members"]))
    return pairs, clusters


def write_reports(P, pairs, clusters, res=RES):
    os.makedirs(res, exist_ok=True)
    with open(os.path.join(res, "pool_duplicate_pairs.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["category", "cosine", "title_share", "same_artist_name", "key_a", "title_a", "artist_a", "views_a", "key_b", "title_b", "artist_b", "views_b"])
        for p in sorted(pairs, key=lambda p: (p["category"], -p["cosine"])):
            a, b = p["a"], p["b"]
            w.writerow([p["category"], p["cosine"], p["title_share"], p["same_artist"], P["key"][a], P["title"][a], P["artist_name"][a],
                        P["listens"][a], P["key"][b], P["title"][b], P["artist_name"][b], P["listens"][b]])
    with open(os.path.join(res, "pool_duplicate_clusters.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["copies", "role", "key", "title", "artist", "views"])
        for c in clusters:
            for i in [c["keep"]] + c["drop"]:
                w.writerow([len(c["members"]), "keep" if i == c["keep"] else "drop", P["key"][i], P["title"][i], P["artist_name"][i], P["listens"][i]])


def apply_marks(P, clusters, here=HERE, log=LOG):
    """Mark every dropped copy i_agree = n in the pool lists (a .bak copy is kept), and log it. Returns the number of songs marked."""
    drop = {P["key"][i]: P["key"][c["keep"]] for c in clusters for i in c["drop"]}
    info = {P["key"][i]: (P["title"][i], P["artist_name"][i]) for c in clusters for i in c["drop"]}
    marked = 0
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if not os.path.exists(p):
            continue
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        if not rows:
            continue
        cols, n_marked = list(rows[0].keys()), 0
        for r in rows:
            if list_key(r) in drop and (r.get("i_agree") or "").strip().lower() not in ("n", "no"):
                r["i_agree"] = "n"; n_marked += 1
        if n_marked:
            with open(p + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
            shutil.copy2(p, p + ".bak"); os.replace(p + ".tmp", p)
            print(f"  {fn}: {n_marked} marked i_agree = n")
            marked += n_marked
    new = not os.path.exists(log)
    with open(log, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "key", "title", "artist", "reason"])
        for k, keeper in drop.items():
            w.writerow([time.strftime("%Y-%m-%d"), k, info[k][0], info[k][1], f"duplicate upload of {keeper}"])
    return marked


def sheet_twins(P, clusters, key_csv=None):
    """{friend: [(title_a, title_b), ...]}: songs on the SAME friend's sheets that are copies of each other. Reads the answer key only for who
    got which song; the lists are never printed."""
    key_csv = key_csv or os.path.join(bt.RES, "blind", "key.csv")
    where = {}
    for ci, c in enumerate(clusters):
        for i in c["members"]:
            where[P["key"][i]] = ci
    title = dict(zip(P["key"], P["title"]))
    per = collections.defaultdict(lambda: collections.defaultdict(set))
    with open(key_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["key"] in where:
                per[r["friend"]][where[r["key"]]].add(r["key"])
    out = {fr: [(title[a], title[b]) for ks in g.values() if len(ks) > 1 for a in sorted(ks) for b in sorted(ks) if a < b] for fr, g in per.items()}
    return {fr: pr for fr, pr in out.items() if pr}                                    # friends with no twin pair are left out


def load_pool():
    P = bt._pool_from_files()
    P["from"] = "files"
    return bt.apply_quality(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="mark the less-viewed copy of each confident duplicate i_agree = n")
    ap.add_argument("--check-sheets", action="store_true", help="count songs on each friend's sheets that have a twin in the pool")
    a = ap.parse_args()
    P = load_pool()
    pairs, clusters = analyse(P)
    write_reports(P, pairs, clusters)
    n_dup = sum(p["category"] == "duplicate" for p in pairs)
    n_drop = sum(len(c["drop"]) for c in clusters)
    print(f"\n{len(P['key'])} pool songs. {n_dup} confident duplicate pairs in {len(clusters)} groups ({n_drop} songs would be dropped), "
          f"{len(pairs) - n_dup} 'check by ear' pairs (sound identical, titles differ).")
    print("reports: results/pool_duplicate_pairs.csv, results/pool_duplicate_clusters.csv")
    for c in clusters[:20]:
        print(f"  x{len(c['members'])}  keep {P['title'][c['keep']][:44]:44s} ({P['artist_name'][c['keep']][:20]})  "
              f"| drop {'; '.join(P['title'][i][:30] for i in c['drop'][:3])}")
    if a.check_sheets:
        twins = sheet_twins(P, clusters)
        print("\nsongs on one friend's sheets that are copies of each other (the lists are not shown):")
        for fr, pr in sorted(twins.items()):
            print(f"  {fr}: {len(pr)} pair(s)" + "".join(f"\n      {x[:40]} | {y[:40]}" for x, y in pr[:5]))
        if not twins:
            print("  none")
    if a.apply:
        print(f"\nmarked {apply_marks(P, clusters)} songs i_agree = n (stored numbers kept). The Sound scale refits on the next run.")
    else:
        print("(dry run: nothing changed)")


if __name__ == "__main__":
    main()
