# Credits and third-party licences

The code in this repository is under the MIT licence (`LICENSE`). It uses, but does not include, the following. Their own terms apply to them:

| What | Used for | Licence |
|---|---|---|
| [Essentia](https://essentia.upf.edu/) (Music Technology Group, Universitat Pompeu Fabra), installed with `pip install essentia-tensorflow` | audio analysis | AGPL-3.0 |
| [Essentia models](https://essentia.upf.edu/models.html): Discogs-EffNet, VGGish, emoMusic, MTG-Jamendo instrument and mood classifiers (downloaded by `models.py`) | the Sound, Mood and Instruments numbers | CC BY-NC-SA 4.0: **non-commercial use only** |
| [MTG-Jamendo dataset](https://github.com/MTG/mtg-jamendo-dataset) metadata in `data/` (track ids, human tags, official splits; no audio) | testing the models; the sealed test split | CC BY-NC-SA 4.0 (annotations) |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org/), [deno](https://deno.com/) | fetching a song's audio into a temporary folder that is deleted after analysis | their own licences |
| [Lingua](https://github.com/pemistahl/lingua-py) | language labels (desktop only) | Apache-2.0 |

Because the models are non-commercial, groovyeverywhere as a whole is a **non-commercial student project**. No audio is stored or shared by this project:
only numbers computed from the audio.
