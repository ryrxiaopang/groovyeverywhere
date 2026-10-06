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
  -> `voice_dev.csv` (811 train-split songs: 140 artists + 420 distractors). Overnight 7 Oct: `voice_dev.csv` run queued after the
  YouTube analysis (`start_voice_dev.sh` in /tmp), then `grow_pool_overnight.sh` (YouTube genres + analysis). NEXT: development
  analysis script (pick model 1 of 5, stem vs mix, window averaging, rescaling, singing gate; ALL on train songs), write
  `voice_freeze.json`, top up the test list, run `run_voice.py --list` on it, score once. Still missing: offline deletion test for
  `analyze_voice.py` (fake separator is built in via `FAKE_VOICE=1`), adding `voice` to `blind_test.FEATURES`.
  Two sealed-test songs were put through Voice for timing only (no scores looked at).

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
