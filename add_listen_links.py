"""Give every song in the friends' sheets a YouTube link where one can be VERIFIED (blind_sheets/sheet_*.csv).

  python add_listen_links.py             # after  python blind_test.py --sheets

  * songs that already come from YouTube keep their own link;
  * Jamendo / FMA / Audius songs: search YouTube (yt-dlp, no API quota) for "artist title" and accept a result only if the
    artist is in the channel or title, the title matches, and the length is within a few seconds of the original;
  * no verified match -> the original page (Jamendo / FMA / Audius, a normal web player) stays as the link.
`listen_here` = the link a friend should use; `also_on` = the original page when it is a different one.
Spotify is not used: searching it needs a developer key, and a wrong guess would send a friend to the wrong song.
Reads the song key from results/blind/key.csv ONLY to find the song's length; it never prints or stores which list a song is in.
"""
import csv, glob, json, os, re, unicodedata
import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
CACHE = os.path.join(RES, "link_cache.json")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def listed_duration(key):
    try:
        return float(json.load(open(os.path.join(RES, "meta", f"{key}.json"), encoding="utf-8")).get("duration") or 0)
    except Exception:
        return 0.0


def good_match(cand, title, artist, dur):
    ct, cc = " ".join(norm(cand.get("title"))), " ".join(norm(cand.get("channel") or cand.get("uploader")))
    t, a = norm(title), norm(artist)
    if not t or not a:
        return False
    if cand.get("is_live"):
        return False
    if re.search(r"\b(cover|remix|slowed|sped up|nightcore|live|reaction|karaoke|instrumental)\b", ct) and not re.search(
            r"\b(cover|remix|slowed|live)\b", " ".join(t)):
        return False
    title_ok = sum(w in ct.split() for w in t) >= max(1, int(0.8 * len(t) + 0.5))
    artist_ok = sum(w in (ct + " " + cc).split() for w in a) >= max(1, int(0.7 * len(a) + 0.5))
    d = cand.get("duration") or 0
    dur_ok = (not dur) or abs(d - dur) <= max(6.0, 0.03 * dur)
    return title_ok and artist_ok and dur_ok


def main():
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    key_of = {r["item"]: r["key"] for r in csv.DictReader(open(os.path.join(RES, "blind", "key.csv"), encoding="utf-8"))}
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True})
    found = kept = total = 0
    for sheet in sorted(glob.glob(os.path.join(HERE, "blind_sheets", "sheet_*.csv"))):
        rows = list(csv.DictReader(open(sheet, encoding="utf-8-sig")))
        out = []
        for r in rows:
            total += 1
            orig = r["listen_here"]
            link, also = orig, ""
            if "youtube.com" not in orig and "youtu.be" not in orig:
                key = key_of.get(r["item"], "")
                ck = key or orig
                if ck not in cache:
                    dur, hit = listed_duration(key), ""
                    try:
                        info = ydl.extract_info(f"ytsearch6:{r['artist']} {r['title']}", download=False)
                        for e in info.get("entries", []):
                            if good_match(e, r["title"], r["artist"], dur):
                                hit = f"https://www.youtube.com/watch?v={e['id']}"
                                break
                    except Exception as e:
                        print("  search failed:", str(e)[:80])
                    cache[ck] = hit
                    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=0)
                if cache[ck]:
                    link, also = cache[ck], orig
                    found += 1
                else:
                    kept += 1
            r2 = dict(r)
            r2["listen_here"], r2["also_on"] = link, also
            out.append(r2)
        cols = ["item", "your_song", "listen_here", "also_on", "title", "artist", "note",
                "would_add (y/n)", "heard_before (y/n)", "rating (1-5)"]
        with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(out)
        print(f"  {os.path.basename(sheet)}: {len(out)} songs")
    yt_native = total - found - kept
    print(f"{total} songs: {yt_native} already YouTube, {found} YouTube link found and verified, "
          f"{kept} keep their original page (no verified YouTube match)")


if __name__ == "__main__":
    main()
