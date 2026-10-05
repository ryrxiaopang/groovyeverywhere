"""Are our pool songs also on Apple Music / Spotify, so users can listen where they already do?

  python check_platforms.py                 # every analysed POOL song (Apple only, no account needed)
  python check_platforms.py --limit 100     # a quick sample first
  python check_platforms.py --all           # every analysed song, not only the pool

Apple: the public iTunes Search API (no key). It allows about 20 searches a minute, so ~1,500 songs take ~75 min.
Spotify (optional): make a free app at https://developer.spotify.com/dashboard, then
  export SPOTIFY_CLIENT_ID=...  SPOTIFY_CLIENT_SECRET=...
and the same run also searches Spotify. Only the search is used (no audio), to find a link to the song.

A song counts as found only if the ARTIST matches, the TITLE is nearly the same, and (when both sites give one)
the length is within 5 seconds, so a different song with the same name isn't counted.
Results: results/platform_links.csv (resumable: songs already checked are skipped) and a printed summary.
"""
import argparse, base64, csv, difflib, json, os, re, time
import requests
from results_index import latest_rows, RES

OUT = os.path.join(RES, "platform_links.csv")
FIELDS = ["song_key", "title", "artist", "duration", "listens", "apple", "apple_url", "spotify", "spotify_url"]


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\((feat|ft|with)[^)]*\)|\[(feat|ft)[^\]]*\]| (feat|ft)\. .*$", "", s)
    s = re.sub(r"\((original mix|radio edit|remaster(ed)?[^)]*|album version)\)", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def same_artist(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def judge(title, artist, dur, cand_title, cand_artist, cand_dur):
    if not same_artist(artist, cand_artist):
        return None
    t = difflib.SequenceMatcher(None, norm(title), norm(cand_title)).ratio()
    if t < 0.85:
        return "artist only"
    if dur and cand_dur and abs(dur - cand_dur) > 5:
        return "artist only"
    return "found"


def apple(title, artist, dur):
    r = requests.get("https://itunes.apple.com/search", timeout=20,
                     params={"term": f"{artist} {title}", "entity": "song", "limit": 10})
    if r.status_code in (403, 429):
        raise RuntimeError("rate limited")
    best = ("not found", "")
    for x in r.json().get("results", []):
        v = judge(title, artist, dur, x.get("trackName"), x.get("artistName"), (x.get("trackTimeMillis") or 0) / 1000)
        if v == "found":
            return "found", x.get("trackViewUrl", "")
        if v == "artist only":
            best = ("artist only", x.get("artistViewUrl", ""))
    return best


_tok = {}
_sp_off = {"until": 0.0}          # Spotify said "come back later": skip it until then


def spotify(title, artist, dur):
    cid, sec = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and sec) or time.time() < _sp_off["until"]:
        return "", ""                       # "" = not checked: the next run checks these songs on Spotify again
    if _tok.get("exp", 0) < time.time():
        r = requests.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"}, timeout=20,
                          headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode()})
        r.raise_for_status(); j = r.json(); _tok.update(t=j["access_token"], exp=time.time() + j["expires_in"] - 60)
    r = requests.get("https://api.spotify.com/v1/search", timeout=20, headers={"Authorization": f"Bearer {_tok['t']}"},
                     params={"q": f'track:"{title}" artist:"{artist}"', "type": "track", "limit": 5})
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After") or 5)
        if wait > 60:                       # Spotify can ask for hours: never sit silently waiting for that
            _sp_off["until"] = time.time() + wait
            print(f"  Spotify: limit reached, it asks us to wait {wait/3600:.1f} h. Carrying on with Apple only; "
                  f"run this again later to fill in Spotify for the songs after this point.")
            return "", ""
        print(f"  Spotify: busy, waiting {wait} s")
        time.sleep(wait); return spotify(title, artist, dur)
    best = ("not found", "")
    for x in r.json().get("tracks", {}).get("items", []):
        v = judge(title, artist, dur, x.get("name"), ", ".join(a["name"] for a in x.get("artists", [])), x.get("duration_ms", 0) / 1000)
        if v == "found":
            return "found", x["external_urls"]["spotify"]
        if v == "artist only":
            best = ("artist only", (x.get("artists") or [{}])[0].get("external_urls", {}).get("spotify", ""))
    return best


