"""Pick the songs for the OFFICIAL test from the MTG-Jamendo TEST split (the sealed split). Analyses nothing.

  python select_test_split.py --dry-run    # preview the group sizes, write nothing
  python select_test_split.py              # writes test_split.csv (+ test_split_freeze.json), about 1,500 songs to analyse
  python select_test_split.py --scale 0.7  # smaller (0.7 = about 1,000 songs)
  python -u run_tests.py --list test_split.csv        # then analyse them (resumable, audio deleted after each song)
  python evaluate.py --split test                     # the official score -> report_test.html

Same groups and rules as the validation list (select_edge_cases.py / expand_edge_cases.py), different songs: the split's
artists are separate from the validation split's. What differs on purpose:
  * only the genres kept in the recommendation pool get a genre group (no punk, latin, classical or soundtrack group);
    classical and ambient still appear inside the functional groups that need them (Sound-vs-Mood, "no steady beat").
  * 'same artist, different album' pairs are plentiful (70 artists): they score Sound now and are the data the Voice
    A/B test needs later (30 pairs; keep Voice only if it beats Sound by 10 points).
  * songs longer than 15 minutes are left out (a 69-minute file is slow and says little).
About 30% of Jamendo songs are no longer available, so every group is listed 1.4 times larger than the number wanted.

The test split is used ONCE. test_split_freeze.json records the code and the list as they were before any test song was
analysed; do not change the models, thresholds or pass bars after looking at the results.
"""
import argparse, collections, csv, hashlib, json, math, os, random, subprocess, sys, time

import select_edge_cases as base

HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT = os.path.join(HERE, "data", "split0-autotagging-test.tsv")
OUT = os.path.join(HERE, "test_split.csv")
FREEZE = os.path.join(HERE, "test_split_freeze.json")
SEED = 2026
OVERFILL = 1.4            # list this many times the songs wanted (about 30% are gone from Jamendo)
PER_GROUP, LOUD_EXTRA, PER_GENRE, PER_WIDE, SAME_ARTIST_PAIRS = 30, 40, 35, 80, 70
MAX_SECONDS = 900

# genre families kept in the pool (mainstream). A song counts for a family only if its genre tags fall in that family.
GENRES = {
    "rock": {"rock", "hardrock", "classicrock", "grunge", "rocknroll"},
    "alternative": {"alternative", "alternativerock"},
    "indie": {"indie"},
    "pop": {"pop", "synthpop", "electropop", "poprock"},
    "hiphop": {"hiphop", "rap"},
    "rnb_soul": {"rnb", "soul"},
    "singersongwriter": {"singersongwriter"},
    "folk": {"folk", "popfolk", "celtic"},
    "country": {"country"},
    "blues": {"blues", "bluesrock"},
    "jazz": {"jazz", "acidjazz", "jazzfusion", "swing"},
    "reggae": {"reggae", "dub"},
    "metal": {"metal"},
    "world": {"world", "ethno", "worldfusion"},
    "techno_house": {"techno", "house", "deephouse", "club", "edm", "trance", "dance", "eurodance"},
    "dnb_dubstep": {"drumnbass", "dubstep", "breakbeat"},
    "ambient": {"ambient", "darkambient"},
    "lounge_chill": {"lounge", "chillout", "downtempo", "triphop"},
}
ALL_G = set().union(*GENRES.values())
# A family with few songs in the split may share tags with its natural neighbours (singer-songwriter songs are usually
# also tagged folk), otherwise it would have 3 songs. Other families still must not appear in the song's tags.
ALLOW_OVERLAP = {"singersongwriter": ("folk", "pop", "indie"), "country": ("folk", "blues", "rock"),
                 "indie": ("rock", "alternative", "pop"), "blues": ("rock", "jazz"), "rnb_soul": ("pop", "hiphop", "jazz")}
VOCAL_GENRES = {"pop", "singersongwriter", "rnb", "soul", "rap", "hiphop", "folk", "indie", "alternative", "rock"}


