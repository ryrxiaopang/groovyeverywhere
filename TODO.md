# To-do for Claude Code (in priority order)

Read CLAUDE.md first. Keep its core rule: no audio is ever kept, only numbers. Do one task at a time, run `python synthetic_tests.py`
after each, and finish each with a short plain-language summary of what changed and any numbers measured.

## 1. Blind test: choose the best part AFTER combining features
`blind_test.similarities` uses the best part (or 30 s window) for Sound only, while Mood/Rhythm/Instruments use the
whole song. Build one dict per part (effnet_parts, instruments_parts, mood parts) plus a whole-song dict and let
`scoring.combine` pick the best pair, as scoring.py's docstring says.
Done when: a synthetic test in synthetic_tests.py shows a song whose sound matches part 1 but mood matches part 3
is NOT scored as if both matched the same part.

## 2. Hidden-gem quality guard
`scoring.pick_hidden_gems` sorts good matches least-played first, so the very least-played (often roughest)
uploads win. Add an option to skip the bottom N% of plays within each source (default 10%) and, for FMA songs,
optionally use favourites/plays. Measure with evaluate.py that match quality doesn't drop.

## 3. Voice feature: build or drop
The plan promises a Voice feature (Demucs vocal separation + a voice model) that was never built. Either build
the A/B test described in the plan doc (30 same-artist pairs; keep only if it beats Sound by 10 points) or remove
it from README/plan with the reason. Ask George which.

## 4. Tests for newer code
Add offline checks to synthetic_tests.py for: scoring.instrument_presence / instrument_somewhere,
match.rank(method="windows"), carry.py pack/unpack merge, run_tests.done_keys
retry cap. No network, no audio files kept.

## Runs George does himself (no code needed)
- Nightly FMA round: `python fma_pool.py --sung 100` then `nohup python -u run_tests.py --list pool_fma.csv > fma.log 2>&1 &`
- Daily: `python check_youtube.py` (until ~300 songs sampled); `python check_platforms.py` (Spotify for FMA songs)
- Finish tapping (http://localhost:8765/tap), then `python evaluate.py`
- After big changes: `python pool_mix.py`, `python evaluate.py`, `python export_catalogue.py`, `python backup.py --to "$HG_BACKUP_DIR"`
