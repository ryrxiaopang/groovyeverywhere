"""What Creative Commons (CC BY) music is on YouTube, per focus genre? A look before building anything.

  python cc_survey.py            # uses YOUTUBE_API_KEY; 16 searches (of the ~100 a day), downloads NOTHING

For each focus genre it searches YouTube's Music category twice, once for any video and once only for videos the
uploader marked "Creative Commons Attribution" (CC BY, the only CC licence YouTube offers), and prints:
  - how many CC results there are next to normal ones (a rough idea of supply)
  - up to 10 CC examples with their channel, so you can listen to a few and judge quality and singing
Results also go to results/cc_survey.csv (titles and channels only; links are kept less than 30 days, see below).

Caveat when reading the list: YouTube only blocks the CC mark on videos with a Content ID claim, so some uploaders
mark songs they don't own as CC. A real pool would only accept CC videos uploaded by the artist's own channel.
"""
import csv, datetime as dt, os, sys
import requests

GENRES = {"pop": "pop song", "rnb": "r&b song", "hiphop": "hip hop rap song", "indie": "indie song",
          "alternative": "alternative rock song", "rock": "rock song", "singer-songwriter": "acoustic singer songwriter",
          "electronic": "electronic song vocals"}
API = "https://www.googleapis.com/youtube/v3/search"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "cc_survey.csv")


def search(q, cc):
    p = dict(part="snippet", type="video", videoCategoryId="10", maxResults=25, q=q,
             key=os.environ["YOUTUBE_API_KEY"])
    if cc:
        p["videoLicense"] = "creativeCommon"
    r = requests.get(API, params=p, timeout=20)
    if r.status_code == 403:
        sys.exit("YouTube refused (daily allowance used up?): try again tomorrow")
    r.raise_for_status()
    j = r.json()
    return j.get("pageInfo", {}).get("totalResults", 0), j.get("items", [])


def main():
    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("set YOUTUBE_API_KEY first")
    rows = []
    print(f"{'genre':18s} {'all music':>10s} {'CC BY':>8s}   (YouTube's rough result counts)")
    for g, q in GENRES.items():
        n_all, _ = search(q, False)
        n_cc, items = search(q, True)
        print(f"{g:18s} {n_all:10,d} {n_cc:8,d}")
        for it in items[:10]:
            s = it["snippet"]
            rows.append(dict(genre=g, title=s.get("title", ""), channel=s.get("channelTitle", ""),
                             url=f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                             checked=dt.date.today().isoformat()))
    print("\nCC BY examples to listen to (do any sound like what your friends would want?):")
    for g in GENRES:
        print(f"\n  {g}")
        for r in [r for r in rows if r["genre"] == g]:
            print(f"    {r['title'][:60]:60s}  | {r['channel'][:28]:28s} {r['url']}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["genre"]); w.writeheader(); w.writerows(rows)
    print(f"\nsaved {OUT}. YouTube's rules allow keeping API data at most 30 days: delete it after you've listened.")


if __name__ == "__main__":
    main()
