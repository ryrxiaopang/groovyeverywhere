"""Look closely at one song's recommendations: is each one AI-tagged, untagged (never checked by tag_ai.py) or clean, which language is it, and how many
songs of the starting song's language are among its closest matches. Read-only: nothing is downloaded or changed.

  python check_recs.py "https://www.youtube.com/watch?v=2rvouaZO4Ns"     # a song the demo already analysed (pool song or results/demo_cache/) or a pool key
  python check_recs.py youtube_2rvouaZO4Ns --k 10

It also says how many pool songs have NO row in results/ai_tags.csv: those were never looked at by the AI tagger, so an AI song among them stays in the pool.
"""
import argparse, collections, json, os, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES, read_meta


def load_query(text):
    """(query, meta, key) for a pool key, a YouTube link or id whose numbers are stored (pool or demo cache)."""
    import blind_test as bt
    import demo_server as ds
    vid = ds.video_id(text) or (text[len("youtube_"):] if text.startswith("youtube_") else None)
    if not vid:
        raise SystemExit("give a YouTube link, a video id or a pool key such as youtube_XXXXXXXXXXX")
    for p, side in ((os.path.join(RES, f"youtube_{vid}.npz"), None), (os.path.join(ds.DEMO_CACHE, f"{vid}.npz"), os.path.join(ds.DEMO_CACHE, f"{vid}.json"))):
        if os.path.exists(p):
            with np.load(p, allow_pickle=False) as d:
                q = bt.query_from_analysis(dict(d))
            meta = read_meta(f"youtube_{vid}") or (json.load(open(side, encoding="utf-8")) if side and os.path.exists(side) else {})
            return q, meta, f"youtube_{vid}"
    raise SystemExit(f"no stored numbers for {vid}: run it through the demo once (or analyse it), then try again")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--features", default="mood+rhythm+instruments")
    a = ap.parse_args()
    import blind_test as bt, recommend_song, tag_ai
    from pool_summary import language_of, script_language
    q, meta, key = load_query(a.song)
    P = bt.pool()
    pos = {k: i for i, k in enumerate(P["key"])}
    tags, channels = tag_ai.load_tags(), tag_ai.load_channels()
    lang = lambda i: language_of(dict(group=P["group"][i], title=P["title"][i], artist=P["artist_name"][i]))
    start_lang = script_language(f"{meta.get('title') or ''} {meta.get('artist') or ''}") or "English / other Latin-script"
    print(f"\nstarting song: {meta.get('title') or key} | {meta.get('artist') or ''}   (language guess from its title: {start_lang})")

    untagged = [k for k in P["key"] if k.startswith("youtube_") and k not in tags]
    print(f"pool: {len(P['key'])} songs; {len(untagged)} of them were NEVER checked by the AI tagger (no row in results/ai_tags.csv)"
          + ("  <- run  bash quality_pass.sh  (needs YOUTUBE_API_KEY via env_keys.sh) to tag them and mark AI songs out" if untagged else ""))

    res = recommend_song.recommend_query(q, meta, a.k, a.features)
    for name, label in (("A", "closest in sound"), ("B", f"sound + {a.features}")):
        print(f"\n## {label}")
        for r in res[name]:
            k = r["key"]; i = pos.get(k)
            st = tags[k][0] if k in tags else "NOT TAGGED"
            print(f"  {r['match']:5.1f}  {st:10s} {lang(i) if i is not None else '?':28s} {r['title'][:46]:46s} | {channels.get(k) or r['artist']}")

    # how many songs of the starting song's language are among the closest in sound (the recommender itself does not look at language)
    sound = np.asarray(bt.raw_sound(q, P), float)
    order = [i for i in np.argsort(-sound) if P["key"][i] != key]
    for n in (10, 50, 200):
        c = collections.Counter(lang(i) for i in order[:n])
        print(f"\nlanguages among the {n} closest in sound: " + ", ".join(f"{l} {v}" for l, v in c.most_common()))
    tot = collections.Counter(lang(i) for i in range(len(P["key"])))
    print("languages in the whole pool:            " + ", ".join(f"{l} {v}" for l, v in tot.most_common()))


if __name__ == "__main__":
    main()
