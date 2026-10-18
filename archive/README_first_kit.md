> **Note (11 Oct 2026):** this README describes the first test kit (160 songs, Jamendo/FMA/Audius). The project has moved on: the current state, decisions and next steps are in `CLAUDE.md` (start at "START HERE"), the plain-language overview is the Claude doc "groovyeverywhere: Project Guide", and the round-2 success rule is `SUCCESS_RULE.md`.

**Where things are now (12 Oct 2026):** `CLAUDE.md` (state, decisions, file map), `TODO.md` (what is waiting), `SUCCESS_RULE.md` (how round 2 is judged), `DEMO.md` (booth demo run sheet), `VOICE_PIPELINE.md` (Voice, dropped from version 1), `archive/` (finished one-shot scripts, kept for history).
Main tools added since the first kit: `build_youtube.py`, `deezer_discover.py`, `boost_artists.sh`, `grow_more.sh` (pool growth); `tag_ai.py`, `mark_ai_out.py`, `ai_channels.py` (AI music); `find_official_versions.py`, `replace_songs.py`, `review_proposals.py`, `pool_duplicates.py`, `pool_summary.py` (pool quality);
`blind_test.py`, `build_friend_lists.py` (friends' lists and scoring); `recommend_song.py`, `demo_server.py` + `demo.html`, `make_demo_bundle.py` (recommendations and the demo).


# groovyeverywhere – first tests with Essentia's models (the original kit)

## Quick setup on a new machine (desktop)

1. **Windows only:** in PowerShell (admin) run `wsl --install -d Ubuntu`, restart, open **Ubuntu** from the Start menu and create a user.
2. Copy this zip into Ubuntu and unzip it (replace YOURNAME with your Windows user name):
   ```bash
   cp /mnt/c/Users/YOURNAME/Downloads/hidden-gems-tests.zip ~/ && cd ~ && unzip -o hidden-gems-tests.zip && cd hidden-gems-tests
   ```
3. Run the one-shot setup (installs everything, downloads the models, asks for your Jamendo ID, runs the self-check):
   ```bash
   bash setup.sh
   ```
4. Start the tests and leave them running (keep the PC awake and the Ubuntu window open):
   ```bash
   source .venv/bin/activate
   nohup python -u run_tests.py > run.log 2>&1 &
   tail -f run.log            # Ctrl+C stops watching, not the run
   ```
5. When the log ends with `finished`, run `python evaluate.py` and open the report with `explorer.exe report.html`.
6. Open **`songs_to_check.csv`** (written by the report): only the songs whose results contradict their label, with the reason. Listen to those, and put `n` in `edge_cases.csv` → `i_agree` where the label is wrong.

**Optional: reuse the laptop's 160 finished songs.** On the laptop, run `cd ~/hidden-gems-tests && zip -qr results.zip results && cp results.zip /mnt/c/Users/YOURNAME/Desktop/`, move `results.zip` to the desktop, and unzip it inside `hidden-gems-tests` on the desktop **before** step 4. Otherwise the desktop simply redoes them, which takes a few extra minutes.

**Same versions everywhere:** the laptop uses Python 3.14 and Essentia 2.1b6.dev1438. `requirements.txt` pins that build so both machines give identical numbers.

---

This kit answers the mentor's three questions with numbers instead of opinions:

1. **Whole song or 3 parts?** → test T5 (30-second clip test)
2. **Can the models tell happy-loud from sad-loud?** → tests T1, T2
3. **Do the features combine into real recommendations?** → tests T6, T8, T9

No audio is ever kept. Each song is downloaded into a temporary folder, analysed, and the folder is deleted. Only numbers are saved in `results/`.

## Files

| File | What it does |
|---|---|
| `edge_cases.csv` | 526 real Jamendo songs: 19 edge-case groups, 18 genre groups and a wide happy/sad sample (from the MTG-Jamendo **validation** split, so the test split stays untouched for the final score) |
| `select_edge_cases.py`, `expand_edge_cases.py` | How that list was picked (don't rerun: it would change the list) |
| `setup.sh` | One-shot setup for a new machine |
| `setup_db.sh`, `schema.sql`, `import_results.py`, `similar.py` | PostgreSQL + pgvector storage (stage 2) |
| `build_bigpass.py`, `build_pool.py` | Song lists for the big pass and the real pool |
| `train_mood.py`, `make_tap_list.py` | Our own mood model; the tap-along list for Rhythm |
| `export_catalogue.py` | `catalogue.csv`: every song used, with track id, title, artist, album, licence, link, popularity rank, use and status |
| `models.py` | Downloads the official Essentia models (~60 MB) |
| `analyze.py` | One song → Sound, Instruments, Mood, Rhythm numbers (whole song + 3 parts) |
| `sources.py` | Jamendo / Audius info + temporary download (downloadable tracks only) |
| `run_tests.py` | Analyses the edge-case songs. Resumable: stop and restart any time. |
| `evaluate.py` | Writes `report.html` with PASS / WARN / FAIL per test |
| `scoring.py` | The matching rules the app will use (percentiles, minimums, best part, …) |
| `synthetic_tests.py` | Checks that need no internet: rhythm on generated drums, trimming, scoring rules |

## Setup (laptop)

**Windows:** do everything inside WSL2 Ubuntu (`wsl --install -d Ubuntu`, then restart). Essentia's model package doesn't install on normal Windows.
**Mac with an M-series chip:** use Docker (`docker run -it -v "$PWD":/w -w /w python:3.11 bash`).
**Linux / Intel Mac:** works directly.

```bash
cd hidden-gems-tests
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python models.py                 # downloads the models
python synthetic_tests.py        # should end with "all scoring checks passed"
export JAMENDO_CLIENT_ID=xxxxxxxx   # free at https://devportal.jamendo.com
export AUDIUS_API_KEY=xxxxxxxx      # optional, https://api.audius.co/plans
```

## Run

```bash
python run_tests.py --limit 10          # first: 10 songs, check it works + see time per song
python run_tests.py                     # then all 160 (about 1–2 h on a laptop CPU; leave it running)
python run_tests.py --audius 3          # optional: 3 downloadable Audius songs per search
python evaluate.py                      # writes report.html
```

### The best first pair

[Japanese Girl](https://www.jamendo.com/track/959961) (tagged happy, energetic) and [Adore](https://www.jamendo.com/track/959962) (tagged sad) are by the same band, Respect Your Mom, from the same album, in the same grunge style. This pair is your mentor's question in two songs:

- **Sound** should call them close (same band, same style).
- **Mood** should put them apart on the sad-to-happy score.
- **Loudness** alone shouldn't separate them much.

Run the four mood groups first (32 songs, which include this pair):

```bash
python run_tests.py --groups mood_loud_happy mood_loud_sad_dark mood_quiet_happy mood_quiet_sad
python evaluate.py
```

### Before trusting the report: listen

The group labels come from crowd tags and are noisy. One "loud-sad" song is tagged *sad + uplifting*, for example. Open the `listen` link for each song in `edge_cases.csv`. If you disagree with its group, put `n` in the `i_agree` column, and `evaluate.py` will leave it out of that group's test. Start with the four `mood_*` groups, since they answer the mentor's question directly.

## What the tests check, and the pass bars

| Test | Pass when |
|---|---|
| T0 Full-length | ≥95% of downloads match the listed length ±3 s |
| T1 Mood | Happiness separates loud-happy from loud-sad ≥75% of the time, and beats plain loudness by ≥10 points |
| T2 Sound vs Mood | Sound keeps happy-classical and happy-electronic apart ≥85%; Mood keeps them within 0.6 happiness |
| T3 Instruments | Expected instrument in the top 3 for ≥70% of single-instrument songs; the 'voice' class detects singing ≥85% |
| T4 Rhythm | Beat confidence is lower for beatless songs ≥85% of the time |
| T5 Parts | Picks whichever of whole / parts / both finds a song from a 30 s clip most often |
| T6 Overlap | No two main features correlate above 0.6 (0.8 = basically the same thing) |
| T7 Same artist | Records Sound's hit rate: the number Voice must beat by 10 points |
| T8 Earn its place | Each added feature improves agreement on its own tags without hurting genre agreement |

A **FAIL** is a finding, not a broken script. Write it down; it changes the plan (e.g. "valence is weak → show Mood as energy only").

## Already checked without internet (`synthetic_tests.py`)

- A 174 BPM drum loop is detected as **87 BPM** and a 60 BPM loop as **120 BPM**. The half/double allowance is needed.
- A beatless pad still gets a made-up **112 BPM** with "steady" beats, but its confidence is **1.1** against 3.0–3.9 for real drums. So speed **and steadiness** are ignored when confidence is low. `scoring.py` now does this.
- Tempo drifting from 100 to 130 BPM shows up as higher steadiness (0.074 against 0.01 for steady loops).
- Scoring rules: one bad feature blocks a match; the best part is chosen after combining; an instrumental song isn't penalised when Voice is chosen; short lists aren't padded.

---

## Stage 2: database + big overnight pass

Run these on the desktop, in `~/hidden-gems-tests`, with `source .venv/bin/activate` first. Unzipping the new kit over the old folder keeps `results/`.

1. **Get the candidate models** (7 new ones, about 120 MB):
   `python models.py`
2. **Set up PostgreSQL and import the songs you already have** (asks for your Ubuntu password):
   `bash setup_db.sh`, then check it works with `python similar.py 959961`
3. **Build the song lists:**
   `python build_bigpass.py` makes `bigpass.csv`: about 1,500 validation songs to score, plus 800 training-split songs for our own mood model.
   `python build_pool.py` makes `pool_list.csv`: about 1,300 of today's Jamendo songs, balanced across 22 genres. This is the real pool.
4. **Overnight run** (keep the PC awake):
   ```bash
   nohup sh -c "python -u run_tests.py --upgrade && python -u run_tests.py --list bigpass.csv" > bigpass.log 2>&1 &
   ```
   `--upgrade` analyses the songs you already have again, this time with the candidate models (each one is downloaded again; no audio is kept). Expect roughly 10–12 hours in total. Run the pool the next night:
   `nohup python -u run_tests.py --list pool_list.csv > pool.log 2>&1 &`
5. **Then:**
   - `python train_mood.py` trains our own happy/sad model on the training songs only.
   - `python make_tap_list.py` makes `taps.csv`. Tap the speed of the 50 songs listed (about 1 minute each), or write `none` if there's no beat.
   - `python evaluate.py` adds T14 (which mood model is best) and T15 (which tempo method matches your taps, and which signal best spots "no beat").
   - `python import_results.py` copies everything new into PostgreSQL.
   - `python export_catalogue.py` writes `catalogue.csv`, the neat list of every song used.

**Pool with Audius:** `python build_pool.py` now also adds about 30 downloadable Audius songs per genre (22 genres), so rebuild `pool_list.csv` with the new version before the pool night. Audius songs with an artist-entered BPM (`bpm_custom = True`) also serve as extra true speeds for the Rhythm test.

After a PC restart, start the database again with `sudo service postgresql start`.

---

## Capture test (can the models recognise a captured song?)

**Rules first:** only capture from Jamendo or Audius pages. Spotify's User Guidelines forbid recording its content
and putting it into a machine learning model; YouTube's Terms forbid reproducing content except as YouTube allows.
The test server refuses any other site.

1. **Simulated capture damage, no listening needed** (about 20 minutes):
   `python robustness_test.py` re-downloads 100 analysed songs into a temporary folder, cuts 30 seconds, and
   damages the clip like a real capture would (quiet, compressed, phone speaker into a microphone, noisy room).
   It reports how often each version still finds its own song.
2. **Real captures in the browser:**
   `python capture_server.py`, then open http://localhost:8765 in Chrome or Edge on Windows.
   Play an analysed Jamendo song in another tab, type its track number, and capture 30 s of tab audio.
   Then try the microphone with the song playing from your phone. Do about 10 of each.
   `python capture_server.py --summary` shows the results. Audio is deleted straight after analysis.

## Are pool songs on Apple Music / Spotify?

`python check_platforms.py --limit 100` checks a sample (about 6 minutes), then `python check_platforms.py` for the
whole pool (about 75 minutes, resumable). Apple needs no account. For Spotify too, make a free app at
https://developer.spotify.com/dashboard and `export SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=...` first.
Only a search is made (no audio). A song counts as found only if artist, title and length all match.
`python check_platforms.py --summary` prints the share found, split by how obscure the songs are.

## Korean R&B and hip-hop (Audius)

`python build_pool.py --korean 100` searches Audius in English and Korean for downloadable Korean R&B and hip-hop
(up to 100 songs each, at most 2 per artist). A song is kept only if its title, artist, tags or description contain
Hangul or say Korean, because a search for "korean rnb" also returns plenty of non-Korean songs.
Then: `nohup python -u run_tests.py --list pool_korean.csv > pool_korean.log 2>&1 &`

## More songs from the same Audius artists

`python build_pool.py --expand-artists 8` looks up every Audius artist already in the pool lists and adds their
other downloadable songs (least played first), up to 8 songs per artist in total, into `pool_audius_more.csv`.
Recommendation lists still show at most 1 song per artist (`scoring.pick_hidden_gems(..., artists=...)`).

## Favourite instrument (user option)

The user can name one instrument they enjoy: piano, acoustic guitar, electric guitar, synth or strings (`python similar.py
--instruments`). Others were dropped after `instrument_check.py` showed the detector is too often wrong for them. It only re-orders the closest Sound matches: songs featuring it come first, or with `--only` (piano and acoustic
guitar only) the others are left out. It never pulls in a song that doesn't sound like the starting song.

```bash
python instrument_check.py                                  # first: how often "has piano" agrees with human labels
python similar.py "song title" --instrument piano           # try it
python similar.py "song title" --instrument piano --only
```

Why an option and not part of the match score: the detector finds the right instrument near the top for 78% of
single-instrument songs, but blended into the score it adds almost nothing (+0.004), because Sound already hears
instruments. Code: `scoring.INSTRUMENT_CHOICES`, `scoring.instrument_presence`, `pick_hidden_gems(favour=...)`.

## Free Music Archive (FMA) songs, same number per focus genre

FMA's own API is closed and its site may not be scraped, so we use the FMA research dataset (github.com/mdeff/fma):
106,574 full-length Creative Commons songs. Each song is read out of the online archive on its own, analysed in a
temporary folder and deleted; nothing but the metadata (about 20 MB) is kept.

```bash
pip install remotezip
python fma_pool.py --setup          # metadata only
python fma_pool.py --check          # reads 1 song to prove single-song reads work
python fma_pool.py --survey         # usable songs per focus genre
python fma_pool.py --per-genre 50   # +50 per focus genre (run again for 50 more each)
python -u run_tests.py --list pool_fma.csv
python pool_mix.py                  # see the genres grow together
```

## Are pool songs on YouTube?

`export YOUTUBE_API_KEY=...` (in ~/.bashrc), then `python check_youtube.py` once a day: the free key allows ~100
searches a day, so it checks a growing random sample (~95 songs/day) and prints how many are on YouTube, and how
many songs NOT on Apple/Spotify YouTube adds. Video links are deleted after 30 days (YouTube's storage rule).
In the app, a plain "Search on YouTube" link needs no key at all.

## Working on the laptop for a day

1. Copy the newest backup zip (C:\AI LODGE PROJ HIDDEN GEM BACKUP) to the laptop (USB stick or Google Drive).
2. On the laptop (WSL Ubuntu): unzip the kit, then `unzip -o <backup>.zip` inside ~/hidden-gems-tests (puts back
   results/, the lists, taps.csv, fma/), `python models.py` once. No database needed: everything falls back to results/.
3. Work: tapping, mic/cable checks, the blind test with friends, `check_youtube.py`, `check_platforms.py`.
4. End of day: `python carry.py --pack /mnt/c/Users/<you>/Downloads`, bring the small zip home, and on the desktop
   `python carry.py --unpack <zip>` (merges, never overwrites).

## Do the song links work? (`check_links.py`)

`python check_links.py` checks every pool song's own link once (Jamendo/Audius via their APIs, YouTube via oEmbed,
old FMA pages by opening them and looking for the song title) and, where it's broken, picks the best working
alternative: Apple Music / Spotify (from check_platforms.py), the song's YouTube video, or a YouTube search for
"artist title". Results in results/links.csv; blind-test sheets and catalogue.csv use the working link
automatically. `python check_links.py --fix-sheets` writes corrected copies of sheets already handed out.

## Where the data lives, and backups

- **PostgreSQL is the store the app uses.** Every analysis run now copies its new songs into the database by
  itself when it finishes (`import_results.py` still works by hand). The blind test and the capture page read
  from the database; if it is down they say so and use the files instead.
- **`results/` is the raw record** (one file per song, written all-or-nothing). The database can always be
  rebuilt from it, and the import only adds or updates, never deletes.
- **Backups:** `python backup.py --to /mnt/c/Users/NAME/OneDrive/HiddenGemsBackups` zips `results/`, the song lists,
  your hand-made files and a full database copy, checks every file, and copies it to Windows/OneDrive.
  To make every run back up by itself: `echo 'export HG_BACKUP_DIR=/mnt/c/Users/NAME/OneDrive/HiddenGemsBackups' >> ~/.bashrc`.
  How to restore: `RESTORE.txt` inside each backup.
