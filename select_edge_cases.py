"""Pick edge-case test songs from the MTG-Jamendo VALIDATION split.

Why the validation split: the official test split is kept untouched for the final
honest score; edge-case exploration is tuning, so it uses separate songs.
Output: edge_cases.csv (group, jamendo_id, artist, album, duration, tags, what_should_happen)
"""
import csv, random, collections

SPLIT = "data/split0-autotagging-validation.tsv"
PER_GROUP = 8
random.seed(7)

def load(path):
    rows = []
    with open(path) as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            tags = p[5:]
            rows.append(dict(
                track=p[0], jamendo_id=int(p[0].split("_")[1]), artist=p[1], album=p[2],
                duration=float(p[4]),
                mood={t.split("---")[1] for t in tags if t.startswith("mood/theme")},
                genre={t.split("---")[1] for t in tags if t.startswith("genre")},
                inst={t.split("---")[1] for t in tags if t.startswith("instrument")},
                tags=" ".join(t.split("---")[1] for t in tags)))
    return rows

HAPPY = {"happy", "upbeat", "fun", "party", "positive"}
SADDARK = {"sad", "melancholic", "dark"}
CALM = {"calm", "soft", "relaxing", "slow", "meditative"}
LOUD_GENRES = {"rock", "punkrock", "metal", "hardrock", "grunge", "alternativerock",
               "dance", "house", "techno", "edm", "eurodance", "drumnbass", "industrial"}
QUIET_GENRES = {"folk", "singersongwriter", "easylistening", "bossanova", "classical", "ambient", "newage"}
BEAT_INST = {"drums", "drummachine", "beat", "percussion", "bongo"}

loud = lambda r: ("energetic" in r["mood"] or r["genre"] & LOUD_GENRES) and not (r["mood"] & CALM)
quiet = lambda r: (r["mood"] & CALM or r["genre"] & QUIET_GENRES) and "energetic" not in r["mood"] and not (r["genre"] & LOUD_GENRES)
normal_len = lambda r: 90 <= r["duration"] <= 420

