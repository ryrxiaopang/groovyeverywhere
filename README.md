# groovyeverywhere

Tell it a song you love; it listens to the song and finds songs in a pool of about 9,000 that really sound like it, not just the ones everyone has heard.
Built for the AI Lodge Hackathon (October 2026).

* **Try it:** https://ryrxiaopang.github.io/groovyeverywhere/ (forwards to the live demo, which runs on our own computer; one song at a time)
* **Demo video:** https://www.youtube.com/watch?v=jMhueRJbihI
* **Write-up:** [`DEVPOST_STORY.md`](DEVPOST_STORY.md)

## How it works

1. A visitor types a song name or pastes a YouTube link. The server downloads the audio into a temporary folder, analyses the whole song and deletes it: **no audio is ever kept, only numbers.**
2. Open audio-AI models from [Essentia](https://essentia.upf.edu/models.html) turn the song into numbers: Discogs-EffNet (1,280 "Sound" numbers), VGGish to emoMusic (happiness and energy), an instrument classifier (40 instruments) and a rhythm analysis.
3. The song is compared with every pool song (cosine similarity on the rescaled Sound numbers, plus mood / rhythm / instruments as filters) and two lists come back: **closest in sound**, and **sound plus the features you pick**.
4. The page shows what the models heard, ranks every match against the whole pool ("closer than 99.4% of the pool"), warns when nothing is really close, and lets the visitor choose languages (English, Chinese, Korean by default; Japanese and others on request).

The pool (YouTube only, frozen at about 9,000 songs by 2,460 artists) is aimed at younger listeners: about 6,100 English, 1,400 Chinese, 1,100 Korean and 300 Japanese songs. AI-generated uploads are removed (a tagger checked by listening to 99 songs, plus a channel block list).

## Results (measured, with pass marks fixed before looking)

| What | Result |
|---|---|
| Sealed test: 1,143 songs of the official MTG-Jamendo test split, scored once (6 Oct 2026) | 16 checks pass, 3 fail, 6 warn, 2 skipped ([`report_test.html`](report_test.html), [`evidence_summary_test.json`](evidence_summary_test.json)) |
| The 3 failures | Sound keeps two styles apart 65% of the time (bar 85%; only 5 songs in one of the styles); both beat-detection checks 64-67% (bar 85%) |
| Sound finds a song by the same artist from another album in its top 10 | 29% of questions (138 questions) |
| AI-music tagger, checked by listening to 99 songs | "confirmed" right 12 of 12, "likely" 28 of 29; finds about 77% of AI music (95% range 59-85%) |
| Singer-voice matching (dropped) | +2.8 points (95% range -5.1 to +10.8) against a +10 bar set before the run |
| Demo rehearsal on the desktop | 17 of 17 real songs worked; a new song about 20 s, a stored song 1-2 s |

The first scoring run of the sealed test was defective (634 of 1,143 songs were read wrongly); it was fixed, disclosed and kept as `*_run1_defective.*`. The pass marks are in
[`archive/README_first_kit.md`](archive/README_first_kit.md); the frozen code fingerprint of the sealed run is [`test_split_freeze.json`](test_split_freeze.json). The validation numbers are in [`report_validation.html`](report_validation.html).
(GitHub shows the `.html` reports as source: download them, or open them with a raw-HTML viewer.)

## Run it yourself (Linux / WSL2, Python 3.14)

```bash
python3.14 -m venv .venv && source .venv/bin/activate                           # the pinned Essentia build installs on Python 3.14 only
pip install -r requirements.txt
sudo apt install -y ffmpeg && curl -fsSL https://deno.land/install.sh | sh     # yt-dlp needs deno for YouTube; open a new terminal afterwards
python models.py                                                              # the Essentia models
python demo_server.py --fake      # practice mode: the page with canned matches, no pool needed
python demo_server.py --check     # pre-flight check for the real demo
python demo_server.py             # the real demo on http://localhost:8765 (needs the analysed pool in results/)
```

The analysed pool (`results/`, the `pool_*.csv` lists) is data and is not in this repository; `make_demo_bundle.py` packs the numbers a demo machine needs.
`python synthetic_tests.py` is the offline self-check (32 sections; the first ones need Essentia).

## Main files

| | |
|---|---|
| `demo_server.py`, `demo.html` | the demo website (search, live analysis, results, language and feature chips, tab-capture fallback) |
| `analyze.py`, `models.py`, `sources.py` | one song to numbers; the models; temporary downloads that are always deleted |
| `recommend_song.py`, `blind_test.py`, `scoring.py`, `match.py` | matching, ranking and the friends' blind-test lists |
| `song_languages.py` | language labels for the language filter |
| `tag_ai.py`, `mark_ai_out.py`, `ai_channels.py`, `ai_tag_check.py` | AI-music detection, removal and its listening check |
| `build_from_spotify.py`, `deezer_discover.py`, `add_channel.py`, `add_song.py`, `boost_artists.sh` | growing the pool |
| `pool_summary.py`, `pool_duplicates.py`, `find_official_versions.py` | pool statistics and quality |
| `evaluate.py`, `SUCCESS_RULE.md` | the sealed test and the pre-registered success rule |
| `DEMO.md`, `CLAUDE.md` | demo run sheet; full project notes |

## Honest limits

* Rhythm is the weakest feature (beat-detection checks 64-67% against an 85% bar).
* The AI tagger finds about 77% of AI music (95% range 59-85%); the block list covers part of the rest.
* The friends' second blind-test round was not scored (the ratings did not come back), and the first was confounded by AI uploads, so there is no claim yet about how often people keep the recommendations.
* Essentia models are CC BY-NC-SA: this is a non-commercial student project. The code is MIT ([`LICENSE`](LICENSE)); credits and third-party licences are in [`NOTICE.md`](NOTICE.md).

The first test kit's README (160 songs, Jamendo / FMA / Audius) is kept in [`archive/README_first_kit.md`](archive/README_first_kit.md).
