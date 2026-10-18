# Devpost write-up draft: Hidden Gems (groovyeverywhere)

Track: **Projects for Daily Life** (music discovery). Everything in [SQUARE BRACKETS] is still to fill in. Only claims that are already measured are in here: check each number against the repo before submitting.

## Tagline (one line)
Hidden Gems listens to a song you love and finds songs that really sound like it, without ever keeping the audio.

## Elevator pitch (about 30 seconds)
Streaming apps keep pushing what is already popular. Hidden Gems takes a song you love, listens to how it sounds, feels and moves (its sound, mood, rhythm and instruments), and finds songs that genuinely match it, not just the ones everyone has heard. It uses open audio-AI models and stores only numbers, never audio. It filters out AI-generated tracks. And we test it the hard way: pass marks set before we looked, a sealed test set scored once, and a friends' blind test with the success rule written down before it was sent. So we can say honestly where it works and where it does not.

## Inspiration
Recommendations tend to follow popularity. We wanted to see whether the *sound* of a song alone can find songs a listener would keep, and to measure it honestly instead of just demoing it.

## What it does
- Type a song name or paste a YouTube link. The app downloads the audio into a temporary folder, analyses it, deletes it, and keeps only numbers.
- It shows two lists: matches on Sound only, and matches on Sound plus the features you choose (mood, rhythm, instruments).
- A "what we heard" strip says what the models heard: mood in words, tempo (only if the beat detector is sure), the main instruments.
- Up to 3 songs per visitor, each in its own tab. Songs are never blended into one list (mixing genres averages the numbers and recommends rubbish).
- Songs already in the pool are served instantly, with no download.

## How AI is used (not an LLM wrapper)
- Pretrained open audio models from Essentia: Discogs-EffNet embeddings (1,280 numbers per song for "Sound"), VGGish to emoMusic (happiness and energy), an instrument classifier (40 instruments), and a rhythm analysis.
- Matching: cosine similarity on the Sound embeddings after a gentle rescaling fitted on the pool. We compared the metrics and measured the rescaling rather than assuming it helped.
- Combining features: the best part of each song is chosen after combining features, and every chosen feature must reach the 65th percentile.
- A pool of 8,062 YouTube songs on 16 Oct (on 11 Oct, at 5,600 songs, the mix was English and other Latin-script about 68%, Korean 12.5%, Mandarin 8.7%, Japanese 7%, Cantonese 3%) [RE-RUN pool_summary.py for today's mix], grown from Spotify and Deezer artist lists aimed at younger listeners.
- An AI-music detector (text and metadata signals) that removes AI-generated uploads from the pool.

## Safety and responsible AI
- **Privacy by design:** no audio is ever kept. Every download goes through a temporary folder that is deleted; an offline test proves deletion for every source, and a sweep removes folders left by a crash. The demo shows a consent line and gives each visitor an anonymous id.
- **Synthetic-content safeguard:** AI-generated songs are removed from recommendations. We measured the detector by listening to 99 songs: confirmed 12 of 12 really AI, "likely" 28 of 29 (20 of 20 under 10,000 views, no false alarms), but it finds only about 77% of AI music (95% range 59-85%). So we added a channel block list and say plainly that the filter is safe but incomplete.
- **Honest testing:** pass marks were fixed before looking. The MTG-Jamendo test split is sealed and was scored once. Our first scoring run was defective (634 of 1,143 songs affected); we fixed it, disclosed it and kept the defective files. Result on 1,143 sealed songs: 16 checks pass, 3 fail, 6 warn, 2 skipped.
- **A feature we dropped:** singer-voice matching gained +2.8 points (95% range -5.1 to +10.8) against a pre-set +10 bar, so it was left out of version 1.
- **A confound we caught:** our first friends' round was skewed by AI uploads (58% of the "Sound only" songs were AI-tagged against 8% of the random list). We fixed the pool and re-ran with a pre-registered rule (`SUCCESS_RULE.md`, committed before the sheets were sent).
- **Failure handling in the demo:** a weak-match warning when the best similarity is low; live streams, premieres and non-songs are refused; one request at a time; only a YouTube video id is used (the server rebuilds the address itself); a failed download offers a tab-capture fallback. An independent code review found 11 demo problems and 8 data-safety problems; each was checked and fixed, with tests (`synthetic_tests.py`, sections 24-25).
- **Known limits:** Rhythm is the weakest feature (beat-detection checks 64-67% against an 85% bar). Few friends took part, so ranges are rough. Visitors' answers at a booth are informal and are not used as evidence.

## Real-world value
Music discovery for listeners who are tired of the same popular songs, with matches explained in words (mood, tempo, instruments) and a clear note when the match is weak. We tested it on friends with a blind design: lists A (Sound only), B (Sound plus the feature they love), C (random same genre) and D (the most-viewed songs of the same style) so that popularity alone cannot explain a good result.

## What is measured, what is not
- Measured: the sealed test above, the AI detector check, the metric comparison, Sound finds a same-artist song on another album in the top 10 for 29% of questions.
- **Round 2 of the friends' blind test (5 friends) was sent on 11 Oct; the ratings did not come back before the deadline, so it is not scored.** The success rule is fixed in advance: at least +10 points, 95% range above 0, 4 or more friends who rated both lists. [UPDATE if ratings arrive before the deadline; otherwise keep this sentence as it is.]
- Demo rehearsal (desktop, 17 real songs): 17 of 17 worked after fixing a YouTube download problem found in the first run (2 of 17 had failed with HTTP 403); a new song takes about 20 s (download 7 s, analysis 13 s), a stored song 1-2 s.

## How we built it
Python, Essentia (TensorFlow models), yt-dlp, numpy, a small local web server with a single-page HTML front end, YouTube Data API for pool metadata. Built with Claude Code. Models are CC BY-NC-SA, so this is a non-commercial student research project.

## Challenges
Beat detection is unreliable; AI music is hard to spot; YouTube throttles downloads; keeping tests honest while the project kept changing.

## What's next
Score round 2, calibrate the weak-match threshold from real demo logs, add a blind-test mode to the demo, and grow the pool for thin styles (indie rock, singer-songwriter).

## Pictures to include
1. The demo page with a real result (two lists, "what we heard" strip, tabs).
2. The weak-match warning.
3. A diagram: song, temporary download, numbers only, audio deleted.
4. The sealed-test summary table.
5. [Optional] the AI-detector check numbers.

## Links
- GitHub: https://github.com/ryrxiaopang/groovyeverywhere (branch `master`; checked: no API keys in the code or its history, and no data or audio)
- Deployed project: https://ryrxiaopang.github.io/groovyeverywhere/ (live on our own computer through a Cloudflare tunnel; one song at a time)
- Demo video: https://www.youtube.com/watch?v=jMhueRJbihI
