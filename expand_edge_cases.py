"""Add more and wider test songs to edge_cases.csv WITHOUT changing the existing rows
(so songs already analysed are kept and skipped by run_tests.py).

Adds, all from the MTG-Jamendo VALIDATION split (test split stays untouched):
  1. Top-ups: every existing group grows to TOPUP_TO songs (loud-sad gets extra, it was short)
  2. 18 genre groups (genre_*): 10 "pure" songs each, for the Sound-vs-style test and pool variety
  3. Wide mood sample: 35 happy-tagged + 35 sad/dark-tagged songs from any genre, for the
     happy-vs-sad test split by MEASURED loudness (T1b)
About 30% of songs are expected to be missing from Jamendo now, so groups are over-filled.

  python expand_edge_cases.py      (safe to run once; running again adds nothing new)
"""
import csv, random, collections
import select_edge_cases as base

random.seed(11)
TOPUP_TO = 14
EXTRA = {"mood_loud_sad_dark": 24, "mood_loud_happy": 18}
GENRE_PER_GROUP = 10
WIDE_PER_SIDE = 35

GENRES = {
    "rock": {"rock", "hardrock", "alternativerock", "classicrock", "grunge"},
    "metal": {"metal", "heavymetal"},
    "punk": {"punkrock"},
    "pop": {"pop", "synthpop", "electropop"},
    "hiphop": {"hiphop", "rap"},
    "techno_house": {"techno", "house", "deephouse", "club", "edm", "trance"},
    "dnb_dubstep": {"drumnbass", "dubstep", "breakbeat"},
    "ambient": {"ambient", "darkambient"},
    "classical": {"classical", "symphonic"},
    "jazz": {"jazz", "acidjazz", "jazzfusion", "swing"},
    "blues": {"blues", "bluesrock"},
    "folk": {"folk", "popfolk", "celtic", "singersongwriter"},
    "country": {"country"},
    "reggae": {"reggae", "dub"},
    "latin": {"latin", "bossanova"},
    "world": {"world", "ethno", "worldfusion"},
    "soul_funk": {"soul", "rnb", "funk", "disco"},
    "lounge_chill": {"lounge", "chillout", "downtempo", "triphop"},
}
ALL_G = set().union(*GENRES.values())


def main():
    global rows, used, fields, count, group_artists, new, existing
    rows = base.load(base.SPLIT)
    with open("edge_cases.csv") as f:
        existing = list(csv.DictReader(f))
    used = {int(r["jamendo_id"]) for r in existing}
    fields = list(existing[0].keys())
    count = collections.Counter(r["group"] for r in existing)
    group_artists = collections.defaultdict(set)
    for r in existing:
        group_artists[r["group"]].add(r["artist"])
    new = []


    def add(r, group, expect):
        used.add(r["jamendo_id"]); group_artists[group].add(r["artist"]); count[group] += 1
        new.append(dict(group=group, jamendo_id=r["jamendo_id"], mtg_track=r["track"], artist=r["artist"],
                        album=r["album"], duration=r["duration"], tags=r["tags"], expect=expect,
                        listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree=""))


    def fill(group, filt, target, expect):
        cand = [r for r in rows if filt(r) and r["jamendo_id"] not in used]
        random.shuffle(cand)
        for r in cand:
            if count[group] >= target:
                break
            if r["artist"] in group_artists[group]:
                continue
            add(r, group, expect)
        return len(cand)


    # 1. top-ups of existing groups
    for name, f, expect in base.GROUPS:
        tgt = EXTRA.get(name, TOPUP_TO)
        n = fill(name, f, tgt, expect)
        print(f"top-up {name:26s} -> {count[name]:3d} (candidates left {n})")

    # 2. genre groups: songs whose genre tags fall in ONE family only
    for g, tags in GENRES.items():
        other = ALL_G - tags
        f = lambda r, tags=tags, other=other: base.normal_len(r) and r["genre"] & tags and not r["genre"] & other
        n = fill(f"genre_{g}", f, GENRE_PER_GROUP,
                 f"Style group '{g}': Sound should rate songs in this group closer to each other than to other genres")
        print(f"genre  {g:26s} -> {count['genre_' + g]:3d} (candidates {n})")

    # 3. wide mood sample, any genre
    HAPPY, SAD = base.HAPPY, {"sad", "melancholic", "dark"}
    fill("mood_wide_happy", lambda r: base.normal_len(r) and r["mood"] & HAPPY and not r["mood"] & SAD,
         WIDE_PER_SIDE, "Any genre, happy-tagged: feeds the happy-vs-sad test split by measured loudness")
    fill("mood_wide_sad", lambda r: base.normal_len(r) and r["mood"] & SAD and not r["mood"] & HAPPY,
         WIDE_PER_SIDE, "Any genre, sad/dark-tagged: feeds the happy-vs-sad test split by measured loudness")
    print(f"wide mood -> happy {count['mood_wide_happy']}, sad {count['mood_wide_sad']}")

    with open("edge_cases.csv", "a", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writerows(new)
    print(f"\nadded {len(new)} songs; edge_cases.csv now has {len(existing) + len(new)}")


if __name__ == "__main__":
    main()
