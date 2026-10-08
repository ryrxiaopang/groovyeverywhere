"""Read Spotify artist pages (public embed pages: no login, no key) into a sources file for build_from_spotify.py.

  python spotify_artists.py spotify_artists4.json ID_OR_URL [ID_OR_URL ...] [--genre pop] [--more 8]

Each entry gets the artist's top tracks (up to 10), a pool genre (default pop; edit the JSON to change it) and `more`: how many extra
songs to take from the artist's own YouTube channel. Then:  python build_from_spotify.py --sources FILE --no-named
"""
import argparse, json, re, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def fetch(kind, sid):
    html = urllib.request.urlopen(urllib.request.Request(f"https://open.spotify.com/embed/{kind}/{sid}", headers=UA), timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("artists", nargs="+")
    ap.add_argument("--genre", default="pop")
    ap.add_argument("--more", type=int, default=8)
    a = ap.parse_args()
    out = []
    for x in a.artists:
        sid = re.search(r"artist/([A-Za-z0-9]+)", x).group(1) if "artist/" in x else x
        ent = fetch("artist", sid)
        tracks = [dict(title=t.get("title"), artists=t.get("subtitle"), seconds=(t.get("duration") or 0) / 1000) for t in (ent.get("trackList") or [])]
        out.append(dict(kind="artist", id=sid, name=ent.get("name") or ent.get("title"), genre=a.genre, more=a.more, tracks=tracks))
        print(f"{sid}  {out[-1]['name']!r}: {len(tracks)} tracks: " + "; ".join(t["title"] for t in tracks[:5]))
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