GROUPS = [
 # name, filter, what should happen
 ("mood_loud_happy", lambda r: normal_len(r) and loud(r) and r["mood"] & HAPPY and not r["mood"] & SADDARK,
  "Mood: high energy AND high happiness (top-right corner)"),
 ("mood_loud_sad_dark", lambda r: normal_len(r) and loud(r) and r["mood"] & SADDARK and not r["mood"] & HAPPY,
  "Mood: high energy but LOW happiness. Must land away from loud_happy on the happiness score; loudness alone should NOT separate these"),
 ("mood_quiet_happy", lambda r: normal_len(r) and quiet(r) and r["mood"] & HAPPY and not r["mood"] & SADDARK,
  "Mood: low energy, high happiness"),
 ("mood_quiet_sad", lambda r: normal_len(r) and quiet(r) and r["mood"] & {"sad", "melancholic"} and not r["mood"] & HAPPY,
  "Mood: low energy, low happiness"),
 ("sound_happy_classical", lambda r: normal_len(r) and r["genre"] & {"classical", "orchestral", "symphonic"} and r["mood"] & HAPPY
            and not r["genre"] & {"electronic", "dance", "pop", "techno", "house"}
            and not r["inst"] & {"drums", "drummachine", "synthesizer", "electricguitar", "beat"},
  "Same mood as happy_electronic but different style: Sound should keep them APART, Mood should keep them CLOSE"),
 ("sound_happy_electronic", lambda r: normal_len(r) and r["genre"] & {"electronic", "dance", "house", "electropop"} and r["mood"] & HAPPY and not r["genre"] & {"classical", "orchestral"},
  "Pair group for sound_happy_classical"),
 ("inst_solo_piano", lambda r: normal_len(r) and r["inst"] == {"piano"},
  "Instruments: piano should be the top instrument"),
 ("inst_acoustic_guitar", lambda r: normal_len(r) and r["inst"] & {"acousticguitar", "classicalguitar"} and not r["inst"] & ({"electricguitar", "synthesizer", "drummachine"} | BEAT_INST),
  "Instruments: acoustic/classical guitar on top, no drums"),
 ("inst_full_band", lambda r: normal_len(r) and {"drums", "bass", "electricguitar"} <= r["inst"],
  "Instruments: drums + bass + electric guitar all high"),
 ("inst_electronic_only", lambda r: normal_len(r) and r["inst"] & {"synthesizer", "drummachine", "computer"} and not r["inst"] & {"guitar", "electricguitar", "acousticguitar", "piano", "violin", "cello", "drums"},
  "Instruments: synth / drum machine on top, no real guitar/piano/strings"),
 ("inst_strings_no_drums", lambda r: normal_len(r) and r["inst"] & {"violin", "cello", "strings", "orchestra"} and not r["inst"] & BEAT_INST,
  "Instruments: strings on top, drums low"),
 ("rhythm_fast", lambda r: normal_len(r) and (r["genre"] & {"drumnbass", "punkrock"} or "fast" in r["mood"]),
  "Rhythm: high speed (or half of it, ~85 for 170 BPM d&b) -> tests the half/double allowance"),
 ("rhythm_half_double_trap", lambda r: normal_len(r) and r["genre"] & {"dubstep", "triphop", "hiphop"},
  "Rhythm: speed often detected at half or double; same-group songs should still match"),
 ("rhythm_no_steady_beat", lambda r: normal_len(r) and r["genre"] & {"ambient", "darkambient", "classical"} and not r["inst"] & BEAT_INST and r["mood"] & (CALM | {"soundscape", "space", "dream"}),
  "Rhythm: beat confidence should be LOW; these songs must not get confident speed matches"),
 ("voice_tagged_vocal", lambda r: normal_len(r) and "voice" in r["inst"],
  "Voice: singing present -> Voice step should run"),
 ("voice_instrumental", lambda r: normal_len(r) and r["genre"] & {"instrumentalpop", "instrumentalrock", "orchestral"} and "voice" not in r["inst"],
  "Voice: no singing -> Voice must be SKIPPED, not compared"),
 ("parts_long_changing", lambda r: r["duration"] > 420 and r["genre"] & {"progressive", "postrock", "trance", "electronic", "soundtrack"},
  "3 parts: parts should differ a lot -> whole-song average vs best part matters most here"),
 ("parts_very_short", lambda r: 30 <= r["duration"] < 90,
  "Short songs: the 3 x 30 s parts overlap -> check part selection doesn't break"),
]

def main():
    rows = load(SPLIT)
    out, used = [], set()
    for name, f, expect in GROUPS:
        cand = [r for r in rows if f(r) and r["track"] not in used]
        random.shuffle(cand)
        picked, artists = [], set()
        for r in cand:                         # one song per artist for variety
            if r["artist"] in artists: continue
            picked.append(r); artists.add(r["artist"]); used.add(r["track"])
            if len(picked) == PER_GROUP: break
        print(f"{name:26s} candidates={len(cand):5d} picked={len(picked)}")
        for r in picked:
            out.append(dict(group=name, jamendo_id=r["jamendo_id"], mtg_track=r["track"], artist=r["artist"],
                            album=r["album"], duration=r["duration"], tags=r["tags"], expect=expect,
                            listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree=""))

    # Same-artist, different-album pairs (Voice + Sound 'same singer' test)
    by_artist = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        if normal_len(r) and r["genre"] & {"pop", "singersongwriter", "rnb", "soul", "rap", "folk", "indie"} and not r["genre"] & {"instrumentalpop", "classical"}:
            by_artist[r["artist"]][r["album"]].append(r)
    multi = [a for a, albums in by_artist.items() if len(albums) >= 2]
    random.shuffle(multi)
    n = 0
    for a in multi[:8]:
        albums = list(by_artist[a].items())[:2]
        for alb, songs in albums:
            r = songs[0]
            out.append(dict(group="voice_same_artist_diff_album", jamendo_id=r["jamendo_id"], mtg_track=r["track"],
                            artist=a, album=alb, duration=r["duration"], tags=r["tags"],
                            expect="Same singer, different album: should find the partner song in its top 10 (Voice) more often than Sound alone does",
                            listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree=""))
            n += 1
    print(f"{'voice_same_artist_diff_album':26s} artists={len(multi)} picked songs={n}")

    with open("edge_cases.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print("total", len(out))


if __name__ == "__main__":
    main()
