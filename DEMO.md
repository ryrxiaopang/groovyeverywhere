# Demo day: run sheet

The demo is a small website that runs **on your laptop only**. A visitor sits at your laptop, pastes a YouTube link, and gets similar songs from the pool.
Built 12 Oct 2026 (`demo_server.py` + `demo.html`); tested offline with a fake backend and in a browser, **not yet run with the real models: rehearse it** (section 2).

## 1. What it does (and the three ways a song gets in)

| Way in | What happens | Time | Needs internet |
| --- | --- | --- | --- |
| **Paste a YouTube link** (main) | looks up the video, downloads the audio with yt-dlp, analyses it with the same models as the pool, finds matches. Audio is deleted at once. | about 30 s (measure it, section 2) | yes |
| **Capture a browser tab** (Plan B) | if YouTube blocks the download, the page offers it: the song plays in another Chrome tab, the page records 30 s of that tab's audio and analyses that | about 60 s | yes (to play the song) |
| **Try a sample song** (Plan C) | a song that is already analysed in the pool: instant | 2-5 s | no |

Two lists come back, as in the friends' test: **closest in sound**, and **sound plus the features you tick** (mood / rhythm / instruments, each in the top 35%).
Each match shows the % match, the four scores, a play button (embedded YouTube) and "would add" / "skip" buttons. Answers go to `results/demo_feedback.csv`; every run to `results/demo_log.csv`.

## 2. A week before: get ready and rehearse

1. `git pull origin claude/brave-rubin-xs7hbb`, finish all analysis and pool-growing jobs, run `python pool_duplicates.py --apply`, **freeze the pool**. (A changed pool changes the results the audience sees.)
2. `source .venv/bin/activate && source env_keys.sh && python -m pip install -U yt-dlp` (an old yt-dlp is the most common reason for a blocked download).
3. Start it: `python demo_server.py`. It prints a warning if an analysis job is still running. Open **http://localhost:8765** in Chrome on Windows. The light at the top turns green ("ready · N songs") after about a minute.
   * If Chrome cannot open `localhost`: in WSL run `hostname -I` and open `http://THAT-ADDRESS:8765`, and start the server with `--host 0.0.0.0`.
4. Rehearse with **at least 10 links**: different genres, languages, an old song, a very new one, one that is long, one that is not in English, one that is NOT in the pool's styles (to see how it fails). Then `python demo_server.py --summary` shows the median seconds per stage and what failed. Write the real numbers on your run sheet.
5. **Choose the sample songs** (Plan C): put 6 songs in `demo_samples.csv` (columns `key,title,artist`, keys like `youtube_XXXXXXXXXXX` from the pool) whose recommendations you have listened to and like. Without the file the page uses the most-viewed song of the six biggest styles. Say out loud that samples are chosen, not random.
6. **Record a backup video** (screen recording, 2 minutes) of a clean run. If everything fails you still have something to show.
7. If YouTube blocks downloads on the venue Wi-Fi: export a `cookies.txt` from a browser that is signed in to YouTube and start with `HG_YT_COOKIES_FILE=/path/cookies.txt python demo_server.py`. Test it at home first.
8. Test the tab capture once: open a song in another tab, press "capture a browser tab instead", choose that tab, tick "Also share tab audio".

## 3. On the day: 30 minutes before

- [ ] Laptop plugged in; sleep and screen-off set to "never" (Windows power settings); notifications off; other apps closed.
- [ ] No analysis or boost job running: `pgrep -af "[r]un_tests|[b]oost"` prints nothing (they make the demo slow).
- [ ] Open the WSL window and **leave it open** (closing it stops the server). `python demo_server.py`, wait for the green light.
- [ ] Chrome full screen on the page. Test: one sample (instant), then one real link (time it).
- [ ] Sound out of the laptop works (the play buttons use embedded YouTube, which needs internet).
- [ ] Phone hotspot ready as a second internet connection.
- [ ] The backup video is on the desktop; the sample list is the one you chose.

## 4. Run of show (about 7 minutes; the audience tries it at the laptop)

1. **30 s, the idea.** "Give it a song you love. It finds songs in our pool that sound alike, so you discover music you would not have searched for."
2. **90 s, live link.** Paste a link (yours, picked beforehand). While the stage text runs ("downloading", "listening", "finding matches") say what happens: it turns the song into numbers for the sound, mood, beat and instruments; the audio is deleted straight away; only the numbers are kept.
3. **90 s, read the results.** Left: closest in sound. Right: sound plus the features. Untick "the rhythm" to show the list change. Play one match. Press "would add" on one.
4. **2-3 min, the audience.** Someone pastes their own song. This is the real test: ask "would you add this to a playlist?" and tick it for them.
5. **60 s, the evidence.** What the friends' rounds showed (fill in with the round-2 verdicts from `blind_test.py --score`), and what was NOT shown (see section 6).

## 5. When something goes wrong

| What you see | Why | What to do |
| --- | --- | --- |
| "YouTube blocked the download" + a yellow Plan B box | YouTube returned 403 (it blocked 4 of 23 downloads on 11 Oct) | press **start the 30-second capture**, pick the tab with the song playing, tick "Also share tab audio" |
| "The recording was (almost) silent" | the audio box was not ticked, or the tab was muted | repeat; make sure the song is audible in that tab |
| "Another song is being analysed" | one request at a time | wait 20 s |
| Light stays orange / "pool did not load" | the pool or models failed to load | look at the WSL window for the error; restart `python demo_server.py` (about a minute); meanwhile show the backup video |
| "That video is N minutes long" | a mix or a live stream | pick a single song |
| No thumbnails, play buttons do nothing | no internet | the matches are still right; use the "open on YouTube" links later; samples still work |
| Matches look odd for a song | it may sit outside the pool's styles (mostly pop, R&B, indie, K/C/J-pop) | say so: "the pool has about 5,300 songs; a metal or classical track has no close neighbours here" |
| Everything fails | | show the backup video, then explain the design and the friends' results |

## 6. Say this honestly (what the demo does NOT prove)

- It is a **recommendation by sound**, from a pool of about 5,300 songs (YouTube only, mostly pop, R&B, indie and Asian pop). It is not a general music service.
- The match scores are not "how much you will like it". The friends' test is the evidence for that, and it had only a handful of friends.
- Rhythm is the weakest of the four features (the beat-detection checks failed at 64-67% against an 85% bar).
- AI-generated songs were removed with a tagger that finds about 77% of them: some remain.
- Nothing is stored except numbers, titles and your "would add" answers on this laptop.

## 7. After the demo

`python demo_server.py --summary` for the runs, failures and the "would add" rate per list (a small, informal sample: do not quote it as a result). The raw files are `results/demo_log.csv` and `results/demo_feedback.csv`.
