"""For pool songs whose own page no longer works (results/pool_links.csv status != ok), find a YouTube version people can open
->  results/link_alternatives.csv  (key, youtube_link, matched_title).

  python find_youtube_alternatives.py

A YouTube result is accepted ONLY when the title matches, the artist is in the channel or title and the length is within a few seconds
(add_listen_links.good_match) so nobody is sent to a cover or a different song. A song with no working link and no safe YouTube match
is left out of recommendations (blind_test.apply_quality) and listed here as 'none'.
"""
import csv, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from add_listen_links import good_match, listed_duration
from results_index import RES, pool_keys, POOL_LISTS, list_key

LINKS = os.path.join(RES, "pool_links.csv")
OUT = os.path.join(RES, "link_alternatives.csv")


def main():
    bad = [r for r in csv.DictReader(open(LINKS, encoding="utf-8-sig")) if r["status"] != "ok"]
    done = {}
    if os.path.exists(OUT):
        done = {r["key"]: r for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))}
    info = {}
    members = pool_keys()
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                if list_key(r) in members:
                    info[list_key(r)] = r
    todo = [r for r in bad if r["key"] not in done]
    print(f"{len(bad)} songs have no working page; {len(todo)} still to search", flush=True)
    lock, n = threading.Lock(), [0]

    def work(r):
        k = r["key"]; meta = info.get(k, {})
        title, artist = meta.get("title") or "", meta.get("artist") or ""
        dur = float(meta.get("duration") or 0) or listed_duration(k)
        hit, matched = "", ""
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}) as ydl:
                for e in ydl.extract_info(f"ytsearch6:{artist} {title}", download=False).get("entries", []):
                    if e.get("id") != k.split("_", 1)[1] and good_match(e, title, artist, dur):
                        hit, matched = f"https://www.youtube.com/watch?v={e['id']}", e.get("title") or ""
                        break
        except Exception as ex:
            pass
        with lock:
            done[k] = dict(key=k, youtube_link=hit, matched_title=matched)
            n[0] += 1
            if n[0] % 100 == 0:
                print(f"  {n[0]} / {len(todo)}", flush=True)

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(work, todo))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["key", "youtube_link", "matched_title"]); w.writeheader(); w.writerows(done.values())
    found = sum(1 for r in done.values() if r["youtube_link"])
    print(f"YouTube alternative found for {found} of {len(done)} songs; {len(done) - found} have no working link anywhere (left out of recommendations)")


if __name__ == "__main__":
    main()
