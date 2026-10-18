## Inspiration

Music recommendations tend to follow popularity: the more a song has been played, the more it gets pushed. Our mentor asked us three questions that stuck with us. Should a whole song be analysed, or three parts of it? Can audio models tell a happy loud song from a sad loud one? And do those features combine into recommendations people would actually keep? We decided to answer them with numbers instead of opinions, and to build a small recommender on top of the answers: **Hidden Gems**.

## What it does

You type a song name or paste a YouTube link. The app listens to the audio, keeps only numbers (never the audio), and returns two lists of matches:

- **Sound only:** songs that sound like yours.
- **Sound plus the features you choose:** mood, rhythm, instruments.

A "what we heard" strip says what the models heard (the mood in words, the tempo if the beat detector is sure, the main instruments), and a warning appears when the best match is weak. Language chips let the visitor choose which languages to see (English, Chinese and Korean by default; Japanese and other languages on request). A visitor can try up to three songs, each in its own tab. Songs are never blended into one list, because mixing genres averages their numbers and recommends rubbish.

## How we built it

- **AI models (not an LLM wrapper):** pretrained open audio models from Essentia. Discogs-EffNet gives each song 1,280 "Sound" numbers. VGGish feeding emoMusic gives happiness and energy. A classifier scores 40 instruments, and a rhythm analysis finds tempo and steadiness.
- **Matching:** cosine similarity between two songs' Sound vectors, after a gentle rescaling fitted on our pool:

  $$\operatorname{sim}(a,b)=\frac{\tilde a\cdot\tilde b}{\lVert\tilde a\rVert\,\lVert\tilde b\rVert},\qquad \tilde x=\frac{x-\mu}{\sigma^{0.25}}$$

  where $\mu$ and $\sigma$ are the pool's average and spread for each of the 1,280 numbers. A full z-score failed our own style pass mark, and we compared other distance measures before choosing this one.
- **Combining features:** the best part of each song is chosen after combining features, and every chosen feature must reach the 65th percentile of the pool.
- **The pool:** about 9,000 YouTube songs by 2,460 artists, grown from Spotify and Deezer artist lists and aimed at younger listeners like our friends: about 6,100 English, 1,400 Chinese, 1,100 Korean and 300 Japanese songs, including about 940 hip hop songs in English, Mandarin and Korean.
- **Stack:** Python, Essentia (TensorFlow), yt-dlp, NumPy, a small local web server with a single-page front end, and the YouTube Data API for metadata. Built with Claude Code.

## Safety and responsible AI

- **No audio is ever kept.** Every download goes into a temporary folder that is deleted straight after analysis. An offline test checks deletion for every source, and a sweep removes folders left behind by a crash.
- **AI-generated music is filtered out.** A detector reads titles and descriptions for signs of AI-made uploads. We measured it by listening to 99 songs: it was right on 12 of 12 "confirmed" and 28 of 29 "likely", but it finds only about 77% of AI music (95% range 59-85%). So we added a channel block list, and we say plainly that the filter is safe but incomplete.
- **Tests that cannot be quietly bent.** Pass marks were fixed before we looked. A sealed test set of 1,143 songs was scored once: 16 checks pass, 3 fail, 6 warn, 2 skipped. Our first scoring run was defective, so we fixed it, disclosed it and kept the defective files.
- **Failure handling in the demo.** Weak-match warning, refusal of live streams and non-songs, one request at a time, only a YouTube video id is used (the server rebuilds the address itself), and a tab-capture fallback if a download fails. An independent code review found problems in the demo and in our data-handling scripts; we checked each one, fixed it, and added tests.

## Challenges

- **Beat detection is unreliable.** Both rhythm checks scored 64-67% against an 85% bar. Rhythm is our weakest feature, and we present it that way.
- **AI music in the pool.** Our first friends' test was skewed: 58% of the "Sound only" songs were AI-tagged, against 8% of the random list. We caught it, rebuilt the pool without AI songs, and re-ran the test with a success rule written down before sending.
- **YouTube throttling and covers.** Downloads were blocked after a few hundred songs, and many entries were covers or fan lyric videos instead of the artist's own upload, so we built tools to find the original.
- **Staying honest while the project kept changing.** Every change had to keep the offline self-check green (30 test sections) without leaking test songs into the pool.

## What we learned

- Setting the pass marks and the success rule before looking is what made the results believable, including the ones that failed.
- A feature can be interesting and still not earn its place: singer-voice matching gained +2.8 points (95% range -5.1 to +10.8) against a pre-set +10 bar, so we left it out of version 1.
- The data you evaluate on matters more than the model: AI uploads nearly ruined our first test.
- Plain numbers with ranges, and saying what was *not* verified, were more useful to us than a polished demo.

## Where things stand, honestly

On the sealed test, Sound finds a same-artist song on another album in the top 10 for 29% of questions. Round 2 of our friends' blind test was sent to five friends and the ratings are still coming in; the success rule (at least +10 points, 95% range above zero, at least four friends who rated both lists) was fixed in advance, and we will report the result either way. In a rehearsal with 17 real songs on our desktop, all 17 worked once we fixed a YouTube download problem we found in the first run (2 of 17 had failed). A new song takes about 20 seconds (7 s to download, 13 s to analyse the whole song); a song already in the pool is served in 1 to 2 seconds.

**Try it:** https://ryrxiaopang.github.io/groovyeverywhere/ (it runs live on our own computer through a Cloudflare tunnel, one song at a time; if it is offline, the [demo video](https://www.youtube.com/watch?v=jMhueRJbihI) shows the same thing).

## What's next

Score round 2, calibrate the weak-match threshold from real demo logs, add a blind-test mode to the demo, and grow the thin styles (indie rock, singer-songwriter).
