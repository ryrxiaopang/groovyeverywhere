# groovyeverywhere (a.k.a. Hidden Gems): project guide for Claude Code

A music **recommendation** research project. It analyses songs with Essentia models (Sound, Mood, Rhythm, Instruments),
stores only numbers, and recommends "hidden gems": good matches that few people have played. `README.md` has the full
story and the mentor's three questions; `TODO.md` the task list; `VOICE_PIPELINE.md` the design for the Voice feature.
The project's own written report is a claude.ai doc, "groovyeverywhere: Evidence Report"
(https://claude.ai/artifact/GpjFC3gVZ6sMvqBKNY15dJ; read it only with the docs connector / Artifact tool, never WebFetch).
Last updated 7 Oct 2026.

## Rules that must never be broken
1. **No audio is ever kept.** Every download goes through `sources.temp_audio()` (a `TemporaryDirectory`); only numbers are
   stored. Stems or caches of audio are forbidden too. `synthetic_tests.py` section 5 proves deletion for every source;
   `sources.sweep_stale_temp()` removes folders left by a killed run.
2. **The MTG-Jamendo TEST split is sealed.** It was scored once (6 Oct, see below). Never tune a model, threshold or pass mark
   on test songs; never put test songs in the pool (their group names are not `pool_*`/`yt_*`). `test_split_freeze.json` holds
   the code fingerprint, the amendment record and the copy of the Sound scale used (`results/sound_scale_official_test.npz`).
3. **Pass marks are set before looking** (README table). Report failures as failures. Disclose any defect or re-run.
4. **Never run two `run_tests.py` at once**: they share `results/index.csv` (append-only) and temp file names.
5. Do not commit data (`results/`, models, `pool_*.csv`, logs; see `.gitignore`). `test_split.csv`, `underrated_*.csv`,
   `test_split_freeze.json` ARE committed on purpose.

## Environment (Windows desktop, work happens in WSL Ubuntu)
* Repo: `~/groovyeverywhere` in WSL (git branch `hidden-gems-kit`, local commits only, not pushed). The older big-data
  folder `~/hidden-gems-tests` is a copy of the original kit; its results were MERGED into this repo's `results/`.
* Edit WSL files from Windows with the editor tools at `\\wsl.localhost\Ubuntu\home\xiaopang\groovyeverywhere\...`.
  Run commands with `wsl -e bash -c '...'` and `source .venv/bin/activate`. Use `bash -ic` when a key from `~/.bashrc`
  is needed (`JAMENDO_CLIENT_ID`, `YOUTUBE_API_KEY`; never print them). A non-interactive shell does NOT load `.bashrc`.
* **Quoting pitfall:** apostrophes, `$`, nested quotes inside `bash -c '...'` / PowerShell break commands and heredocs.
  Put multi-line Python in a script file (the scratchpad dir, run via `wsl -e python3 /mnt/c/...` from PowerShell, or
  the Bash tool) instead of inline heredocs. `pkill -f`/`pgrep -f` can match their own shell: use `[x]` patterns.
* Python 3.14 venv `.venv`, `essentia-tensorflow` (no Windows wheel). `psycopg`/`pgvector` are NOT installed, so PostgreSQL
  import fails harmlessly; all code falls back to `results/` files. Hardware: 16 cores, 15 GB RAM, RTX 5070 (visible in WSL).
* git commits: pass identity per command (`git -c user.name=ryrxiaopang -c user.email=ryanchan3007@gmail.com commit -F file`),
  write long messages to a file (shell quoting). End messages with the Co-Authored-By line.
* After every analysis run `run_tests.py` makes a backup (~5 GB) into `HG_BACKUP_DIR` (the Windows project folder),
  keeping only the newest 2 zips there.

## Pipeline and file map
* **Pool lists** (`pool_*.csv`, hand-editable; `i_agree = n` removes a song from the pool, it stays stored):
  `build_pool.py` (Jamendo/Audius), `fma_pool.py`, `build_youtube.py` (YouTube via the Data API), `build_underrated.py`
  (see below). `results_index.pool_keys()` is the single definition of "the pool"; `OFF_POOL_GENRES` leaves out punk, latin,
  funk, classical, soundtrack (user decision: keep mainstream genres; ask if unsure about a genre).
* **Analysis:** `python -u run_tests.py --list <list.csv>` (resumable; one song at a time; `analyze.py` -> `results/<key>.npz`
  + `results/index.csv`). Keys are `jamendo_ID`, `fma_ID`, `audius_ID`, `youtube_VIDEOID`.
* **Scoring:** `scoring.py` (percentiles, `combine` = best part chosen AFTER combining features, every chosen feature >= 65%,
  `pick_hidden_gems`, `least_played` quality guard that skips the least-played 10% of each site). `blind_test.py` builds the
  friends' blind-test lists (A Sound only, B Sound + chosen feature, C random same genre). `match.py` clip/library matching.
* **Sound similarity:** cosine on EffNet embeddings AFTER a gentle rescaling: subtract the pool mean, divide by spread^0.25
  (`scoring.SOUND_SPREAD_POWER`, `match.sound_scale()`, cached in `results/sound_scale.npz`). Full z-score fails the 85%
  style pass mark; plain cosine is the baseline. `metric_check.py` is the metric comparison.
* **Evaluation:** `python evaluate.py --split validation|test|all` -> `report_*.html`, `evidence_summary_*.json`.
  `--split test` is the sealed score: do not run it again without saying so.
* **Mood:** the chosen model is VGGish -> emoMusic (user decision 6 Oct; do not reopen unless asked). Per-part mood uses the
  original MusiCNN model because only it has parts.
* Other scripts: `similar.py` (database demo, still PLAIN cosine), `capture_server.py` (tap page, mic capture; mic input is a
  known weak point), `check_youtube.py`, `check_platforms.py`, `pool_mix.py`, `export_catalogue.py`, `backup.py`, `carry.py`,
  `gem_guard_check.py`, `select_test_split.py`, `check_youtube_quality.py`.

## State of the work (7 Oct 2026)
* Analysed songs: 8,185 (Jamendo 5,345, FMA 2,167, Audius 282, YouTube 391). Pool: 4,568 songs, 66% with singing.
* **Official test (6 Oct):** 1,143 sealed test songs (of 1,686 listed; 498 gone from Jamendo, 45 not downloadable), 16 checks
  pass, 3 fail (Sound "styles apart" 65% vs 85% bar: only 5 happy-classical songs, plain cosine scores the same; both beat-
  detection checks 64-67% vs 85%), 6 warn, 2 skipped. The FIRST scoring run was defective (634 of 1,143 songs: zero-padded ids
  and tags read from the validation file only); fixed, disclosed, kept as `*_run1_defective.*`. Baseline for Voice: Sound finds
  a same-artist song on ANOTHER album in the top 10 for 29% of questions (28% on the full library).
* **YouTube pool growth is in progress.** `pool_youtube.csv` has ~748 rows, 101 marked `n`; ~323 are still pending analysis.
  If `run_tests.py --list pool_youtube.csv` is not running, restart it (it skips finished songs):
  `bash -ic 'cd ~/groovyeverywhere && source .venv/bin/activate && nohup python -u run_tests.py --list pool_youtube.csv > pool_youtube4.log 2>&1 &'`
  (~16 s per song; WSL shutting down stops it). New songs appear in the list after each `build_youtube.py` /
  `build_underrated.py --add`, so run it again afterwards.
* **YouTube quality:** about 38% of early titles were not songs (tutorials, playlists, covers, type beats, lessons). The filter is
  `build_youtube.NOT_A_SONG` (regex; extend it when new junk appears, then run `mark_*`-style marking of matching rows to `n`).
  The user has permission for YouTube terms: do not raise them again.
* **Underrated-artist search:** `underrated_artists.csv` (genre, artist, hint, source, why, channel_url) holds 120+ artists from web
  lists plus the user's own playlist (genre `playlist`, kept whole, matched STRICTLY: own channel or "Name - Song" title,
  aliases in `build_underrated.ALIASES`, or a `channel_url` the user supplied). `python -u build_underrated.py [--genres ..] [--add]`
  uses `yt-dlp` search (no API quota), keeps artists with a channel under 1M followers (artist's OWN channel only: label channels
  are ignored) and songs under 5M views, ranks by smoothed like rate, top 10 per genre, up to 3 songs each.
  `underrated_selected.csv` = who was chosen and why. Cache: `results/underrated_cache.json`. Still unmatched from the user's list:
  SHIRT (and chilloop's channel has only short clips): ask for YouTube links. Worth extending to metal/jazz/folk/reggae/blues/country/world.
* `check_youtube_quality.py` writes red-flag reports and listening sheets (`--selected` = from the underrated selection); the user
  was given `youtube_listen_sheet_underrated.csv` (30 songs) to fill in; `--score` summarises it.
* **Voice feature:** design only (`VOICE_PIPELINE.md`). Primary question (user decision): Sound + Voice vs Sound alone, as an extra
  filter like the other features; Demucs (GPU) + the five Sony singer-identity models; develop on TRAIN-split same-artist songs,
  freeze, then score once on the sealed test split with extra same-artist test songs (user agreed to top up the test list with a
  fixed seed). Needs about 250 questions for 90% power.
  **Built 7 Oct:** GPU env `.venv-voice` (Python 3.12, torch 2.11+cu128, demucs, Sony models cloned and patched in `~/ssl-singer-identity`;
  the 'uniformity' model is `unif-align` on Hugging Face). Demucs ~3-5 s per song on the RTX 5070. `analyze_voice.py` (one song,
  in memory) + `run_voice.py --list` (resumable, writes `results/voice/<key>.npz`, run with `.venv-voice`), `select_voice_dev.py`
  -> `voice_dev.csv` (811 train-split songs: 140 artists + 420 distractors). 7 Oct: `run_voice.py --list voice_dev.csv` runs in `.venv-voice` (start with `bash -ic` or `source env_keys.sh`: a
  non-interactive bash has no API keys, which is what stopped the first overnight run). `after_voice.sh` then runs
  `voice_dev_analysis.py` (Voice alone: model, stem vs mix, window mean, rescaling, singing gate -> `voice_dev_report.md`,
  `voice_dev_choice.json`), analyses Sound for the dev songs with `run_tests.py --list voice_dev.csv`, and repeats the analysis with
  `--with-sound` (dry run of the test: Sound alone vs Sound + Voice, paired gain). NEXT: read the report, write `voice_freeze.json`,
  top up the test list, run `run_voice.py --list` on it, score once (`voice_test.py`, not written yet).
  **Unattended-run rules (learned the hard way, 7 Oct):** scripts that run unattended must `source env_keys.sh` + `need_keys`; save
  results after EVERY step (`build_youtube.py` writes `pool_youtube.csv` after each search and remembers finished searches in
  `results/youtube_queries_done.json`; it stops cleanly on a 429 or the daily quota, which resets at 15:00 UTC+8);
  `run_voice.py` stops after 5 failed songs in a row; `synthetic_tests.py` section 7 replays these failures offline. Never `pkill -f`
  a pattern that also appears in your own command line (it kills your shell); use script files, not long `bash -c` strings.
  `grow_pool_overnight.sh [HH:MM]` = variety search (`build_youtube.py --variety`, extra sub-style queries inside the EXISTING
  genres only) + analysis, optionally not before HH:MM. Still missing: offline deletion test for
  `analyze_voice.py` (fake separator is built in via `FAKE_VOICE=1`), adding `voice` to `blind_test.FEATURES`.
  Two sealed-test songs were put through Voice for timing only (no scores looked at).

## Friends' blind test: inputs (7 Oct 2026)
* `friends_inputs.csv` = what each friend said (Felicia 3 songs, Isaac 3, Weiyang 2, Xing You 3) with `proposed_feature_for_list_B`
  (my guess from their words; column `confirmed` is for the user to fill: mood / rhythm / instruments / sound, joined by +).
  `friends_songs.csv` = the 10 unique YouTube videos (official uploads, picked by yt-dlp search), group `friend_song`, NOT in the pool.
  Analysed 9 of 10 (`analyse_friends_songs.sh`). **peoplepleaser (whotfisarya, QEPr2GOWbJU) fails with YouTube 403 on every yt-dlp client:**
  needs a mic capture (`capture_server.py`), a retry later, or another song from Felicia.
* Voice was dropped from version 1 (dry run on dev songs: Sound + Voice gains +2.8 points, 95% range -5.1 to +10.8, bar is +10;
  see `voice_dev_report.md`); sealed test NOT spent on it. Features for list B: sound, mood, rhythm, instruments.
* Sample website UI: `blind_listen_sample.html` (published as an artifact "groovyeverywhere"); not yet wired to `blind_test.py`.

## Scope change (7 Oct 2026): not only hidden gems
The user decided the pool may contain songs that used to be popular and are less known to younger listeners; the project does
NOT have to stay strict to hidden gems / obscurity. So: `recommend_song.py` ranks best match first by default (`--rank obscure`
keeps the old rule), `build_youtube.py --ytdlp --relevance` takes songs in YouTube's order up to 20M views,
`build_from_spotify.py` adds whole playlists (verified YouTube matches). The BLIND TEST lists still use `pick_hidden_gems`
(changing them would break comparability with the sheets already made); decide before round 2 whether they should change too.
Pool quality audits (7 Oct): ~75 non-songs excluded by hand (news, recaps, reviews, listicles, "guess the song" games, karaoke,
type beats, test uploads, ads); `NOT_A_SONG` is now much stricter. Re-run an audit after every big pool addition: titles with
top N / best / guess / quiz / review / recap / news / compilation / playlist, and channel names with news / radio / tv.
Queued after the pool analysis (each waits for the previous): `style_boost.sh` (Japanese soul / piano pop / city pop inside jpop,
jrnb, citypop, singer, rnb), then `spotify_boost.sh` (4 playlists + 1 artist page in `spotify_tracks.json` + Ruel, jupiterkid,
2hollis). Spotify playlists are read from the public embed pages (first 50-100 tracks only, no login or key needed).

## Open work, in order
1. Let the YouTube analysis finish (restart if stopped); optionally run another `build_youtube.py` / `build_underrated.py` round.
2. Voice: environment + Demucs benchmark, then the steps in `VOICE_PIPELINE.md` section 7.
3. Rhythm: the beat-detection checks fail on validation and test. Busyness as the "is there a beat?" signal won on test (0.78 vs 0.66)
   but NOT clearly on validation (0.754 vs 0.733, n=64), so the switch was NOT made (test numbers must not drive choices). Rhythm
   stays the least validated model: finish tapping 50 songs (11 done) to choose the speed method; present it as weak/optional.
4. Friends' blind listening test (after the Voice decision), then the user test; pool freeze as "version 1".
5. Housekeeping: switch `similar.py` to the rescaled Sound; install `psycopg` + `bash setup_db.sh` if the database is wanted;
   re-run `check_platforms.py` when Spotify's limit resets; keep the Evidence Report doc in step with new results.

## Conventions
Plain-language explanations for the user (no jargon without a gloss); numbers with their 95% range; say what was NOT verified.
Keep `python synthetic_tests.py` green after every change (it is the offline self-check). Commit small, descriptive commits.
