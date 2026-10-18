## Inspiration

Music recommendations tend to follow popularity: the more a song has been played, the more it gets pushed, and the songs we would actually love get buried. Furthermore, they tend to recommend songs which other people who listen to this song also listen to rather than songs that sound similar. Hence, I wanted to build a song recommender website to offer better recommendations to people: **groovyeverywhere**.

## What it does

You type a song name or paste a YouTube link. The app listens to the whole song, keeps only numbers (never the audio), and returns two lists of matches from a pool of about 9,000 songs:

- **1. Closest in sound:** songs that sound like yours.
- **2. Sound plus what you care about:** songs that also match the mood, the rhythm and / or the instruments you pick.

A "what we heard" strip says what the models heard (the mood in words, the tempo when the beat detector is sure, the main instruments). Every match is ranked against the whole pool ("closer than 99.4% of the pool"), and a warning appears when nothing in the pool is really close. Language chips let you choose what to see (English, Chinese and Korean by default; Japanese and other languages on request). You can try up to three songs, each in its own tab; songs are never blended into one list, because mixing genres averages their numbers and recommends rubbish. A song that is already in the pool is answered in 1 to 2 seconds; a new song takes about 20 seconds (7 s to download, 13 s to analyse the whole song).

**Try it:** https://ryrxiaopang.github.io/groovyeverywhere/ (it runs live on our own computer, one song at a time; if it is offline, the [demo video](https://www.youtube.com/watch?v=jMhueRJbihI) shows the same thing).

## How we built it

- **AI models (not an LLM wrapper):** pretrained open audio models from Essentia. Discogs-EffNet turns each song into 1,280 "Sound" numbers; VGGish feeding emoMusic gives happiness and energy; a classifier scores 40 instruments; a rhythm analysis finds tempo and steadiness.
- **Matching:** cosine similarity between two songs' Sound numbers, after a gentle rescaling fitted on our pool:

  $$\operatorname{sim}(a,b)=\frac{\tilde a\cdot\tilde b}{\lVert\tilde a\rVert\,\lVert\tilde b\rVert},\qquad \tilde x=\frac{x-\mu}{\sigma^{0.25}}$$

  where $\mu$ and $\sigma$ are the pool's average and spread for each of the 1,280 numbers. A full z-score failed our own style pass mark, and we compared other distance measures before choosing this one. For list 2 the best part of each song is chosen after combining features, and every chosen feature must reach the 65th percentile of the pool.
- **The pool:** about 9,000 YouTube songs by 2,460 artists, grown from Spotify and Deezer artist lists and aimed at younger listeners like our friends: about 6,100 English, 1,400 Chinese, 1,100 Korean and 300 Japanese songs, including about 940 hip hop songs in English, Mandarin and Korean. Each song carries a language label from its title's script, the search it came from and an offline language detector.
- **Safety built in:**
  - **No audio is ever kept.** Every download goes into a temporary folder that is deleted straight after analysis; an offline test checks the deletion, and a sweep removes folders left behind by a crash.
  - **AI-generated music is filtered out.** A detector reads titles and descriptions for signs of AI-made uploads, and a block list removes whole channels of AI "mood mills". We measured the detector by listening to 99 songs: right on 12 of 12 "confirmed" and 28 of 29 "likely", but it finds only about 77% of AI music (95% range 59-85%), which is why the block list exists.
  - **The demo fails safely.** Only a YouTube video id is used (the server builds the address itself), live streams and non-songs are refused, one song is analysed at a time, and if a download is blocked the page offers to capture 30 seconds from another browser tab instead.
- **Stack:** Python, Essentia (TensorFlow), NumPy, yt-dlp with ffmpeg and deno, a small Python web server with a single-page HTML / CSS / JavaScript front end, the YouTube Data API, Spotify and Deezer artist pages, the Lingua language detector, a Cloudflare tunnel and GitHub Pages for the public link. Built with Claude Code.

## Challenges we ran into

- **AI music everywhere.** In our first test with friends, 58% of the "sound only" picks were tagged as AI-generated uploads (against 8% of the random picks), because the least-played songs on YouTube are often AI. We measured the problem, removed every AI-tagged song and blocked whole channels.
- **YouTube fights downloads.** Downloads were throttled after a few hundred songs, and during our last rehearsal 2 of 17 songs failed with "403 Forbidden" until we found that yt-dlp needed a JavaScript runtime and an up-to-date puzzle solver. Many pool entries were covers or fan lyric videos, so we built tools to find the artist's own upload.
- **Beat detection is unreliable.** Both rhythm checks scored 64-67% against an 85% bar, so rhythm is our weakest feature and we present it that way.
- **Language is not in the sound.** A Chinese rap song matched French rap, because they really do sound alike. We added language labels and chips; the first version of the labels hid English songs because artists' names looked French or German, so we rebuilt it to read only the song's own name.
- **Staying honest while the project kept changing.** Every change had to keep the offline self-check green (32 test sections), and an independent code review found problems in the demo and in our data scripts that we checked, fixed and tested.

## Accomplishments that we're proud of

- A live demo where anyone can bring their own song and get recommendations on the spot, with 17 of 17 real songs working in our final rehearsal.
- Results we can defend: pass marks fixed before we looked, and a sealed test set of 1,143 songs scored once (16 checks pass, 3 fail, 6 warn, 2 skipped). When our first scoring run turned out to be defective, we fixed it, disclosed it and kept the defective files.
- On the sealed test, the Sound feature alone finds a song by the same artist from a different album in the top 10 for 29% of questions (138 questions).
- An honest AI-music filter, with its weak spot measured and stated.
- A pool of 9,000 songs across English, Chinese and Korean, aimed at the people we built it for.

## What we learned

- Setting the pass marks before looking is what makes results believable, including the ones that fail.
- A feature can be interesting and still not earn its place: matching singers' voices gained only +2.8 points (95% range -5.1 to +10.8) against a pre-set +10 bar, so we left it out.
- The data matters more than the model: AI uploads nearly ruined our first test, and duplicate uploads and fan videos kept creeping into the pool.
- Plain numbers with ranges, and saying what was *not* verified, were more useful than a polished claim.

## What's next for groovyeverywhere

- A proper blind test with more listeners, to measure how often people keep the songs it recommends.
- Calibrate the "weak match" warning from real demo logs, and add a blind mode to the demo so booth visitors' answers can count as data.
- Grow the thin styles (Japanese indie and rock, folk) and keep replacing fan uploads with the artists' own videos.
- A faster analysis path for weaker computers, so the booth laptop answers new songs as quickly as the desktop.
