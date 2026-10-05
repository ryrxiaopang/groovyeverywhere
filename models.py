"""Official Essentia model files (https://essentia.upf.edu/models.html).
Licence: CC BY-NC-SA 4.0 (non-commercial) — fine for this student project.

Run `python models.py` once to download everything into ./models (about 60 MB).
Input/output node names are read from each model's .json so they can't drift.
"""
import json, os, sys, urllib.request

BASE = "https://essentia.upf.edu/models"
MODELS = {
    # name: (path on server, role)
    "effnet":          ("feature-extractors/discogs-effnet/discogs-effnet-bs64-1", "Sound: 1,280 numbers per ~2 s"),
    "musicnn":         ("feature-extractors/musicnn/msd-musicnn-1", "Mood input: 200 numbers per ~3 s"),
    "genre400":        ("classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1", "Diagnostic: which of 400 styles EffNet hears"),
    "instruments":     ("classification-heads/mtg_jamendo_instrument/mtg_jamendo_instrument-discogs-effnet-1", "Instruments: 40 likelihoods"),
    "emomusic":        ("classification-heads/emomusic/emomusic-msd-musicnn-2", "Mood: happiness (valence) + energy (arousal), 1-9"),
    "deam":            ("classification-heads/deam/deam-msd-musicnn-2", "Mood backup: valence + arousal"),
    "mood_happy":      ("classification-heads/mood_happy/mood_happy-discogs-effnet-1", "Cross-check: happy yes/no"),
    "mood_sad":        ("classification-heads/mood_sad/mood_sad-discogs-effnet-1", "Cross-check: sad yes/no"),
    "mood_aggressive": ("classification-heads/mood_aggressive/mood_aggressive-discogs-effnet-1", "Cross-check: aggressive yes/no"),
    "mood_relaxed":    ("classification-heads/mood_relaxed/mood_relaxed-discogs-effnet-1", "Cross-check: relaxed yes/no"),
    # ---- candidates being tested (a missing one is skipped, never breaks a run)
    "vggish":             ("feature-extractors/vggish/audioset-vggish-3", "Candidate ear for Mood: 128 numbers per ~1 s"),
    "emomusic_vggish":    ("classification-heads/emomusic/emomusic-audioset-vggish-2", "Candidate Mood: emoMusic via VGGish"),
    "deam_vggish":        ("classification-heads/deam/deam-audioset-vggish-2", "Candidate Mood: DEAM via VGGish"),
    "mood_happy_musicnn": ("classification-heads/mood_happy/mood_happy-msd-musicnn-1", "Candidate Mood: happy yes/no via MusiCNN"),
    "mood_sad_musicnn":   ("classification-heads/mood_sad/mood_sad-msd-musicnn-1", "Candidate Mood: sad yes/no via MusiCNN"),
    "danceability":       ("classification-heads/danceability/danceability-discogs-effnet-1", "Candidate Rhythm: danceable yes/no"),
    "tempocnn":           ("tempo/tempocnn/deepsquare-k16-3", "Candidate Rhythm: tempo model (TempoCNN)"),
}
OPTIONAL = {"vggish", "emomusic_vggish", "deam_vggish", "mood_happy_musicnn", "mood_sad_musicnn", "danceability", "tempocnn"}
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


def available(name):
    pb, js = paths(name)
    return os.path.exists(pb) and os.path.exists(js) and os.path.getsize(pb) > 0


def paths(name):
    stem = os.path.join(MODEL_DIR, os.path.basename(MODELS[name][0]))
    return stem + ".pb", stem + ".json"


def meta(name):
    with open(paths(name)[1]) as f:
        return json.load(f)


def node(name, purpose):
    """Return (input_name, output_name) for the output with this purpose ('predictions'/'embeddings')."""
    m = meta(name)
    inp = m["schema"]["inputs"][0]["name"]
    for o in m["schema"]["outputs"]:
        if o.get("output_purpose") == purpose:
            return inp, o["name"]
    raise KeyError(f"{name}: no output with purpose {purpose}")


def classes(name):
    return meta(name)["classes"]


def download():
    """Downloads to a .part file first, so a stopped download is never mistaken for a finished one.
    Slow server? Use instead:  wget -c --tries=20 --timeout=30 -P models -i model_urls.txt"""
    import socket
    socket.setdefaulttimeout(60)
    os.makedirs(MODEL_DIR, exist_ok=True)
    for name, (path, role) in MODELS.items():
        for ext in (".pb", ".json"):
            url = f"{BASE}/{path}{ext}"
            dest = os.path.join(MODEL_DIR, os.path.basename(path) + ext)
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                continue
            def hook(blocks, bs, total, _n=name + ext):
                done = blocks * bs / 1e6
                print(f"\r  {_n:22s} {done:6.1f} / {total/1e6:5.1f} MB", end="", flush=True)
            print(f"downloading {url}")
            for attempt in range(5):
                try:
                    urllib.request.urlretrieve(url, dest + ".part", reporthook=hook)
                    os.replace(dest + ".part", dest)
                    print()
                    break
                except Exception as e:
                    print(f"\n  retry {attempt+1}/5 after error: {e}")
            else:
                if name in OPTIONAL:
                    print(f"  !! skipped optional model {name}: the test for it will be skipped")
                    break
                raise SystemExit(f"could not download {url} - try the wget command in this file's docstring")
    print("all models present in", MODEL_DIR)


if __name__ == "__main__":
    download()
    for n in MODELS:
        try:
            print(f"{n:16s} classes={str(classes(n))[:70]}")
        except Exception as e:
            print(n, "->", e, file=sys.stderr)
