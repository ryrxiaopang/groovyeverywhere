# groovyeverywhere: Devpost fields

The project story (the "About the project" field) is [`DEVPOST_STORY.md`](DEVPOST_STORY.md). This file holds the short fields and the links.

## Tagline
groovyeverywhere listens to a song you love and finds songs that really sound like it, without ever keeping the audio.

## Elevator pitch (about 30 seconds)
Streaming apps keep pushing what is already popular. groovyeverywhere takes a song you love, listens to how it sounds, feels and moves (its sound, mood, rhythm and instruments), and finds songs in a pool of about 9,000 that genuinely match it, not just the ones everyone has heard. It uses open audio-AI models, stores only numbers, never audio, and filters out AI-generated tracks. Pass marks were set before looking and a sealed test set was scored once, so we can say honestly where it works and where it does not.

## Built with
Python, Essentia (TensorFlow audio models: Discogs-EffNet, VGGish / emoMusic, instrument classifier), NumPy, yt-dlp, ffmpeg, deno, HTML / CSS / JavaScript, YouTube Data API, Spotify and Deezer artist pages, Lingua (language detection), Cloudflare Tunnel, GitHub Pages, Claude Code.

## Links
- Try it: https://ryrxiaopang.github.io/groovyeverywhere/ (forwards to the live demo on our own computer through a Cloudflare tunnel; one song at a time)
- Demo video: https://www.youtube.com/watch?v=jMhueRJbihI
- Code: https://github.com/ryrxiaopang/groovyeverywhere (branch `master`; no API keys, data or audio in the code or its history)

## Licence note
The Essentia models are CC BY-NC-SA, so this is a non-commercial student project.
