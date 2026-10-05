"""Reads results/index.csv: one row per song, the latest one.

Exception: if a song was analysed once (its numbers file exists) and a LATER lookup said
'missing' / 'not downloadable' / 'failed' (Jamendo's lookups are sometimes flaky), the
finished analysis is kept. Every script uses this, so they all agree on which songs are done.
"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")


def latest_rows(res=RES):
    rows, last_done = {}, {}
    p = os.path.join(res, "index.csv")
    if not os.path.exists(p):
        return rows
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[r["key"]] = r
            if r["status"] == "done":
                last_done[r["key"]] = r
    for k, r in last_done.items():
        if rows[k]["status"] != "done" and os.path.exists(os.path.join(res, f"{k}.npz")):
            rows[k] = r
    return rows


POOL_LISTS = ("pool_list.csv", "pool_audius.csv", "pool_korean.csv", "pool_audius_more.csv", "pool_vocal.csv",
              "pool_fma.csv", "pool_youtube.csv")


def excluded_keys(here=HERE):
    """Songs marked i_agree = n in any pool list: they stay stored, but are left out of the pool."""
    out = set()
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if (r.get("i_agree") or "").strip().lower() in ("n", "no"):
                        out.add(f"{r.get('source') or 'jamendo'}_{r.get('track_id') or r.get('jamendo_id')}")
    return out


def list_key(r):
    return f"{r.get('source') or 'jamendo'}_{r.get('track_id') or r.get('jamendo_id')}"


# Genres left out of the recommendation pool: the pool keeps the mainstream genres (decided 6 Oct 2026). The songs stay
# analysed and stored (nothing is deleted); they are just not recommended. To bring a genre back, remove it here.
OFF_POOL_GENRES = {"punk", "latin", "funk", "classical", "soundtrack"}


def pool_keys(here=HERE):
    """Every song in a pool list, not marked i_agree = n, and not in an OFF_POOL_GENRES genre. Pool membership
    comes from the lists, not from the group a song was first analysed under (a song can be both a test song and a
    pool song)."""
    keys = set()
    for fn in POOL_LISTS:
        p = os.path.join(here, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                keys |= {list_key(r) for r in csv.DictReader(f) if genre_of(r.get("group")) not in OFF_POOL_GENRES}
    return keys - excluded_keys(here)


def write_list(path, rows, keep_cols=("i_agree",)):
    """Write a song list that people also edit by hand. Marks already in the old file (i_agree) are carried over
    by song, the old file is kept as <name>.bak, and the new one appears all at once (never half-written).
    Saved with a BOM so Excel shows Korean and accented titles correctly."""
    old = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            old = {list_key(r): r for r in csv.DictReader(f)}
    kept = 0
    for r in rows:
        o = old.get(list_key(r))
        for c in keep_cols:
            if o and (o.get(c) or "").strip() and not (r.get(c) or "").strip():
                r[c] = o[c]; kept += 1
    cols = list(rows[0].keys())
    with open(path + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    if os.path.exists(path):
        import shutil
        shutil.copy2(path, path + ".bak")            # copy, so the list itself never disappears even for a moment
    os.replace(path + ".tmp", path)
    if kept:
        print(f"  kept {kept} of your marks from the old {os.path.basename(path)} (old file saved as .bak)")


def read_meta(key, res=None):
    """A song's info file (results/meta/<key>.json) as a dict; {} if it is missing or damaged
    (python check_results.py finds damaged ones and queues those songs again)."""
    import json
    p = os.path.join(res or RES, "meta", f"{key}.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


# Pool groups -> one genre name, so pool_fma_rnb, pool_audius_randb_soul and pool_jamendo_korean_rnb all read "rnb".
GENRE_NAME = {"pop": "pop", "vocal_pop": "pop",
              "rnb": "rnb", "randb_soul": "rnb", "korean_rnb": "rnb",
              "hiphop": "hiphop", "rap": "hiphop", "hip-hop_rap": "hiphop", "korean_hiphop": "hiphop",
              "indie": "indie", "alternative": "alternative", "rock": "rock",
              "singersongwriter": "singer-songwriter", "singer-songwriter": "singer-songwriter",
              # YouTube genre keys (build_youtube.py): read as the mainstream genre they belong to
              "kpop": "pop", "jpop": "pop", "cpop": "pop", "cantopop": "pop", "khiphop": "hiphop", "krnb": "rnb",
              "singer": "singer-songwriter",
              "electronic": "electronic"}


def genre_of(group):
    g = (group or "").lower()
    for p in ("pool_vocal_", "pool_audius_", "pool_jamendo_", "pool_fma_", "yt_", "pool_"):
        if g.startswith(p):
            g = g[len(p):]; break
    return GENRE_NAME.get(g, g or "?")
