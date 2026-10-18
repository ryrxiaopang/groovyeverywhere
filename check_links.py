"""Does every pool song have a link that actually opens? Fix the ones that don't.

  python check_links.py                  # checks every pool song once (resumable), prints a summary
  python check_links.py --recheck        # check again even songs checked before
  python check_links.py --youtube-api 90 # for broken links, also look up the exact YouTube video (uses up to 90 of
                                         # the ~100 daily YouTube searches; needs YOUTUBE_API_KEY)
  python check_links.py --fix-sheets     # write blind_sheets/<sheet>_links.csv with working links (the friends'
                                         # original sheets are never changed)
  python check_links.py --summary

How each song's own link is checked (one polite request per song, nothing downloaded):
  jamendo  - Jamendo's API still lists the track (then its current page link is used)
  audius   - Audius's API still has the track
  youtube  - YouTube's public oEmbed check says the video is still up
  fma      - the old Free Music Archive page (from the 2017 research dataset) opens AND mentions the song's title;
             the https and trailing-slash forms are tried too. Many FMA pages have moved or gone since 2017.
If the song's own link is broken, the best working alternative is used, in this order:
  1. its Apple Music or Spotify page, if check_platforms.py found the exact song
  2. its exact YouTube video, if check_youtube.py found it, or --youtube-api finds it now (checked via oEmbed)
  3. a YouTube search for "<artist> <title>" (always opens; the listener picks the right video)
Results: results/links.csv. Other scripts (blind_test.py, export_catalogue.py) use its best_link automatically.
YouTube's rules allow keeping API results for 30 days, so API-found video links are re-checked after 30 days.
"""
import argparse, csv, datetime as dt, glob, os, re, time
from urllib.parse import quote_plus, urlparse
import requests
from results_index import latest_rows, pool_keys, read_meta, RES, HERE, POOL_LISTS

OUT = os.path.join(RES, "links.csv")
FIELDS = ["song_key", "source", "title", "artist", "own_link", "own_ok", "why", "best_link", "best_type", "checked"]
UA = {"User-Agent": "groovyeverywhere-school-project/1.0 (link check, one request per song)"}
KEEP_DAYS = 30
_last = {}


def polite(host, gap=1.0):
    t = time.time() - _last.get(host, 0)
    if t < gap:
        time.sleep(gap - t)
    _last[host] = time.time()


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def yt_search(artist, title):
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{artist} {title}".strip())


def youtube_up(url):
    polite("youtube.com", 0.3)
    try:
        r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, headers=UA, timeout=20)
        return r.status_code == 200, f"oEmbed {r.status_code}"
    except requests.RequestException as e:
        return False, f"error {type(e).__name__}"


def page_ok(url, title):
    """Opens (status < 400), didn't bounce to the home page, and the page mentions the song title.
    Returns (ok, reason, final address after redirects)."""
    host = urlparse(url).netloc
    polite(host)
    try:
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
    except requests.RequestException as e:
        return False, f"error {type(e).__name__}", ""
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}", ""
    if urlparse(r.url).path.strip("/") == "":
        return False, "sends you to the home page", ""
    t = norm(title)
    if t and len(t) >= 3 and "html" in r.headers.get("Content-Type", "") and t not in norm(r.text[:400000]):
        return False, "page opens but doesn't show this song", ""
    return True, f"HTTP {r.status_code}", r.url              # the address it really ends up at


def fma_ok(url, title):
    if not url:
        return False, "no link in the dataset", ""
    tries = [url]
    u = url.replace("http://", "https://", 1)
    tries += [u, u.rstrip("/") + "/"]
    why = ""
    for v in dict.fromkeys(tries):
        ok, why, final = page_ok(v, title)
        if ok:
            return True, why, final or v
    return False, why, ""


