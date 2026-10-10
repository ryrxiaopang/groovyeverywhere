"""Check that every song in the pool has a link a person can really open and listen to  ->  results/pool_links.csv

  python check_links.py              # check every pool song (about 10 minutes), write results/pool_links.csv
  python check_links.py --retry      # only re-check the songs that failed last time

Per source (checked the way that source can really be checked):
  * FMA      the page over HTTPS (the old http:// links failed for friends on their phones), the page must name the track, and the
             page's mp3 file must answer (HEAD). The direct mp3 address is kept as `audio_url`.
  * Jamendo  the Jamendo API (a missing track is gone), page link https://www.jamendo.com/track/<id>
  * Audius   the Audius API for the track id
  * YouTube  oEmbed (404 = gone; 401 = exists but embedding is off, which is fine for a link)
Columns: key, source, original, link (the best working link, https), audio_url, status (ok / gone / no_audio / error), detail.
Songs that fail get a YouTube alternative from find_youtube_alternatives.py.
"""
import argparse, csv, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import pool_keys, POOL_LISTS, list_key, RES

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
OUT = os.path.join(RES, "pool_links.csv")
FIELDS = ["key", "source", "original", "link", "audio_url", "status", "detail"]
lock = threading.Lock()


def http(url, method="GET", n=300000, timeout=25):
    req = urllib.request.Request(url, headers=UA, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), (r.read(n).decode("utf-8", "replace") if method == "GET" else "")


def https(u):
    return re.sub(r"^http://", "https://", u or "")


def check_fma(key, link):
    link = https(link)
    try:
        st, final, body = http(link)
    except urllib.error.HTTPError as e:
        return dict(link=link, status="gone", detail=f"page {e.code}")
    except Exception as e:
        return dict(link=link, status="error", detail=str(e)[:60])
    body = body.replace("\\/", "/")
    m = re.search(r'https://files\.freemusicarchive\.org/[^"\'\s<>]+?\.mp3', body)
    if "Free Music Archive" not in body or not m:
        return dict(link=final, status="no_audio", detail="page has no track audio")
    try:
        http(m.group(0), method="HEAD")
    except Exception as e:
        return dict(link=final, audio_url=m.group(0), status="no_audio", detail=f"mp3 {str(e)[:40]}")
    return dict(link=final, audio_url=m.group(0), status="ok", detail="")


def check_youtube(key, link):
    vid = key.split("_", 1)[1]
    url = f"https://www.youtube.com/watch?v={vid}"
    try:
        http("https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe=""), n=2000)
        return dict(link=url, status="ok", detail="")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return dict(link=url, status="ok", detail="embedding off, page exists")
        return dict(link=url, status="gone", detail=f"oembed {e.code}")
    except Exception as e:
        return dict(link=url, status="error", detail=str(e)[:60])


def check_audius(key, link):
    tid = key.split("_", 1)[1]
    try:
        st, _, body = http(f"https://api.audius.co/v1/tracks/{tid}?app_name=hiddengems", n=20000)
        if '"data"' in body and '"is_delete":true' not in body.replace(" ", ""):
            return dict(link=https(link), status="ok", detail="")
        return dict(link=https(link), status="gone", detail="deleted")
    except urllib.error.HTTPError as e:
        return dict(link=https(link), status="gone" if e.code == 404 else "error", detail=f"api {e.code}")
    except Exception as e:
        return dict(link=https(link), status="error", detail=str(e)[:60])


def pool_rows():
    members, info = pool_keys(), {}
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                if list_key(r) in members:
                    info[list_key(r)] = r
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    info = pool_rows()
    old = {}
    if os.path.exists(OUT):
        old = {r["key"]: r for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))}
    todo = [k for k in info if (not a.retry and k not in old) or (a.retry and old.get(k, {}).get("status") not in ("ok", None)) or k not in old]
    print(f"{len(info)} pool songs; {len(todo)} to check")
    res = dict(old)

    def one(k):
        src = k.split("_", 1)[0]
        link = info[k].get("listen") or info[k].get("page") or ""
        fn = {"fma": check_fma, "youtube": check_youtube, "audius": check_audius}.get(src)
        if fn is None:
            return k, None
        for attempt in range(2):
            r = fn(k, link)
            if r["status"] != "error":
                break
            time.sleep(2)
        return k, dict(key=k, source=src, original=link, audio_url=r.get("audio_url", ""), **{x: r.get(x, "") for x in ("link", "status", "detail")})

    done = [0]

    def work(k):
        k, row = one(k)
        with lock:
            if row:
                res[k] = row
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"  {done[0]} / {len(todo)}", flush=True)

    with ThreadPoolExecutor(a.threads) as ex:
        list(ex.map(work, [k for k in todo if not k.startswith("jamendo_")]))

    # Jamendo: one API question for many tracks at a time
    jam = [k for k in todo if k.startswith("jamendo_")]
    if jam:
        import sources
        ids = [int(k.split("_", 1)[1]) for k in jam]
        print(f"  asking the Jamendo API about {len(ids)} tracks ...", flush=True)
        found = {}
        for i in range(0, len(ids), 100):
            found.update(sources.jamendo_tracks(ids[i:i + 100]))
        for k, i in zip(jam, ids):
            link = f"https://www.jamendo.com/track/{i}"
            res[k] = dict(key=k, source="jamendo", original=info[k].get("listen") or "", link=link, audio_url="",
                          status="ok" if i in found else "gone", detail="" if i in found else "not on Jamendo any more")
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(res.values())
    from collections import Counter
    c = Counter((r["source"], r["status"]) for r in res.values())
    print("\nresult by source / status:")
    for (s, st), n in sorted(c.items()):
        print(f"   {s:8s} {st:9s} {n}")


if __name__ == "__main__":
    main()
