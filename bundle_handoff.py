"""Check a demo bundle and turn it into the copy we hand to another team (e.g. the AI Lodge team hosting a live demo).

  python make_demo_bundle.py --out groovy-demo-bundle          # 1. the bundle (demo-bundle-<date>.zip in that folder)
  source env_keys.sh                                           #    (so the secret check knows the real key values; they are never printed)
  python bundle_handoff.py groovy-demo-bundle                  # 2. checks it, adds the Sound scale and README.txt -> groovy-demo-bundle/groovy-demo-bundle.zip

Run it on the machine that made the bundle (the desktop: it compares the zip with results/ and the pool lists). It prints one line per check
(PASS / WARN / FAIL), the size and the song count, and exits with 1 when a check FAILS (then the handoff zip is not written).
Checks: every pool song has its cut-down numbers (Sound, Instruments, Mood: whole song + parts), the stretch index covers the same songs, the lists,
tags and labels are there; no audio file (by name and by its first bytes); no API key, cookie file or private key (by name and by content).
Adds: results/sound_scale_youtube.npz (the rescaling the matcher fits on the pool) and README.txt (how the files map to the code, the model versions,
how to reproduce the rescaling).
"""
import argparse, glob, hashlib, io, os, re, sys, time, zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

NEED_ARRAYS = ("effnet_whole", "effnet_parts", "instruments_whole", "instruments_parts", "emomusic_whole", "emomusic_parts")
NEED_RES = ("index.csv", "windows_cache.npz", "ai_tags.csv", "pool_links.csv", "link_alternatives.csv", "song_languages.csv")
NEED_TOP = ("ai_keep.txt", "ai_block.txt")
AUDIO_EXT = (".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".webm", ".mp4", ".mkv", ".wma", ".aiff", ".aif")
AUDIO_MAGIC = (b"ID3", b"fLaC", b"OggS", b"\x1aE\xdf\xa3")            # mp3 tag, flac, ogg / opus, webm / mkv; wav (RIFF..WAVE) and mp4 (..ftyp) below
SECRET_NAMES = re.compile(r"(cookie|env_keys|\.env$|\.pem$|\.key$|id_rsa|id_ed25519|credential|token|secret)", re.I)
SECRET_TEXT = {
    "a Google / YouTube API key": re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
    "a cookies.txt file": re.compile(rb"Netscape HTTP Cookie File|\t(?:SAPISID|__Secure-[0-9A-Z]+PSID|LOGIN_INFO)\t"),
    "a private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "a GitHub token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{36}"),
    "an API secret (sk-...)": re.compile(rb"\bsk-[A-Za-z0-9_\-]{20,}"),
}
KEY_VARS = ("YOUTUBE_API_KEY", "JAMENDO_CLIENT_ID", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "HG_YT_COOKIES_FILE")


def newest_bundle(path):
    """The zip to check: `path` itself, or the newest demo-bundle-*.zip in that folder."""
    if os.path.isfile(path):
        return path
    found = sorted(glob.glob(os.path.join(path, "demo-bundle-*.zip")), key=os.path.getmtime)
    if not found:
        sys.exit(f"no demo-bundle-*.zip in {path}: run  python make_demo_bundle.py --out {path}  first")
    return found[-1]


def is_audio(name, head):
    return (name.lower().endswith(AUDIO_EXT) or head.startswith(AUDIO_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WAVE")
            or head[4:8] == b"ftyp" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and not name.endswith((".csv", ".txt", ".json"))))


def secret_hits(name, data, env=None):
    """What kind of secret this entry looks like it holds (never the value itself)."""
    env = os.environ if env is None else env
    hits = [f"a file named like one ({os.path.basename(name)})"] if SECRET_NAMES.search(os.path.basename(name)) else []
    if name.endswith(".npz"):
        return hits                                                    # numbers only (checked with allow_pickle=False when read)
    hits += [kind for kind, rx in SECRET_TEXT.items() if rx.search(data)]
    hits += [f"the value of ${v}" for v in KEY_VARS if len(env.get(v, "")) >= 12 and env[v].encode() in data]
    return hits


def scale_file(here=HERE):
    """(path, mu, sd, hash) of the Sound scale the recommender uses for this pool: fitted (or read from its cache) exactly as the demo does."""
    import blind_test as bt, match
    match.use_scale_sources(bt.POOL_SOURCES)
    mu, sd = match.sound_scale()
    src = match._scale_sources
    path = os.path.join(here, "results", "sound_scale.npz" if not src else "sound_scale_" + "_".join(src) + ".npz")
    with np.load(path) as d:
        return path, mu, sd, str(d["hash"]), int(d["n"])


def expected_hash(keys):
    """The hash match.sound_scale() computes from the songs it fits on: if the file's hash equals this, the receiving machine uses it as is."""
    import scoring
    return hashlib.md5(("\n".join(sorted(keys)) + f"|power={scoring.SOUND_SPREAD_POWER}").encode()).hexdigest()


def check(zip_path, here=HERE, env=None):
    """[(status, what, detail)] for every check, plus facts for the README."""
    import make_demo_bundle as mb
    from results_index import POOL_LISTS
    rows, _ = mb.pool_rows(here)
    want = set(rows)
    out, facts = [], dict(songs=0)
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        have = {n[len("results/"):-4] for n in names if re.fullmatch(r"results/[^/]+_[^/]+\.npz", n)} - {"windows_cache", "sound_scale_youtube", "sound_scale"}
        facts["songs"] = len(have & want)
        lost, short, no_vggish = sorted(want - have), [], 0
        for k in sorted(have & want):
            with np.load(io.BytesIO(z.read(f"results/{k}.npz")), allow_pickle=False) as d:
                miss = [a for a in NEED_ARRAYS if a not in d.files]
                if miss:
                    short.append(f"{k} ({', '.join(miss)})")
                no_vggish += "cand_emomusic_vggish_whole" not in d.files
        out.append(("PASS" if not lost else "FAIL", "numbers for every pool song",
                    f"{len(have & want)} of {len(want)} pool songs" + (f"; missing e.g. {', '.join(lost[:5])}" if lost else "")))
        out.append(("PASS" if not short else "FAIL", "Sound, Instruments and Mood (whole song + parts) in each file",
                    "all there" if not short else f"{len(short)} files lack arrays, e.g. {'; '.join(short[:3])}"))
        out.append(("PASS" if not no_vggish else "WARN", "the chosen Mood model (VGGish -> emoMusic)",
                    "in every file" if not no_vggish else f"{no_vggish} songs only have the older MusiCNN mood (the demo falls back to it for them)"))
        extra = sorted(have - want)
        if extra:
            out.append(("WARN", "songs that are not in the pool", f"{len(extra)}, e.g. {', '.join(extra[:5])}"))
        metas = {n[len("results/meta/"):-5] for n in names if n.startswith("results/meta/") and n.endswith(".json")}
        out.append(("PASS" if want <= metas else "WARN", "results/meta/<key>.json (titles, artists)", f"{len(metas & want)} of {len(want)}"))
        if "results/windows_cache.npz" in names:
            with np.load(io.BytesIO(z.read("results/windows_cache.npz")), allow_pickle=False) as wc:
                wkeys, owners = set(wc["keys"].tolist()), set(np.unique(wc["owner"]).tolist())
                covered = {str(wc["keys"][i]) for i in owners}
                facts["windows"] = int(len(wc["owner"]))
            ok = wkeys == want and covered == want
            out.append(("PASS" if ok else "FAIL", "results/windows_cache.npz (the ~30 s stretches)",
                        f"{facts['windows']} stretches of {len(covered)} songs" + ("" if ok else f"; {len(want - covered)} pool songs have none")))
        for n in NEED_RES:
            if n != "windows_cache.npz" or "results/windows_cache.npz" not in names:
                out.append(("PASS" if f"results/{n}" in names else "FAIL", f"results/{n}", "there" if f"results/{n}" in names else "MISSING"))
        local_lists = [n for n in POOL_LISTS if os.path.exists(os.path.join(here, n))]
        lists_missing = [n for n in local_lists if n not in names]
        out.append(("PASS" if local_lists and not lists_missing else "FAIL", "the pool lists (pool_*.csv)",
                    f"{len(local_lists) - len(lists_missing)} of {len(local_lists)}: {', '.join(n for n in local_lists if n in names)}"
                    + (f"; MISSING {', '.join(lists_missing)}" if lists_missing else "")))
        for n in NEED_TOP:
            out.append(("PASS" if n in names else "FAIL", n, "there" if n in names else "MISSING"))
        audio, secrets = [], []
        for info in z.infolist():
            data = z.read(info.filename)
            if is_audio(info.filename, data[:16]):
                audio.append(info.filename)
            secrets += [f"{info.filename}: {h}" for h in secret_hits(info.filename, data, env)]
        out.append(("PASS" if not audio else "FAIL", "no audio files", "none" if not audio else f"{len(audio)}: {', '.join(audio[:5])}"))
        out.append(("PASS" if not secrets else "FAIL", "no API keys, cookies or other secrets",
                    ("none found" + ("" if any((env if env is not None else os.environ).get(v) for v in KEY_VARS[:2])
                                     else " (key values unknown here: run  source env_keys.sh  first for the exact check)"))
                    if not secrets else "; ".join(secrets[:5])))
    facts["want"] = want
    return out, facts


README = """groovyeverywhere: demo data bundle
Made {when} from the pool of {songs} songs (YouTube only), {windows} stretches. Code: https://github.com/ryrxiaopang/groovyeverywhere (branch master).

Everything here is NUMBERS and text. No audio is kept anywhere in the project: songs are downloaded to a temporary folder, analysed and deleted.
No API keys, cookies or personal data are included. Song keys are youtube_<VIDEO ID> (https://www.youtube.com/watch?v=<VIDEO ID>).

FILES
results/<key>.npz         one per pool song, cut down to the arrays the recommender reads (load with numpy.load, allow_pickle=False)
  effnet_whole (1280,)        Sound: mean of the Discogs-EffNet embeddings over the whole song (one embedding per ~2 s patch, ~1 s apart)
  effnet_parts (3,1280)       Sound for 3 parts of 30 s centred at 25 / 50 / 75 % of the song (1 part for songs under 30 s)
  instruments_whole (40,), instruments_parts (3,40)   instrument likelihoods; class names in the model's .json (python models.py downloads it)
  emomusic_whole (2,), emomusic_parts (3,2)           mood from MusiCNN -> emoMusic: valence (happiness), arousal (energy), 1-9; the parts use this model
  cand_emomusic_vggish_whole (2,)                     mood from VGGish -> emoMusic, the CHOSEN mood model for whole songs (valence, arousal)
  rhythm_bpm, rhythm_confidence, rhythm_steadiness, rhythm_busyness   tempo, beat confidence, spread of beat gaps / mean gap, onsets per second
results/windows_cache.npz keys (N,) song keys; owner (W,) index into keys; vecs (W,1280) float16 RAW (not rescaled) Sound means of every stretch of
                          30 embeddings, a new one every 15 (match.window_means); raw = 1
results/sound_scale_youtube.npz   mu (1280,), sd (1280,): the Sound rescaling fitted on these pool songs; n = songs used; hash (see below)
results/index.csv         one row per pool song (status, group = search / style group, artist, title, page, listens ...)
results/meta/<key>.json   title, artist and other details read from YouTube
results/ai_tags.csv       AI-music tags (confirmed / likely / none) from tag_ai.py
results/pool_links.csv, results/link_alternatives.csv   whether each song's page works, and verified YouTube alternatives
results/song_languages.csv  english / chinese / korean / japanese / other / unknown (song_languages.py)
pool_*.csv                the pool lists: every row is in the pool unless its i_agree column is n
ai_block.txt, ai_keep.txt channels whose songs always leave the pool / always stay (they win over the tags)
DEMO_BUNDLE_README.txt    how to run the live demo on another machine with this bundle

HOW THE FILES MAP TO THE CODE
* The pool = results_index.pool_keys() (pool lists minus i_agree = n), only YouTube (blind_test.POOL_SOURCES), minus AI-tagged songs, ai_block.txt
  channels and dead links (blind_test.apply_quality; ai_keep.txt wins). The demo's entry point is recommend_song.recommend_query();
  blind_test.query_from_analysis() turns one song's .npz into the query.
* Sound (scoring.py, match.py): x_scaled = scoring.scale_sound(x, (mu, sd)) = (x - mu) / sd, then L2-normalise and take the cosine
  (scoring.cosine). match.library() does this for effnet_whole and effnet_parts, match.windows() for the stretches in windows_cache.npz;
  the best of whole / parts / stretches counts. scoring.to_percentile() turns similarities into rankings ("closer than 99.4% of the pool").
* List 2 (Sound + the features a visitor ticks): scoring.combine(), every chosen feature must reach the 65th percentile (feature_floor).
* similar.py is the older PostgreSQL demo: it reads the Sound numbers from the database and uses PLAIN cosine (no rescaling). It does not
  read these files and does not match the live demo; use scoring.py / match.py to reproduce the demo.

MODELS THAT MADE THE NUMBERS (Essentia, https://essentia.upf.edu/models, files downloaded by models.py)
  Sound           discogs-effnet-bs64-1 (feature-extractors/discogs-effnet)
  Instruments     mtg_jamendo_instrument-discogs-effnet-1
  Mood (chosen)   audioset-vggish-3 -> emomusic-audioset-vggish-2
  Mood (parts)    msd-musicnn-1 -> emomusic-msd-musicnn-2
  Rhythm          Essentia RhythmExtractor2013 (method multifeature) and OnsetRate, no neural model
  essentia-tensorflow 2.1b6.dev1438, analysis version {version}; audio decoded to mono, 16 kHz for the models, 44.1 kHz for rhythm.

REPRODUCING THE RESCALING
  X  = effnet_whole of every pool song in this bundle, as float64, shape (n, 1280)   (n = {n})
  mu = X.mean(axis=0)
  sd = (X.std(axis=0) + 1e-6) ** {power}       # NOT the standard deviation: spread to the power {power} (scoring.SOUND_SPREAD_POWER,
                                               # chosen on validation data; the table is in scoring.py). std is the population std (ddof = 0).
  This is scoring.fit_sound_scale(X). match.sound_scale() fits it the same way and stores it with
  hash = md5("\\n".join(sorted(keys)) + "|power={power}"). On a machine with this bundle unzipped the hash matches, so the file is used as is;
  if the pool changes, the scale is refitted automatically at the first start (a few seconds).

LICENCES
  The numbers were made with the Essentia models above, licensed CC BY-NC-SA 4.0: non-commercial use only, share alike, credit the Music
  Technology Group (UPF). The Essentia library is AGPL-3.0; the project code is MIT. Titles and links come from YouTube. See NOTICE.md in the repository.
"""


def finish(zip_path, out_path, facts, here=HERE, when=None):
    """Copy the bundle into out_path, adding the Sound scale and README.txt. Returns the README text."""
    import analyze, scoring
    path, mu, sd, h, n = scale_file(here)
    if h != expected_hash(facts["want"]):
        print("  !! the Sound scale was fitted on a different set of songs than the bundle holds: the receiving machine will refit it at the first start")
    text = README.format(when=when or time.strftime("%Y-%m-%d %H:%M"), songs=facts["songs"], windows=facts.get("windows", "?"), n=n,
                         power=scoring.SOUND_SPREAD_POWER, version=analyze.ANALYSIS_VERSION)
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            if info.filename not in ("README.txt", "results/sound_scale_youtube.npz"):
                dst.writestr(info, src.read(info.filename))
        dst.write(path, "results/" + os.path.basename(path))
        dst.writestr("README.txt", text)
    os.replace(tmp, out_path)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", help="the folder given to make_demo_bundle.py --out (its newest demo-bundle-*.zip is used), or the zip itself")
    ap.add_argument("--name", default="groovy-demo-bundle.zip", help="file name of the handoff zip, written next to the bundle")
    a = ap.parse_args()
    zip_path = newest_bundle(a.bundle)
    print(f"checking {zip_path}")
    results, facts = check(zip_path)
    for status, what, detail in results:
        print(f"  [{status}] {what}: {detail}")
    if any(s == "FAIL" for s, _, _ in results):
        sys.exit("!! fix the FAIL lines (usually: finish the analysis, run song_languages.py, then make_demo_bundle.py again); no handoff zip written")
    out = os.path.join(os.path.dirname(os.path.abspath(zip_path)), a.name)
    finish(zip_path, out, facts)
    print(f"written: {out} ({os.path.getsize(out) / 1e6:.0f} MB, {facts['songs']} songs). README.txt and results/sound_scale_youtube.npz added.")


if __name__ == "__main__":
    main()