def song_info(k, r):
    from results_index import read_meta
    m = read_meta(k, RES)
    num = lambda v: float(v) if v not in (None, "", "None") else None
    return dict(title=m.get("title") or r.get("title") or "", artist=m.get("artist") or r.get("artist") or "",
                duration=num(m.get("duration") or r.get("duration_listed")), listens=num(m.get("listens") or r.get("listens")))


def summary():
    with open(OUT, encoding="utf-8") as f:
        rows = list({r["song_key"]: r for r in csv.DictReader(f)}.values())     # latest check per song
    if not rows:
        print("nothing checked yet"); return
    sp = any(r["spotify"] for r in rows)

    def pct(g, col):
        g = [r for r in g if r[col] not in ("", "error")]          # only songs actually checked on that site
        return f"{100 * sum(r[col] == 'found' for r in g) / len(g):3.0f}%" if g else "  -"
    print(f"\n{len(rows)} songs checked. 'found' = same artist, same title, same length")
    print(f"  on Apple Music: {pct(rows, 'apple')}   (artist there but not this song: "
          f"{100 * sum(r['apple'] == 'artist only' for r in rows) / len(rows):.0f}%)")
    if sp:
        print(f"  on Spotify:     {pct(rows, 'spotify')}")
        both = [r for r in rows if r["spotify"] not in ("", "error")]
        print(f"  on either:      {100 * sum('found' in (r['apple'], r['spotify']) for r in both) / max(len(both), 1):3.0f}%"
              f"   (of the {len(both)} songs checked on both sites)")
    srcs = sorted({r["song_key"].split("_")[0] for r in rows})
    if len(srcs) > 1:
        print("  by source:")
        for s_ in srcs:
            g = [r for r in rows if r["song_key"].startswith(s_ + "_")]
            print(f"    {s_:8s} {len(g):5d} songs   Apple {pct(g, 'apple')}" + (f"  Spotify {pct(g, 'spotify')}" if sp else ""))
    known = sorted([r for r in rows if r["listens"] not in ("", "None")], key=lambda r: float(r["listens"]))
    if len(known) >= 40:
        q = len(known) // 4
        print("  by popularity on its own site (least -> most listened):")
        for i, name in enumerate(("most obscure quarter", "2nd quarter", "3rd quarter", "most popular quarter")):
            g = known[i * q:(i + 1) * q] if i < 3 else known[3 * q:]
            print(f"    {name:22s} Apple {pct(g, 'apple')}" + (f"  Spotify {pct(g, 'spotify')}" if sp else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.summary:
        return summary()
    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            last = {r["song_key"]: r for r in csv.DictReader(f)}
        # songs checked before Spotify keys were set get checked again, now including Spotify
        sp_on = bool(os.environ.get("SPOTIFY_CLIENT_ID"))
        done = {k for k, r in last.items() if r["apple"] != "error" and not (sp_on and r["spotify"] in ("", "error"))}
    rows = latest_rows(RES)
    from results_index import pool_keys
    in_pool = pool_keys()                     # the same pool the app uses (lists, minus i_agree = n)
    todo = [(k, r) for k, r in rows.items() if r["status"] == "done" and k not in done
            and (a.all or k in in_pool)]
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(todo)} songs to check ({len(done)} already checked)"
          + ("" if os.environ.get("SPOTIFY_CLIENT_ID") else "; Spotify skipped (no SPOTIFY_CLIENT_ID set)"))
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new: w.writeheader()
        for n, (k, r) in enumerate(todo, 1):
            s = song_info(k, r)
            if not s["title"] or not s["artist"]:
                continue
            for attempt in range(3):
                try:
                    ap_, apu = apple(s["title"], s["artist"], s["duration"]); break
                except Exception as e:
                    print(f"  Apple: {e}, waiting 60 s"); time.sleep(60); ap_, apu = "error", ""
            try:
                spf, spu = spotify(s["title"], s["artist"], s["duration"])
            except Exception as e:
                spf, spu = "error", ""; print(f"  Spotify: {e}")
            w.writerow(dict(song_key=k, **s, apple=ap_, apple_url=apu, spotify=spf, spotify_url=spu)); f.flush()
            if n % 25 == 0:
                print(f"  {n}/{len(todo)}")
            time.sleep(3.2)                     # stay under Apple's ~20 searches a minute
    summary()


if __name__ == "__main__":
    main()
