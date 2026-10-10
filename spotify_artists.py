"""Read Spotify artist pages (public embed pages: no login, no key) into a sources file for build_from_spotify.py.

  python spotify_artists.py spotify_artists6.json ID_OR_URL[@genre] [ID_OR_URL[@genre] ...] [--genre pop] [--more 25]

Each entry gets the artist's top tracks (up to 10), a pool genre (`@genre` after the id or link, e.g. .../artist/ID@indierock;
otherwise --genre, default pop; edit the JSON to change it) and `more`: how many extra songs to take from the artist's own YouTube
channel (default 25, was 8 before 10 Oct: the same artist's other songs in the same genre give the matching more to choose from;
a recommendation list still takes at most one song per artist). Genres: any key of results_index.GENRE_NAME, e.g. indie, indiepop,
indierock, altrock, alternative, pop, rnb, singer, indiefolk, electro, electronic, hiphop, rock. Then:  python build_from_spotify.py --sources FILE --no-named
"""
import argparse, json, re, urllib.request

from results_index import GENRE_NAME
KNOWN_GENRES = set(GENRE_NAME) | set(GENRE_NAME.values())
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
    ap.add_argument("--more", type=int, default=25)
    a = ap.parse_args()
    out = []
    for x in a.artists:
        x, _, g = x.partition("@")
        genre = g.strip().lower() or a.genre
        if genre not in KNOWN_GENRES:                      # a typo would silently create a pool genre of its own
            raise SystemExit(f"unknown genre {genre!r} for {x}: use one of {', '.join(sorted(KNOWN_GENRES))}")
        sid = re.search(r"artist/([A-Za-z0-9]+)", x).group(1) if "artist/" in x else x
        ent = fetch("artist", sid)
        tracks = [dict(title=t.get("title"), artists=t.get("subtitle"), seconds=(t.get("duration") or 0) / 1000) for t in (ent.get("trackList") or [])]
        out.append(dict(kind="artist", id=sid, name=ent.get("name") or ent.get("title"), genre=genre, more=a.more, tracks=tracks))
        print(f"{sid}  {out[-1]['name']!r} [{genre}]: {len(tracks)} tracks: " + "; ".join(t["title"] for t in tracks[:5]))
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
