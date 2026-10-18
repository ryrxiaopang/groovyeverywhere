# Artists queued for the next pool expansion (added 11 Oct 2026)

Spotify artist links the user wants in the pool next time it is expanded. Not yet looked up: names and genres are unknown.
**On hold: the pool is frozen at about 9,000 songs for the hackathon demo (18 Oct 2026).** Run this on the desktop after the demo period.

| # | Spotify artist | Status |
| --- | --- | --- |
| 1 | https://open.spotify.com/artist/4MMQmzYiUiuD8VwjrJu3v6 | not looked up |
| 2 | https://open.spotify.com/artist/6QYehwA9q6UQEMs1Vak0uy | not looked up |
| 3 | https://open.spotify.com/artist/1sjw4xq2pAWy5Vdgba5QAt | not looked up |
| 4 | https://open.spotify.com/artist/6wMCLX99dfazjaH8QbnCrd | not looked up |
| 5 | https://open.spotify.com/artist/4BBN286rBKyCWsSPq2cxYO | not looked up |
| 6 | https://open.spotify.com/artist/4EKSBwzbRW2YnMP5JXnXYr | not looked up |
| 7 | https://open.spotify.com/artist/7zrkFhYAp6dBxsydmJkouN | not looked up |
| 8 | https://open.spotify.com/artist/58qX06UZpmeiapyjskI8sn | not looked up |
| 9 | https://open.spotify.com/artist/4dkCB7FJeRXK6OWpal7zpw | not looked up |
| 10 | https://open.spotify.com/artist/5gjVxMSvUPmjSPX95sl2Sr | not looked up |

## How to add them (when the pool is expanded)

1. Get the names and top tracks (every artist shows as `[pop]` for now, only a placeholder):
   `python spotify_artists.py spotify_artists10.json <the ten ids>`
2. Choose a pool genre for each (see the thin spots in `python pool_summary.py`; genres: indie, indiepop, indierock, altrock, alternative, pop, rnb, singer, indiefolk, electro, hiphop, rock ...)
   and rerun with `ID@genre` after each id.
3. `nohup bash boost_artists.sh spotify_artists10.json > boost_artists10.log 2>&1 &` (about 35 songs per artist, about 15 s of analysis each; never two analyses at once).
4. Afterwards: `python pool_summary.py`, `python pool_duplicates.py`, `python find_official_versions.py`.

Do not expand the pool between building a round's lists and scoring it if the Sound scale matters for a comparison with that round's lists; scoring itself does not read the pool.
