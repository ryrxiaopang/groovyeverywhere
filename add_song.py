"""Add single songs you pick by hand to the pool (metadata only; the numbers come from run_tests.py afterwards).

  python add_song.py "https://www.youtube.com/watch?v=2EO3-MsH5II" --genre pop            # preview: title, channel, length, views
  python add_song.py LINK [LINK ...] --genre chiphop --apply                               # add them to pool_handpicked.csv
  python -u run_tests.py --list pool_handpicked.csv                                       # then analyse them (never while another analysis or a boost runs)

The songs go into their OWN list, pool_handpicked.csv (one of results_index.POOL_LISTS), not pool_youtube.csv: a boost or a YouTube search that is
running keeps its own copy of pool_youtube.csv and would overwrite a song added there in the meantime. A song already in any pool list is
skipped (also when it was marked i_agree = n: say so instead of adding it twice). --genre is a pool group key such as pop, rnb, indie, hiphop,
chiphop, khiphop, jpop, mrock (results_index.GENRE_NAME); it decides the style group and the language guess. The next quality pass tags it for AI.
"""
import argparse, csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import GENRE_NAME, list_key, write_list

LIST = "pool_handpicked.csv"
COLS = ["source", "track_id", "title", "artist", "duration", "listens", "licence", "listen", "site_genre", "group", "i_agree"]


def info(vid):
    """Title, channel, length and views of one video (yt-dlp, no download, no API quota)."""
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
        d = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return dict(title=d.get("title") or "", channel=d.get("channel") or d.get("uploader") or "", duration=float(d.get("duration") or 0),
                views=int(d.get("view_count") or 0), live=bool(d.get("is_live")))


def existing(here=HERE):
    """{song key: 'in the pool' or 'marked out'} over every pool list."""
    from replace_songs import load_lists
    out = {}
    for rows, _ in load_lists(here).values():
        for r in rows:
            out[list_key(r)] = "marked out (i_agree = n)" if (r.get("i_agree") or "").strip().lower() in ("n", "no") else "already in the pool"
    return out


def plan(links, genre, get_info=info, here=HERE):
    """[(video id, row or None, note)]: the row to add, or None with the reason it is skipped."""
    from replace_songs import video_id
    from build_youtube import NOT_A_SONG, _clean_artist
    have, out, seen = existing(here), [], set()
    for link in links:
        vid = video_id(link) or (link if len(link) == 11 else None)
        if not vid:
            out.append((link, None, "not a YouTube link")); continue
        if vid in seen:
            continue
        seen.add(vid)
        if f"youtube_{vid}" in have:
            out.append((vid, None, have[f"youtube_{vid}"])); continue
        try:
            d = get_info(vid)
        except Exception as e:
            out.append((vid, None, f"YouTube did not answer: {str(e)[:100]}")); continue
        if d["live"] or not d["duration"]:
            out.append((vid, None, "a live stream or premiere, not a finished song")); continue
        note = []
        if not 60 <= d["duration"] <= 600:
            note.append(f"length {int(d['duration'])} s: check that it is one song")
        if NOT_A_SONG.search(d["title"]):
            note.append("the title looks like a non-song (lyrics / cover / mix ...): check it")
        row = dict(source="youtube", track_id=vid, title=d["title"], artist=_clean_artist(d["channel"]), duration=d["duration"], listens=d["views"],
                   licence="youtube-standard", listen=f"https://www.youtube.com/watch?v={vid}", site_genre=genre, group=f"yt_{genre}", i_agree="")
        out.append((vid, row, "; ".join(note)))
    return out


def apply(planned, here=HERE):
    """Append the new rows to pool_handpicked.csv (a .bak of the old file is kept). Returns how many were added."""
    path = os.path.join(here, LIST)
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig"))) if os.path.exists(path) else []
    new = [dict((c, r.get(c, "")) for c in COLS) for _, r, _ in planned if r]
    if new:
        write_list(path, rows + new)
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("links", nargs="+")
    ap.add_argument("--genre", default="pop", help="pool group key, e.g. pop, rnb, indie, hiphop, chiphop, khiphop, jpop, mrock")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.genre not in GENRE_NAME:
        raise SystemExit(f"unknown genre {a.genre!r}: use one of {', '.join(sorted(GENRE_NAME))}")
    planned = plan(a.links, a.genre)
    for vid, r, note in planned:
        if r:
            print(f"  add   {vid}  {r['title'][:60]} | {r['artist'][:30]} | {int(r['duration'])} s | {int(r['listens']):,} views -> yt_{a.genre}"
                  + (f"\n        !! {note}" if note else ""))
        else:
            print(f"  skip  {vid}  ({note})")
    if not a.apply:
        print("\n(preview: nothing changed. Add --apply to add them)")
        return
    n = apply(planned)
    print(f"\nadded {n} song(s) to {LIST}. Analyse them (when no other analysis or boost is running):  python -u run_tests.py --list {LIST}")


if __name__ == "__main__":
    main()
