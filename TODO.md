# To-do for Claude Code (in priority order)

Read CLAUDE.md first. Keep its core rule: no audio is ever kept, only numbers. Do one task at a time, run `python synthetic_tests.py`
after each, and finish each with a short plain-language summary of what changed and any numbers measured.

## 1. Cable input for starting songs (needed before the friend test)
The robustness test showed a phone played out loud into a microphone is unusable (shares 7% of the real song's
20 nearest songs vs 68% for a clean clip), so friends will connect their phone by cable.
- In `capture.html`, add an input-device picker (navigator.mediaDevices.enumerateDevices) and a live level meter,
  and a "Cable / line-in" method that records with echoCancellation, noiseSuppression and autoGainControl OFF.
- Warn on screen when the recording clips (peaks at maximum) or is very quiet.
- In `robustness_test.py`, add a "cable" condition (clean clip, -10 dB, small hiss at 40 dB SNR, then volume
  levelling) so we know what to expect.
Done when: the page lets George pick "Line In", shows the level moving, and the cable condition is in the table.

## 2. Blind test: choose the best part AFTER combining features
`blind_test.similarities` uses the best part (or 30 s window) for Sound only, while Mood/Rhythm/Instruments use the
whole song. Build one dict per part (effnet_parts, instruments_parts, mood parts) plus a whole-song dict and let
`scoring.combine` pick the best pair, as scoring.py's docstring says.
Done when: a synthetic test in synthetic_tests.py shows a song whose sound matches part 1 but mood matches part 3
is NOT scored as if both matched the same part.

## 3. Hidden-gem quality guard
`scoring.pick_hidden_gems` sorts good matches least-played first, so the very least-played (often roughest)
uploads win. Add an option to skip the bottom N% of plays within each source (default 10%) and, for FMA songs,
optionally use favourites/plays. Measure with evaluate.py that match quality doesn't drop.

## 4. Learned "mic/cable to clean" correction (research)
Using the damage functions in robustness_test.py, build pairs (damaged clip embedding, clean clip embedding) for
~300 songs (several random clips each), fit a ridge regression (or a small linear map in a PCA-128 space), and
test on HELD-OUT songs: does neighbour overlap for "phone mic" rise from ~7%? Report honestly; keep it only if it
clearly helps on held-out songs. Save the map as numbers (no audio).

## 5. Keep the capture server's pool fresh
`match.library()` and `blind_test.pool()` load once per process. Reload when results/index.csv or any pool list
changes (check modification times on each request), so new songs and i_agree = n marks count without a restart.

## 6. Voice feature: build or drop
The plan promises a Voice feature (Demucs vocal separation + a voice model) that was never built. Either build
the A/B test described in the plan doc (30 same-artist pairs; keep only if it beats Sound by 10 points) or remove
it from README/plan with the reason. Ask George which.

## 7. Tests for newer code
Add offline checks to synthetic_tests.py for: scoring.instrument_presence / instrument_somewhere,
match.rank(method="windows"), capture_server.even_out_volume, carry.py pack/unpack merge, run_tests.done_keys
retry cap. No network, no audio files kept.

## Runs George does himself (no code needed)
- Nightly FMA round: `python fma_pool.py --sung 100` then `nohup python -u run_tests.py --list pool_fma.csv > fma.log 2>&1 &`
- Daily: `python check_youtube.py` (until ~300 songs sampled); `python check_platforms.py` (Spotify for FMA songs)
- Finish tapping (http://localhost:8765/tap), then `python evaluate.py`
- After big changes: `python pool_mix.py`, `python evaluate.py`, `python export_catalogue.py`, `python backup.py --to "$HG_BACKUP_DIR"`