def listed(n, scale):
    return math.ceil(n * scale * OVERFILL)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="multiply every group size (0.7 = about 1,000 songs)")
    ap.add_argument("--dry-run", action="store_true", help="show the group sizes only; write nothing")
    a = ap.parse_args()
    if os.path.exists(OUT) and not a.dry_run:
        sys.exit(f"{os.path.basename(OUT)} already exists: the test list is made once. Delete it by hand only if you "
                 "mean to start the official test over (and say so in the report).")
    rng = random.Random(SEED)
    rows = [r for r in base.load(SPLIT) if r["duration"] <= MAX_SECONDS]
    used, count, group_artists, out = set(), collections.Counter(), collections.defaultdict(set), []

    def add(r, group, expect):
        used.add(r["jamendo_id"]); group_artists[group].add(r["artist"]); count[group] += 1
        out.append(dict(group=group, jamendo_id=r["jamendo_id"], mtg_track=r["track"], artist=r["artist"],
                        album=r["album"], duration=r["duration"], tags=r["tags"], expect=expect,
                        listen=f"https://www.jamendo.com/track/{r['jamendo_id']}", i_agree=""))

    def fill(group, filt, want, expect):
        cand = [r for r in rows if filt(r) and r["jamendo_id"] not in used]
        rng.shuffle(cand)
        for r in cand:
            if count[group] >= want:
                break
            if r["artist"] in group_artists[group]:          # one song per artist per group
                continue
            add(r, group, expect)
        flag = "" if count[group] >= want else f"   <- only {count[group]} of {want} wanted (not enough songs)"
        print(f"  {group:30s} {count[group]:4d}{flag}")

    SAD = {"sad", "melancholic", "dark"}
    jobs = []                                              # (group, filter, how many to list, what should happen)
    for name, f, expect in base.GROUPS:
        jobs.append((name, f, listed(LOUD_EXTRA if name in ("mood_loud_happy", "mood_loud_sad_dark") else PER_GROUP, a.scale), expect))
    for g, tags in GENRES.items():
        other = ALL_G - tags - set().union(*(GENRES[x] for x in ALLOW_OVERLAP.get(g, ())))
        f = lambda r, tags=tags, other=other: base.normal_len(r) and r["genre"] & tags and not r["genre"] & other
        jobs.append((f"genre_{g}", f, listed(PER_GENRE, a.scale),
                     f"Style group '{g}': Sound should rate songs in this group closer to each other than to other genres"))
    jobs.append(("mood_wide_happy", lambda r: base.normal_len(r) and r["mood"] & base.HAPPY and not r["mood"] & SAD,
                 listed(PER_WIDE, a.scale), "Any genre, happy-tagged: feeds the happy-vs-sad test split by measured loudness"))
    jobs.append(("mood_wide_sad", lambda r: base.normal_len(r) and r["mood"] & SAD and not r["mood"] & base.HAPPY,
                 listed(PER_WIDE, a.scale), "Any genre, sad/dark-tagged: feeds the happy-vs-sad test split by measured loudness"))
    # the scarcest groups pick first, so a common group can't use up the few songs a rare group (e.g. happy classical) has
    jobs.sort(key=lambda j: len({r["artist"] for r in rows if j[1](r)}))
    print("groups, scarcest first (one song per artist per group):")
    for name, f, want, expect in jobs:
        fill(name, f, want, expect)

    print("same artist, different album (Sound now, Voice A/B later):")
    by_artist = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        if base.normal_len(r) and r["genre"] & VOCAL_GENRES and not r["genre"] & {"instrumentalpop", "classical", "instrumentalrock"} \
                and r["jamendo_id"] not in used:
            by_artist[r["artist"]][r["album"]].append(r)
    multi = [x for x, albums in by_artist.items() if len(albums) >= 2]
    rng.shuffle(multi)
    n_art = 0
    for x in multi[:listed(SAME_ARTIST_PAIRS, a.scale)]:
        for alb, songs in list(by_artist[x].items())[:2]:
            add(rng.choice(songs), "voice_same_artist_diff_album",
                "Same singer, different album: should find the partner song in its top 10 (Sound now; Voice must beat it by 10 points later)")
        n_art += 1
    print(f"  {'voice_same_artist_diff_album':30s} {count['voice_same_artist_diff_album']:4d}  ({n_art} artists, 2 albums each; {len(multi)} possible)")

    if a.dry_run:
        print(f"\n(dry run) {len(out)} songs would be listed, about {int(len(out) / OVERFILL)} expected to be analysed. Nothing written.")
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print(f"\n{len(out)} songs listed in {os.path.basename(OUT)} (about {int(len(out) / OVERFILL)} expected to be analysed)")
    freeze(out)


def freeze(out):
    """A fingerprint of everything that must not change once test songs are analysed."""
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True).stdout.strip()
        except Exception:
            return ""
    code = ["scoring.py", "analyze.py", "match.py", "models.py", "evaluate.py", "blind_test.py", "select_test_split.py",
            "select_edge_cases.py", "expand_edge_cases.py"]
    rec = dict(made=time.strftime("%Y-%m-%d %H:%M"), seed=SEED, songs_listed=len(out),
               groups=dict(collections.Counter(r["group"] for r in out)),
               test_split_csv_sha256=sha(OUT), analysis_version=None,
               git_head=git("rev-parse", "HEAD"), uncommitted_changes=bool(git("status", "--porcelain")),
               code_sha256={fn: sha(os.path.join(HERE, fn)) for fn in code if os.path.exists(os.path.join(HERE, fn))},
               model_files=sorted(os.listdir(os.path.join(HERE, "models"))) if os.path.isdir(os.path.join(HERE, "models")) else [],
               note="Written BEFORE any test-split song was analysed. Changing code or thresholds after seeing test results "
                    "voids the official score; if you must, say so in the report.")
    try:
        import analyze
        rec["analysis_version"] = analyze.ANALYSIS_VERSION
    except Exception:
        pass
    with open(FREEZE, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    print(f"freeze record: {os.path.basename(FREEZE)} (git {rec['git_head'][:8] or 'n/a'}"
          f"{', with UNCOMMITTED changes' if rec['uncommitted_changes'] else ''})")


if __name__ == "__main__":
    main()