def load_platforms():
    out = {}
    p = os.path.join(RES, "platform_links.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):                     # latest row per song wins
                out[r["song_key"]] = r
    y = {}
    p = os.path.join(RES, "youtube_links.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("youtube") == "found" and r.get("video_id"):
                    y[r["song_key"]] = "https://www.youtube.com/watch?v=" + r["video_id"]
    return out, y


def list_links():
    out = {}
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    k = f"{r.get('source') or 'jamendo'}_{r.get('track_id') or r.get('jamendo_id')}"
                    out[k] = r
    return out


def load():
    if not os.path.exists(OUT):
        return {}
    with open(OUT, encoding="utf-8") as f:
        rows = {r["song_key"]: r for r in csv.DictReader(f)}
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for k in [k for k, r in rows.items() if r["best_type"] == "youtube video (API)" and r["checked"] < cut]:
        del rows[k]                                          # YouTube's 30-day rule: look it up again
    return rows


def save(rows):
    with open(OUT + ".tmp", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rows.values())
    os.replace(OUT + ".tmp", OUT)


def summary(rows):
    if not rows:
        print("nothing checked yet"); return
    from collections import Counter
    print(f"\n{len(rows)} pool songs checked")
    for s in sorted({r["source"] for r in rows.values()}):
        g = [r for r in rows.values() if r["source"] == s]
        own = sum(r["own_ok"] == "y" for r in g)
        print(f"  {s:8s} {len(g):5d} songs: own link works {100 * own / len(g):3.0f}%")
    c = Counter(r["best_type"] for r in rows.values())
    print("  link given to listeners: " + ", ".join(f"{t} {n}" for t, n in c.most_common()))
    why = Counter(r["why"] for r in rows.values() if r["own_ok"] != "y")
    if why:
        print("  why own links failed: " + ", ".join(f"{w} {n}" for w, n in why.most_common(6)))


def fix_sheets():
    from results_index import best_link
    n = 0
    for p in sorted(glob.glob(os.path.join(HERE, "blind_sheets", "sheet_*.csv"))):
        if p.endswith("_links.csv"):
            continue
        with open(p, encoding="utf-8-sig") as f:
            rd = csv.DictReader(f); cols = rd.fieldnames; rows = list(rd)
        key_of = {}
        kp = os.path.join(RES, "blind", "key.csv")
        if os.path.exists(kp):
            with open(kp, encoding="utf-8") as f:
                key_of = {r["item"]: r["key"] for r in csv.DictReader(f)}
        changed = 0
        for r in rows:
            k = key_of.get(r.get("item"))
            new = best_link(k, r.get("listen_here")) if k else r.get("listen_here")
            if new and new != r.get("listen_here"):
                r["listen_here"] = new; changed += 1
        out = p[:-4] + "_links.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        print(f"  {os.path.basename(out)}: {changed} links replaced"); n += 1
    print(f"{n} sheet(s) written next to the originals (originals untouched)" if n else "no sheets found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--youtube-api", type=int, default=0, metavar="N")
    ap.add_argument("--fix-sheets", action="store_true")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    rows = load()
    if a.summary:
        return summary(rows)
    if a.fix_sheets:
        return fix_sheets()
    idx, lists = latest_rows(RES), list_links()
    keys = sorted(k for k in pool_keys() if idx.get(k, {}).get("status") == "done")
    todo = [k for k in keys if a.recheck or k not in rows]
    print(f"{len(keys)} pool songs, {len(todo)} to check")
    plat, yt_found = load_platforms()
    jam = {}
    jids = [int(k.split("_", 1)[1]) for k in todo if k.startswith("jamendo_")]
    if jids:
        import sources
        print(f"  asking Jamendo about {len(jids)} songs ...")
        jam = sources.jamendo_tracks(jids)
    api_left = a.youtube_api if os.environ.get("YOUTUBE_API_KEY") else 0
    for n, k in enumerate(todo, 1):
        src, sid = k.split("_", 1)
        m, L = read_meta(k, RES), lists.get(k, {})
        title = m.get("title") or idx[k].get("title") or L.get("title") or ""
        artist = m.get("artist") or idx[k].get("artist") or L.get("artist") or ""
        own = m.get("page") or idx[k].get("page") or L.get("listen") or ""
        ok, why, use = False, "", ""
        if src == "jamendo":
            info = jam.get(int(sid))
            ok = info is not None
            use = (info or {}).get("page") or own or f"https://www.jamendo.com/track/{sid}"
            why = "listed by Jamendo" if ok else "no longer on Jamendo"
        elif src == "audius":
            import sources
            polite("audius")
            try:
                r = requests.get(f"{sources.AUDIUS}/tracks/{sid}", headers=UA, timeout=20)
                ok = r.status_code == 200 and not (r.json().get("data") or {}).get("is_delete")
                why = f"Audius {r.status_code}"
            except (requests.RequestException, ValueError) as e:
                why = f"error {type(e).__name__}"
            use = own
        elif src == "youtube":
            use = own or f"https://www.youtube.com/watch?v={sid}"
            ok, why = youtube_up(use)
        elif src == "fma":
            ok, why, use = fma_ok(own, title)
        elif own:                                      # any other source with a web page
            ok, why, final = page_ok(own, title); use = final or own
        else:
            why = "no link"
        best, btype = (use, f"{src} page") if ok and use else ("", "")
        if not best:
            p = plat.get(k, {})
            if p.get("apple") == "found" and p.get("apple_url"):
                best, btype = p["apple_url"], "Apple Music"
            elif p.get("spotify") == "found" and p.get("spotify_url"):
                best, btype = p["spotify_url"], "Spotify"
        if not best and k in yt_found:
            up, _ = youtube_up(yt_found[k])
            if up:
                best, btype = yt_found[k], "youtube video"
        if not best and api_left > 0 and title and artist:
            import check_youtube
            try:
                res, _, vid = check_youtube.check(title, artist, float(m.get("duration") or 0) or None)
                api_left -= 1
                if res == "found":
                    best, btype = f"https://www.youtube.com/watch?v={vid}", "youtube video (API)"
            except check_youtube.QuotaUsed:
                api_left = 0; print("  YouTube's daily allowance is used up; the rest get a YouTube search link")
            except Exception as e:
                print(f"  {k}: YouTube lookup failed ({str(e)[:60]})")
        if not best:
            best, btype = yt_search(artist, title), "YouTube search"
        rows[k] = dict(song_key=k, source=src, title=title, artist=artist, own_link=own, own_ok="y" if ok else "n",
                       why=why, best_link=best, best_type=btype, checked=dt.date.today().isoformat())
        if n % 50 == 0:
            save(rows); print(f"  {n}/{len(todo)}")
    save(rows)
    summary(rows)
    print(f"\nsaved {OUT}. Fix links in sheets already handed out: python check_links.py --fix-sheets")


if __name__ == "__main__":
    main()
