"""Add an artist's YouTube channel to the pool list (metadata only; run_tests.py analyses the songs later).

  python add_channel.py https://www.youtube.com/channel/UC... --artist "Dame Atlas" --genre rnb --max 25

Takes the channel's uploads (yt-dlp, no API quota), keeps 90-480 s songs, drops intros / outros / interludes / skits / instrumentals /
loops / films / non-song titles (build_youtube.NOT_A_SONG), keeps ONE version of a song (the most viewed), and adds the --max most
viewed. `genre` must be an existing pool genre (the group becomes yt_<genre>). Songs already in the pool are skipped.
"""
import argparse, csv, os, re, sys
import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_youtube import NOT_A_SONG
from results_index import pool_keys, latest_rows, write_list

SKIP = re.compile(r"\b(intro|outro|interlude|skit|instrumental|1 ?hour|hours?|loop|short film|trailer|behind the|teaser|making of|"
                  r"live (session|at|from)|reaction|cover|karaoke|vlog|diary|documentary|unboxing|back ?story|jacket shooting|recap|"
                  r"short ver(sion)?|on sale|tickets?)\b|1시간|반복|日誌|日记|紀錄|纪录|紀實|纪实|開箱|开箱|開賣|开卖|購物台|花絮|幕後|幕后|回顧|回顾|拍攝|拍摄|back ?story|unboxing", re.I)   # 16 Oct: a band channel's vlogs, tour films, unboxings


def key_of(title, artist):
    t = re.sub(r"[\(\[].*?[\)\]]", "", title or "")
    t = re.sub(rf"^{re.escape(artist)}\s*[-–:]\s*", "", t, flags=re.I)
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def clean_title(title, artist):
    t = re.sub(rf"^{re.escape(artist)}\s*[-–:]\s*", "", title or "", flags=re.I)
    t = re.sub(r"\s*[\(\[]\s*(official|lyric|lyrics|audio|visuali[sz]er|music video|m/v|video)[^\)\]]*[\)\]]", "", t, flags=re.I)
    return t.strip() or title


def _growth_running():
    """True while a pool-growing job runs (they read pool_youtube.csv once and rewrite it after each search)."""
    import subprocess
    try:
        out = subprocess.run(["pgrep", "-f", "[b]oost_artists.sh|[g]row_more.sh|[b]uild_youtube.py|[b]uild_from_spotify.py"], capture_output=True, text=True).stdout.split()
    except OSError:
        return False
    return any(p != str(os.getpid()) for p in out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--artist", required=True)
    ap.add_argument("--genre", required=True)
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    url = a.url if "/videos" in a.url or "/channel/" not in a.url else a.url.rstrip("/") + "/videos"
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True})
    try:
        info = ydl.extract_info(url, download=False)
    except Exception:                                   # e.g. an auto-generated 'Topic' channel has no Videos tab
        info = ydl.extract_info(a.url, download=False)
    if not a.dry_run and _growth_running():
        raise SystemExit("a pool-growing job (boost_artists.sh / grow_more.sh / build_youtube.py / build_from_spotify.py) is running: it keeps its own copy of "
                         "pool_youtube.csv and would overwrite these songs. Run this again when it has finished (or add --dry-run to look).")
    existing = list(csv.DictReader(open(os.path.join(HERE, "pool_youtube.csv"), encoding="utf-8-sig")))
    taken = set(pool_keys()) | set(latest_rows()) | {f"youtube_{r['track_id']}" for r in existing}
    best = {}
    for e in info.get("entries", []):
        title, dur = e.get("title") or "", e.get("duration") or 0
        if not e.get("id") or f"youtube_{e['id']}" in taken or not (90 <= dur <= 480):
            continue
        if SKIP.search(title) or NOT_A_SONG.search(title):
            continue
        k = key_of(title, a.artist)
        if k and (k not in best or (e.get("view_count") or 0) > (best[k].get("view_count") or 0)):
            best[k] = e
    pick = sorted(best.values(), key=lambda e: -(e.get("view_count") or 0))[: a.max]
    rows = [dict(source="youtube", track_id=e["id"], title=clean_title(e.get("title"), a.artist), artist=a.artist, duration=e.get("duration"),
                 listens=e.get("view_count") or 0, licence="youtube-standard", listen=f"https://www.youtube.com/watch?v={e['id']}",
                 site_genre=a.genre, group=f"yt_{a.genre}", i_agree="") for e in pick]
    print(f"{a.artist}: channel has {len(info.get('entries', []))} uploads -> {len(rows)} songs" + (" (dry run)" if a.dry_run else ""))
    for r in rows:
        print(f"   {r['track_id']}  {int(r['duration']):4d}s  {int(r['listens']):>9,}  {r['title'][:60]}")
    if rows and not a.dry_run:
        write_list(os.path.join(HERE, "pool_youtube.csv"), existing + rows)


if __name__ == "__main__":
    main()
