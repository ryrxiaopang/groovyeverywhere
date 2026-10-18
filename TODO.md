# To-do (updated 18 Oct 2026, after the hackathon submission)

Read CLAUDE.md first, starting with its "START HERE" section: it has the state of the project, the decisions already made and the ordered list of what is waiting.
Keep the core rules: no audio is ever kept, the MTG test split is sealed, never run two analysis runs at once, pass marks are set before looking.
Run the offline tests after every change and finish each task with a short plain-language summary of what changed and any numbers measured.

## Now
1. Keep the public demo alive until finalists are picked (desktop on; restart `demo_server.py` after a code update, the tunnel keeps its address; if cloudflared restarts, update `LIVE` in `docs/index.html`).
2. After this update, on the desktop: `python song_languages.py` (the labelling rules changed on 18 Oct), then restart the demo server.
3. Booth laptop: a new bundle from the desktop (`make_demo_bundle.py`), then on the laptop deno, `pip install -U "yt-dlp[default]"`, unzip, `python demo_server.py --check`, `--rehearse links.txt`.

## Decided (18 Oct)
- Round 2 of the friends' blind test is **not scored** (the ratings did not come back); no claim is made about it. If ratings ever arrive, score them against `SUCCESS_RULE.md` and say the lists were built with the old AI policy.
- The pool stays frozen at about 9,000 songs for the demo.

## Later (optional)
- More Japanese indie / rock / rap and folk artists; `pending_artists.md` (queued before the freeze).
- Covers and fan lyric videos -> the artist's own upload (`find_official_versions.py`).
- Calibrate the weak-match threshold from `results/demo_log.csv`.
- Rhythm: finish tapping (11 of 50) and decide its role (weak / optional).
- Re-run the AI-tagger check on a fresh sample if the tagger is retuned (the first 99 songs must not be reused to validate a new rule).
- Housekeeping: merge the two link checkers, `similar.py` on the rescaled Sound, optional `psycopg` + database setup; update the Project Guide and Evidence Report docs.

## Done (recent)
- Hackathon submission (18 Oct): Devpost story, demo video, public link (GitHub Pages -> Cloudflare tunnel -> desktop), README rewrite, licence and credits.
- Review fixes (18 Oct): demo (results kept for chip changes, chips never wait for another analysis, artist's other names left out, odd requests answered), language labels, sealed-test guard in `evaluate.py`, AI block list for untagged songs.
- Language filter, AI channel block list from the user's names, pool growth to about 9,000 songs (16 Oct).
- Round 2 design: YouTube-only pool, best match first, lists A/B/C/D, no repeats, success rule written before sending, friend-resampled ranges.
