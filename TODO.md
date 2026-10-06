# To-do for Claude Code (in priority order, updated 7 Oct 2026)

Read CLAUDE.md first. Keep its core rules: no audio is ever kept, the MTG test split is sealed, never run two analysis runs at
once. Do one task at a time, run `python synthetic_tests.py` after each, and finish each with a short plain-language summary of
what changed and any numbers measured.

## Done
- [x] Blind test: best part chosen AFTER combining features (`blind_test.pair_similarities`, one score per part).
- [x] Hidden-gem quality guard (`scoring.least_played`, skips the least-played 10% of each site; FMA favourites need >= 3).
- [x] Offline tests for the newer code are partly in place (`synthetic_tests.py` sections 3b-6: rescaling, blind pairing, audio
      deletion, carry.py zip guard, key redaction, split ids). Still missing: `instrument_presence` / `instrument_somewhere`,
      `match.rank(method="windows")`, `carry.py` pack/unpack merge, `run_tests.done_keys` retry cap.
- [x] Sound rescaling adopted (spread^0.25), official test-split score done (see CLAUDE.md), YouTube + underrated-artist pool growth.

## Next
1. **Finish the YouTube analysis** (`run_tests.py --list pool_youtube.csv`, resumable) and keep growing the pool with
   `build_youtube.py` / `build_underrated.py --add` (more genres: metal, jazz, folk, reggae, blues, country, world). Ask the
   user for YouTube links for artists that could not be matched (SHIRT).
2. **Voice: build it or drop it** with the test in `VOICE_PIPELINE.md` (Sound + Voice vs Sound alone; baseline 29%; ~250 questions).
   Awaiting the user's OK for the GPU environment.
3. **Rhythm:** switch the "is there a beat?" signal to busyness; finish tapping (11 of 50) and run T15.
4. **Missing offline tests** (list above), `similar.py` on the rescaled Sound, optional `psycopg` + database setup.
5. After Voice: friends' blind test (`capture_server.py` + `blind_test.py`), user test, freeze the pool as version 1, update the
   Evidence Report doc.

## Runs the user does himself or herself (no code needed)
- Fill in `youtube_listen_sheet_underrated.csv`, then `python check_youtube_quality.py --score`.
- Finish tapping (http://localhost:8765/tap after `python capture_server.py`), then `python evaluate.py --split validation`.
- After big changes: `python pool_mix.py` (needs the database), `python export_catalogue.py`, `python backup.py --to "$HG_BACKUP_DIR"`.
