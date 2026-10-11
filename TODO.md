# To-do (updated 11 Oct 2026)

Read CLAUDE.md first, starting with its "START HERE" section: it has the state of the project, the decisions already made and the ordered list of what is waiting.
Keep the core rules: no audio is ever kept, the MTG test split is sealed, never run two analysis runs at once, pass marks are set before looking.
Run the offline tests after every change and finish each task with a short plain-language summary of what changed and any numbers measured.

## Waiting on the user's machine (details and commands in CLAUDE.md > START HERE > Pending)
1. Round-2 ratings from five friends, then `python blind_test.py --score <round-2 sheets>` against `SUCCESS_RULE.md`.
2. AI channels: `ai_channels.py --from-sheet ai_check_sheet.csv` (preview, then `--write`), confirm other SEO-style AI channels for `ai_block.txt`.
3. Six replacements from the listening-sheet comments: `replace_songs.py ai_check_sheet.csv` (preview, then `--apply`).
4. Covers and fan lyric videos -> the artist's own upload: `find_official_versions.py --search --limit 50 --deezer --explain 12`, review, approve, `replace_songs.py --proposals ...`.
5. One analysis run (`run_tests.py --list pool_youtube.csv`), then `pool_duplicates.py` (`--apply` before round 3).
6. `pending_artists.md`: 10 queued Spotify artists for the next pool expansion.

## Next (for a coding session)
- After round 2 is scored: update the Project Guide doc and the Evidence Report; decide round 3 (more indie rock / alternative rock / singer-songwriter; list sizes; whether list D stays).
- Re-run the AI-tagger check on a fresh sample if the tagger is retuned (the first 99 songs must not be reused to validate a new rule).
- Rhythm: finish tapping (11 of 50) and decide its role (weak / optional).
- Housekeeping: README refresh, merge the two link checkers, `similar.py` on the rescaled Sound, optional `psycopg` + database setup.

## Done (recent)
- Round 2 design: YouTube-only pool, best match first, lists A/B/C/D, no repeats, success rule written before sending, friend-resampled ranges, Sound scale fitted on the YouTube pool.
- Pool growth: 33 Spotify artists, 60 Deezer-discovered artists (`deezer_discover.py`), pool tools (`pool_summary.py`, `pool_duplicates.py`).
- AI music: tagger check (`ai_tag_check.py`), policy `hide` by default, `ai_keep.txt` / `ai_block.txt`, `ai_channels.py`.
- Official versions: `find_official_versions.py` + `replace_songs.py` (two real batches run and fixed).
