"""Are the YouTube songs we collect actually good? Two checks, no audio and no downloads.

  python check_youtube_quality.py               # red-flag report + a random listening sheet (youtube_listen_sheet.csv)
  python check_youtube_quality.py --n 40 --seed 3

1. AUTOMATIC RED FLAGS (a flag means "look at this one", not "it is bad"): titles that say playlist / mix /
   compilation / cover / karaoke / slowed / nightcore / lyrics / live / instrumental / type beat ..., the same title
   uploaded by several channels, a channel that appears many times, and (for analysed songs) a clip that is not
   full length or has no singing.
2. A RANDOM LISTENING SHEET: a seeded random sample with a link to each song and the questions that matter
   (is it a real song, does the genre fit, is it original, is the sound quality fine, would you add it?). Fill it in,
   then run with --score to get the share that passed. To drop a song from the pool, write n in the i_agree column of
   pool_youtube.csv (the song stays stored, but is no longer recommended).
"""
import argparse, collections, csv, os, random, re
import numpy as np
from results_index import latest_rows, RES

HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "pool_youtube.csv")
SHEET = os.path.join(HERE, "youtube_listen_sheet.csv")
FLAGS = {
    "playlist or long mix": r"\b(playlist|mix|compilation|hours?|hrs?|full album|non-?stop|megamix)\b|\b1 ?h\b",
    "cover or karaoke": r"\b(cover|covered|karaoke|tribute|piano version|acoustic version)\b",
    "altered audio": r"\b(slowed|reverb|sped ?up|nightcore|8d|bass boosted|remix|mashup|bootleg)\b",
    "lyrics or visualiser": r"\b(lyrics?|lyric video|visuali[sz]er|audio only)\b",
    "live or reaction": r"\b(live|concert|reaction|tutorial|trailer|podcast|asmr|interview|behind the scenes)\b",
    "not a song with singing": r"\b(instrumental|type beat|beat|bgm|ost|soundtrack|meditation|sleep|study|lofi)\b",
}
QUESTIONS = ["real_song (y/n)", "genre_fits (y/n)", "original_not_cover_or_remix (y/n)", "sound_quality_ok (y/n)",
             "would_add_to_my_playlist (y/n)", "notes"]


def read_list():
    with open(LIST, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def report(rows):
    n = len(rows)
    print(f"{n} YouTube songs in pool_youtube.csv\n")
    flagged, why = set(), collections.defaultdict(list)
    for r in rows:
        t = (r.get("title") or "").lower()
        for name, pat in FLAGS.items():
            if re.search(pat, t):
                flagged.add(r["track_id"]); why[name].append(r)
    print("Titles that deserve a look (a flag is a hint, not a verdict):")
    for name, rs in sorted(why.items(), key=lambda x: -len(x[1])):
        ex = "; ".join((x["title"] or "")[:40] for x in rs[:2])
        print(f"  {name:26s} {len(rs):4d}  e.g. {ex}")
    print(f"  -> {len(flagged)} of {n} songs ({100 * len(flagged) / n:.0f}%) have at least one flag\n")
    titles = collections.Counter(re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip() for r in rows)
    dup = sum(1 for v in titles.values() if v > 1)
    chans = collections.Counter(r.get("artist") for r in rows)
    print(f"Same title more than once: {dup} titles. Channels with 4+ songs: "
          f"{[(c, v) for c, v in chans.most_common(5) if v >= 4] or 'none'}")
    views = np.array([float(r["listens"]) for r in rows if r.get("listens") not in (None, "")])
    dur = np.array([float(r["duration"]) for r in rows if r.get("duration") not in (None, "")])
    print(f"Views: median {int(np.median(views)):,}, lowest tenth under {int(np.percentile(views, 10)):,}, "
          f"highest tenth over {int(np.percentile(views, 90)):,}. Length: median {int(np.median(dur))} s.")
    # analysed songs: full length and singing
    idx = latest_rows(RES)
    ok = [r for r in rows if idx.get(f"youtube_{r['track_id']}", {}).get("status") == "done"]
    if ok:
        full = [idx[f"youtube_{r['track_id']}"].get("full_length_ok") for r in ok]
        print(f"\nAnalysed so far: {len(ok)}. Downloaded length matches the listed length for "
              f"{100 * sum(str(x).lower() == 'true' for x in full) / len(ok):.0f}% of them.")
    return flagged


def make_sheet(rows, n, seed, flagged):
    rng = random.Random(seed)
    pick = rng.sample(rows, min(n, len(rows)))
    with open(SHEET, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "genre", "title", "channel", "views", "seconds", "auto_flag", "listen_here"] + QUESTIONS)
        for i, r in enumerate(pick, 1):
            w.writerow([f"yt-{i:02d}", (r.get("site_genre") or r.get("group", "")), r.get("title"), r.get("artist"),
                        r.get("listens"), r.get("duration"), "yes" if r["track_id"] in flagged else "",
                        r.get("listen") or f"https://www.youtube.com/watch?v={r['track_id']}"] + [""] * len(QUESTIONS))
    print(f"\nlistening sheet with {len(pick)} random songs: {SHEET}\n(open it in Excel or Google Sheets, listen about 30 s of each)")
    return pick


def score():
    with open(SHEET, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if (r.get(QUESTIONS[0]) or "").strip()]
    if not rows:
        print("nothing filled in yet"); return
    yes = lambda v: str(v).strip().lower() in ("y", "yes")
    print(f"{len(rows)} songs listened to")
    for q in QUESTIONS[:-1]:
        v = [yes(r[q]) for r in rows if (r.get(q) or "").strip()]
        if v:
            p = np.mean(v); se = (p * (1 - p) / len(v)) ** 0.5
            print(f"  {q:40s} {100 * p:3.0f}% yes  (plus or minus {196 * se:.0f} points)")
    good = [yes(r[QUESTIONS[0]]) and yes(r[QUESTIONS[2]]) and yes(r[QUESTIONS[3]]) for r in rows]
    print(f"\nsongs that are real, original and well recorded: {100 * np.mean(good):.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--score", action="store_true", help="summarise a filled-in sheet")
    a = ap.parse_args()
    if a.score:
        return score()
    rows = read_list()
    flagged = report(rows)
    make_sheet(rows, a.n, a.seed, flagged)


if __name__ == "__main__":
    main()
