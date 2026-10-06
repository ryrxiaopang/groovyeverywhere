"""Pick the DEVELOPMENT songs for the Voice feature from the MTG-Jamendo TRAIN split (VOICE_PIPELINE.md section 4).

  python select_voice_dev.py --dry-run     # sizes only
  python select_voice_dev.py               # writes voice_dev.csv
  (then in the GPU environment)  python -u run_voice.py --list voice_dev.csv

The train split is not sealed (the Sony voice models never trained on MTG data), so Voice settings (which of the 5
models, stem or mix, window averaging, rescaling, singing gate) are chosen on these songs and then frozen before the
sealed test split is touched.

  * artists: likely-sung (vocal genre, not instrumental/classical), 2+ albums, normal length; up to 3 songs each, spread
    over at least 2 albums, so every artist gives different-album partners.
  * distractors: other train songs from vocal genres by other artists (so the library is not only the question songs).
  * listed 1.4x the wanted size because about 30% of Jamendo songs are gone.
The choice uses only the split file and a fixed seed: no result was looked at.
"""
import argparse, collections, csv, os, random

import select_edge_cases as base
from select_test_split import VOCAL_GENRES, OVERFILL, MAX_SECONDS

HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT = os.path.join(HERE, "data", "split0-autotagging-train.tsv")
OUT = os.path.join(HERE, "voice_dev.csv")
SEED = 20261007
ARTISTS, PER_ARTIST, DISTRACTORS = 100, 3, 300
NOT_SUNG = {"instrumentalpop", "classical", "instrumentalrock"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rng = random.Random(SEED)
    rows = [r for r in base.load(SPLIT) if r["duration"] <= MAX_SECONDS and base.normal_len(r)
            and r["genre"] & VOCAL_GENRES and not r["genre"] & NOT_SUNG]
    by_artist = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        by_artist[r["artist"]][r["album"]].append(r)
    multi = sorted(x for x, albums in by_artist.items() if len(albums) >= 2)
    rng.shuffle(multi)
    chosen = multi[: int(ARTISTS * OVERFILL)]
    out, used = [], set()

    def add(r, group):
        used.add(r["jamendo_id"])
        out.append(dict(group=group, jamendo_id=r["jamendo_id"], mtg_track=r["track"], artist=r["artist"],
                        album=r["album"], duration=r["duration"], tags=r["tags"],
                        listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree=""))

    for x in chosen:
        albums = list(by_artist[x].items())
        rng.shuffle(albums)
        picks = [rng.choice(songs) for _, songs in albums[:PER_ARTIST]]        # one song from each of up to 3 albums
        if len(picks) < PER_ARTIST:                                              # 2 albums: add a 2nd song from one
            extra = [s for s in albums[0][1] if s not in picks]
            if extra:
                picks.append(rng.choice(extra))
        for r in picks:
            add(r, "voice_dev_artist")
    artists_in = set(chosen)
    rest = [r for r in rows if r["artist"] not in artists_in and r["jamendo_id"] not in used]
    rng.shuffle(rest)
    seen = set()
    n = 0
    for r in rest:                                                               # distractors: one song per artist
        if r["artist"] in seen:
            continue
        seen.add(r["artist"]); add(r, "voice_dev_distractor"); n += 1
        if n >= int(DISTRACTORS * OVERFILL):
            break
    print(f"{len(multi)} possible artists; listing {len(chosen)} artists ({len(out) - n} songs) + {n} distractors "
          f"= {len(out)} songs (about {int(len(out) / OVERFILL)} expected to be analysed)")
    if a.dry_run:
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print(f"wrote {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
