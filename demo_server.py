"""The live demo: paste a YouTube link, get similar songs from the pool. Runs on this laptop only.

  python demo_server.py                     # then open http://localhost:8765 in Chrome (the pool takes a minute to load: the page says when it is ready)
  python demo_server.py --k 8 --port 8800   # 8 songs per list; another port
  python demo_server.py --host 0.0.0.0      # let other devices on the same network open it (default: this computer only)

What the page offers (see DEMO.md for the run sheet for the day)
  1. paste a YouTube link  -> the server fetches the audio with yt-dlp, analyses it (about 15-30 s), finds the closest pool songs
  2. "capture a tab"       -> if YouTube blocks the download, the page records 30 s of a browser tab's audio instead (same analysis)
  3. "try a sample song"   -> a song that is already analysed: instant, works with no internet (the safety net)
Two lists come back: closest in SOUND, and SOUND + the things you choose (mood / rhythm / instruments, each at least the 65th percentile),
the same rules as the friends' test (recommend_song.recommend_query). The audio is deleted straight away (sources.temp_audio / a temporary folder);
only numbers are used. Logs (numbers and titles, no audio): results/demo_log.csv (every run, with the seconds each stage took) and
results/demo_feedback.csv (the "would you add it?" answers).

One request at a time (the models use a lot of memory): a second request while one runs gets "busy".
"""
import argparse, collections, csv, json, os, re, subprocess, sys, tempfile, threading, time
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RES = os.path.join(HERE, "results")
LOG = os.path.join(RES, "demo_log.csv")
FEEDBACK = os.path.join(RES, "demo_feedback.csv")
SAMPLES_CSV = os.path.join(HERE, "demo_samples.csv")        # optional: key,title,artist of the sample songs you want on the page
LOG_COLS = ["time", "visitor", "kind", "input", "title", "ok", "error", "source", "best_sound", "seconds_total", "seconds_lookup", "seconds_download", "seconds_analyse", "seconds_match", "detail"]
DEMO_CACHE = os.path.join(RES, "demo_cache")        # the NUMBERS of songs visitors brought (never audio): a repeat is instant and does not touch YouTube again
POOL_MSG = ("This is the closest we have, but it is not very close: our pool is mostly pop, R&B, indie and Asian pop, so songs from other styles "
            "(metal, classical, Latin, ...) find few real neighbours.")
CAPTURE_MSG = "The recording does not sound much like music (noise or a very quiet tab), so these matches may be weak."
FEEDBACK_COLS = ["time", "visitor", "token", "kind", "input", "list", "rec_key", "rec_title", "rating", "would_add"]
MAX_SECONDS = 600                       # a song, not a mix or a live stream
MAX_CLIP_BYTES = 25 * 1024 * 1024
VALID_FEATURES = ("mood", "rhythm", "instruments")
DEFAULT_FEATURES = "mood+rhythm+instruments"
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_ID = r"[A-Za-z0-9_-]{11}"


class DemoError(Exception):
    """An expected failure with a plain-language message; fallback='capture' makes the page offer the tab-capture route."""
    def __init__(self, code, message, fallback=None, status=200):
        super().__init__(message)
        self.code, self.message, self.fallback, self.status = code, message, fallback, status


def clean_visitor(x):
    """The anonymous visitor id the page makes up for each person at the booth (letters and digits only, 12 at most): it ties one person's songs and answers together, nothing else."""
    return re.sub(r"[^A-Za-z0-9]", "", str(x or ""))[:12]


def video_id(text):
    """The 11-character YouTube id in a pasted link (watch?v=, youtu.be/, shorts/, embed/, live/) or a bare id; None for anything else.
    Only the id is used afterwards (the server rebuilds the address itself), so nothing but YouTube can be fetched."""
    t = (text or "").strip()
    if re.fullmatch(_ID, t):
        return t
    if not t or " " in t:
        return None
    u = urlparse(t if "://" in t else "https://" + t)
    host = (u.hostname or "").lower()
    if host not in YT_HOSTS:
        return None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    else:
        vid = (parse_qs(u.query).get("v") or [""])[0]
        if not vid:
            m = re.match(rf"^/(?:shorts|embed|live|v)/({_ID})", u.path)
            vid = m.group(1) if m else ""
    return vid if re.fullmatch(_ID, vid) else None


def yt_id_of(link):
    m = re.search(rf"(?:v=|youtu\.be/|/shorts/|/embed/)({_ID})", link or "")
    return m.group(1) if m else ""


def _plain(o):
    """json default: numpy numbers and arrays to plain Python."""
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def shape(res, k):
    """The recommendation result as the page needs it: the first k of each list, with the YouTube id of every song."""
    out = dict(features=res.get("features", []), pool=res.get("pool"), best_sound=res.get("best_sound"),
               A_bar=res.get("A_bar"), B_bar=res.get("B_bar"))
    for name in ("A", "B"):
        out[name] = [dict(r, yt=yt_id_of(r.get("link"))) for r in (res.get(name) or [])[:k]]
    return out


# ---- the short "what we heard" strip under the starting song
SKIP_INSTRUMENTS = {"voice", "beat", "computer", "sampler"}              # not instruments a listener would name (scoring.py: left out for the same reason)
_NICE = {"acousticguitar": "acoustic guitar", "electricguitar": "electric guitar", "classicalguitar": "classical guitar", "electricpiano": "electric piano",
         "drummachine": "drum machine", "doublebass": "double bass", "bongo": "bongos", "synthesizer": "synth"}


def mood_label(valence, arousal):
    """Plain words for the emoMusic happiness / energy pair (each 1-9). '' when either is missing."""
    if valence is None or arousal is None or valence != valence or arousal != arousal:
        return ""
    lvl = lambda x: "high" if x >= 5.5 else "low" if x <= 4.5 else "mid"
    return {("high", "high"): "upbeat and energetic", ("low", "high"): "intense and dark", ("mid", "high"): "driving",
            ("high", "low"): "warm and relaxed", ("low", "low"): "sad and calm", ("mid", "low"): "calm and mellow",
            ("high", "mid"): "bright", ("low", "mid"): "melancholy", ("mid", "mid"): "balanced"}[(lvl(valence), lvl(arousal))]


def tempo_text(bpm, confidence):
    """'about 92 BPM', or 'tempo unclear' when the beat detector is not sure (rhythm is the weakest feature: never claim more than it knows)."""
    try:
        bpm, confidence = float(bpm), float(confidence)
    except (TypeError, ValueError):
        return "tempo unclear"
    return f"about {round(bpm)} BPM" if bpm == bpm and 40 <= bpm <= 220 and confidence >= 2.0 else "tempo unclear"


def top_instruments(inst, names, n=3):
    """The n strongest instruments by name (singing, beats and samplers left out)."""
    pairs = sorted(zip(inst, names), key=lambda x: -float(x[0]))
    return [_NICE.get(nm, nm.replace("_", " ")) for _, nm in pairs if nm not in SKIP_INSTRUMENTS][:n]


def build_heard(q, names):
    """What the models heard in a query (from blind_test.query_from_analysis): mood words, the two mood numbers, tempo, main instruments."""
    v, a = (q.get("va_vg") if q.get("va_vg") is not None else [float("nan")] * 2)
    if v != v or a != a:
        v, a = q["va_mc"]
    v, a = float(v), float(a)
    return dict(mood=mood_label(v, a), happiness=round(v, 1), energy=round(a, 1), tempo=tempo_text(q.get("bpm"), q.get("confidence")),
                instruments=top_instruments(q["inst"], names))


def _csv_safe(v):
    """Text typed by visitors or taken from YouTube can start with = + - @ and then run as a formula when the log is opened in Excel: a leading ' makes it plain text."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def append_row(path, cols, row):
    """Add one row to a log. A log that cannot be written (full disk, file open in Excel) is reported on the console and never costs a visitor their result."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: _csv_safe(v) for k, v in row.items()})
    except OSError as e:
        print(f"!! could not write {os.path.basename(path)}: {e}")


class Backends:
    """Everything that needs Essentia, the models, the pool or the network. The offline test replaces this class with a fake."""

    def warm(self):
        import blind_test as bt
        return len(bt.pool()["key"])

    def weak_cosine(self):
        import blind_test as bt
        return bt.WEAK_COSINE

    def info(self, vid):
        cmd = ["yt-dlp", "-q", "--no-warnings", "--no-playlist", "--force-ipv4", "--skip-download", "--dump-single-json"]
        if os.environ.get("HG_YT_COOKIES_FILE"):
            cmd += ["--cookies", os.environ["HG_YT_COOKIES_FILE"]]
        try:
            p = subprocess.run(cmd + [f"https://www.youtube.com/watch?v={vid}"], capture_output=True, timeout=45)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise DemoError("lookup_failed", f"YouTube did not answer in time ({type(e).__name__}).", fallback="capture")
        if p.returncode != 0:
            msg = (p.stderr or b"").decode("utf-8", "replace").strip().lower()
            raise DemoError("lookup_failed", "YouTube would not let this computer read that video"
                            + (" (it needs a sign-in)." if "sign in" in msg or "bot" in msg else "."), fallback="capture")
        d = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
        duration = float(d.get("duration") or 0)
        if d.get("is_live") or d.get("live_status") in ("is_live", "is_upcoming") or duration <= 0:
            raise DemoError("not_a_song", "That is a live stream or a premiere, not a finished song. Pick a normal video of the song.")
        return dict(title=d.get("title") or "", channel=d.get("channel") or d.get("uploader") or "", duration=duration)

    def download(self, vid):
        """A context manager that yields the path of the downloaded audio and deletes it afterwards."""
        import sources
        return sources.temp_audio(dict(source="youtube", download_allowed=True, download_url=f"https://www.youtube.com/watch?v={vid}"))

    def analyse_full(self, path, fast=True, max_seconds=None):
        """(features, timings per step). fast = skip the models the app never reads (same numbers for everything it does read); max_seconds = only the middle of a long song."""
        import analyze
        return analyze.analyse(path, fast=fast, max_seconds=max_seconds)

    def analyse(self, path):
        """The live analysis. DEFAULT = the full pipeline on the whole song, exactly as the pool songs were analysed (user decision 12 Oct: accuracy first, a longer wait is fine).
        --fast (skip the unread models: same numbers, quicker) and --excerpt N (only the middle of a long song: slightly different numbers) are opt-in."""
        feats, self.last_timings = self.analyse_full(path, os.environ.get("HG_DEMO_FAST") == "1", int(os.environ.get("HG_DEMO_EXCERPT", "0") or 0) or None)
        return feats

    def analyse_clip(self, wav_path):
        import capture_server
        return capture_server.clip_query(wav_path)           # the same way the blind test turns a clip into numbers: (signal check, feats or None)

    def query(self, feats):
        import blind_test as bt
        return bt.query_from_analysis(feats)

    def search(self, q, n=5):
        """Candidates for a typed song name: YouTube's own search through yt-dlp (no API quota): single songs of 1-10 minutes, official-looking uploads first."""
        import build_youtube as by
        cmd = ["yt-dlp", "--flat-playlist", "-j", "--no-warnings", "--force-ipv4", f"ytsearch12:{q}"]
        if os.environ.get("HG_YT_COOKIES_FILE"):
            cmd[1:1] = ["--cookies", os.environ["HG_YT_COOKIES_FILE"]]
        code, so, se = _run(cmd, 35)
        if code != 0 and not so.strip():
            raise DemoError("search_failed", "YouTube search did not answer. Paste the song's link instead, or capture it from a tab.")
        out, seen = [], set()
        for line in so.splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            vid, title, dur = d.get("id") or "", d.get("title") or "", d.get("duration") or 0
            if not re.fullmatch(_ID, vid) or vid in seen or (not dur or not 60 <= dur <= MAX_SECONDS) or by.NOT_A_SONG.search(title):
                continue
            chan = d.get("channel") or d.get("uploader") or ""
            seen.add(vid)
            out.append(dict(id=vid, title=title, channel=chan, seconds=dur, views=d.get("view_count") or 0,
                            official=bool(re.search(r"official|vevo|- topic", f"{title} {chan}", re.I))))
        out.sort(key=lambda r: not r["official"])           # stable: official-looking first, YouTube's own order otherwise
        return out[:n]

    def _stored(self, vid):
        for p in (os.path.join(RES, f"youtube_{vid}.npz"), os.path.join(DEMO_CACHE, f"{vid}.npz")):
            if os.path.exists(p):
                return p
        return None

    def known(self, vid):
        """True when this video's numbers are already stored (it is in the pool, or a visitor brought it before)."""
        return self._stored(vid) is not None

    def known_query(self, vid):
        import numpy as np, blind_test as bt
        from results_index import read_meta
        p = self._stored(vid)
        with np.load(p, allow_pickle=False) as d:
            q = bt.query_from_analysis(dict(d))
        meta = read_meta(f"youtube_{vid}") or {}
        side = os.path.join(DEMO_CACHE, f"{vid}.json")
        if not meta and os.path.exists(side):
            meta = json.load(open(side, encoding="utf-8"))
        return q, meta

    def cache_put(self, vid, feats, meta):
        """Keep the analysed NUMBERS (never the audio) of a visitor's song so that the next visitor with the same song is served at once."""
        import numpy as np
        arrays = {}
        for k, v in feats.items():
            try:
                a = np.asarray(v)
                if a.dtype != object:
                    arrays[k] = a
            except Exception:
                pass
        os.makedirs(DEMO_CACHE, exist_ok=True)
        # written under temporary names and renamed, the .npz LAST (known() looks for it): a kill half-way never leaves a broken entry that fails for every later visitor
        side, tmp_side = os.path.join(DEMO_CACHE, f"{vid}.json"), os.path.join(DEMO_CACHE, f"{vid}.tmp.json")
        with open(tmp_side, "w", encoding="utf-8") as f:
            json.dump(dict(title=meta.get("title", ""), artist=meta.get("artist", ""), duration=meta.get("duration", 0)), f, ensure_ascii=False)
        os.replace(tmp_side, side)
        tmp_npz = os.path.join(DEMO_CACHE, f"{vid}.tmp.npz")
        np.savez_compressed(tmp_npz, **arrays)
        os.replace(tmp_npz, os.path.join(DEMO_CACHE, f"{vid}.npz"))

    def heard(self, q):
        if not hasattr(self, "_names"):
            import evaluate
            self._names = evaluate.class_names("instruments", 40)
        return build_heard(q, self._names)

    def sample_query(self, key):
        import numpy as np, blind_test as bt
        from results_index import read_meta
        with np.load(os.path.join(RES, f"{key}.npz")) as d:
            return bt.query_from_analysis(dict(d)), read_meta(key) or {}

    def recommend(self, q, meta, k, features):
        import recommend_song
        return recommend_song.recommend_query(q, meta, k, features)

    def samples(self):
        """[{key, title, artist}] of already analysed songs for the sample buttons: demo_samples.csv if it exists, else the most viewed pool song
        of each of the biggest style groups."""
        import blind_test as bt
        P = bt.pool()
        have = {k: (t, a) for k, t, a in zip(P["key"], P["title"], P["artist_name"])}
        if os.path.exists(SAMPLES_CSV):
            with open(SAMPLES_CSV, encoding="utf-8-sig") as f:
                rows = [r for r in csv.DictReader(f) if r.get("key") in have and os.path.exists(os.path.join(RES, f"{r['key']}.npz"))]
            return [dict(key=r["key"], title=r.get("title") or have[r["key"]][0], artist=r.get("artist") or have[r["key"]][1]) for r in rows]
        return auto_samples(P["key"], P["title"], P["artist_name"], P["group"], P["listens"])


class FakeBackends:
    """PRACTICE MODE (python demo_server.py --fake): canned matches, no models, no pool, no YouTube. Use it to test the page, Chrome reaching localhost inside WSL, and the
    tab-capture window while the machine is busy. The page shows an orange banner, because these matches are made up and must never be shown as real results."""

    def warm(self):
        time.sleep(1.0)
        return 8000

    def weak_cosine(self):
        return 0.45

    def info(self, vid):
        time.sleep(0.5)
        return dict(title=f"Practice song {vid[:4]}", channel="Practice channel", duration=200.0)

    def download(self, vid):
        import contextlib

        @contextlib.contextmanager
        def cm():
            time.sleep(1.0)
            yield "/dev/null"
        return cm()

    def analyse(self, path):
        time.sleep(1.5)
        return dict(fake=1)

    def analyse_clip(self, wav_path):
        time.sleep(1.0)
        return dict(rms_db=-20.0, silent_share=0.0), (None if os.path.getsize(wav_path) < 2000 else dict(fake=2))

    def query(self, feats):
        return dict(fake=feats)

    def sample_query(self, key):
        return dict(fake=3), dict(title="Practice sample", artist="Nobody")

    def search(self, q, n=5):
        time.sleep(0.6)
        return [dict(id=f"{w}{i:010d}"[:11], title=f"{q.title()} (Official Audio)" if i == 0 else f"{q.title()} - version {i + 1}", channel=f"Practice channel {i + 1}",
                     seconds=180 + 7 * i, views=1_000_000 // (i + 1), official=i == 0) for i, w in enumerate("abcde")][:n]

    def known(self, vid):
        return vid.startswith("a")                            # the first practice candidate shows the "instant" path

    def known_query(self, vid):
        return dict(fake=4), dict(title="Practice song from the pool", artist="Practice artist", duration=190)

    def heard(self, q):
        return dict(mood="warm and relaxed", happiness=6.4, energy=4.1, tempo="about 96 BPM", instruments=["piano", "acoustic guitar", "strings"])

    def recommend(self, q, meta, k, features):
        n_b = 2 + len([f for f in features.split("+") if f])
        def row(i, w):
            return dict(key=f"practice_{w}{i}", title=f"Practice match {i + 1}", artist=f"Practice artist {i + 1}", link="", sound=88 - 3 * i, mood=72 + i, rhythm=61,
                        instruments=77, match=92 - 2 * i, popularity="few plays", ai="")
        return dict(A=[row(i, "a") for i in range(max(k, 6))], B=[row(i, "b") for i in range(n_b)], features=["sound"] + features.split("+"), pool=8000,
                    best_sound=0.9, A_bar=70.0, B_bar=65.0)

    def samples(self):
        return [dict(key="practice_s1", title="Practice sample one", artist="Nobody"), dict(key="practice_s2", title="Practice sample two", artist="Nobody")]


def auto_samples(keys, titles, artists, groups, listens, n=6):
    """The most viewed song of each of the n biggest style groups (one per group), as a safety net when demo_samples.csv does not exist."""
    count = collections.Counter(groups)
    best = {}
    for i, g in enumerate(groups):
        v = listens[i] if listens[i] == listens[i] else -1
        if g not in best or v > best[g][0]:
            best[g] = (v, i)
    out = []
    for g, _ in count.most_common(n):
        i = best[g][1]
        out.append(dict(key=keys[i], title=titles[i], artist=artists[i]))
    return out


class Demo:
    """The demo's state and logic, separate from the HTTP layer so it can be tested without a network."""

    def __init__(self, backends=None, k=6, log=LOG, feedback=FEEDBACK):
        self.b = backends or Backends()
        self.k, self.log, self.feedback = k, log, feedback
        self.lock = threading.Lock()
        self.ready, self.pool_size, self.warm_error = False, 0, ""
        self.stage, self.since = "", 0.0
        self.last = collections.OrderedDict()                # token -> (query, meta, input description): kept for "refine"
        self.counter = 0
        self.samples_cache = None
        self.fake = False                                     # practice mode (canned matches): the page shows a banner so it can never be mistaken for the real thing

    # ---- start-up
    def warm(self):
        try:
            self.pool_size = self.b.warm()
            self.ready = True
        except BaseException as e:                            # a missing pool must show on the page, not kill the server
            self.warm_error = f"{type(e).__name__}: {e}"[:200]

    def status(self):
        busy = self.lock.locked()
        return dict(ready=self.ready, pool=self.pool_size, error=self.warm_error, busy=busy, stage=self.stage if busy else "", fake=self.fake,
                    elapsed=round(time.time() - self.since, 1) if busy else 0)

    def _stage(self, s):
        self.stage = s

    # ---- one job at a time
    def _job(self, kind, ident, fn, visitor=""):
        """Run fn(times) under the lock; returns (http status, body dict). Every run is logged."""
        if not self.ready:
            return 503, dict(error="warming_up", message=self.warm_error or "The song pool is still loading: wait for the green light at the top of the page.")
        if not self.lock.acquire(blocking=False):
            return 429, dict(error="busy", message="Another song is being analysed. Try again in a moment.")
        t0, times, title, err, src, best = time.time(), {}, "", "", "", ""
        self.since = time.time()
        try:
            body = fn(times)
            title = (body.get("input") or {}).get("title", "")
            src, best = body.get("source", ""), (body.get("results") or {}).get("best_sound", "")
            return 200, body
        except DemoError as e:
            err = e.code
            return e.status, dict(error=e.code, message=e.message, fallback=e.fallback)
        except BaseException as e:                            # one bad request must never stop the server
            err = f"internal: {type(e).__name__}"
            return 500, dict(error="internal", message=f"Something went wrong inside the demo ({type(e).__name__}: {str(e)[:120]}).", fallback="capture" if kind == "link" else None)
        finally:
            self.stage = ""
            self.lock.release()
            append_row(self.log, LOG_COLS, dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), visitor=clean_visitor(visitor), kind=kind, input=ident, title=title, ok=int(not err),
                                                error=err, source=src, best_sound=best if best == "" else round(float(best), 3), seconds_total=round(time.time() - t0, 1),
                                                detail=times.get("_detail", ""), **{f"seconds_{k}": round(v, 1) for k, v in times.items() if not k.startswith("_")}))

    def _finish(self, kind, ident, q, meta, features, times, extra_input, source="new"):
        t = time.time()
        self._stage("finding matches")
        res = shape(self.b.recommend(q, meta, self.k, features), self.k)
        times["match"] = time.time() - t
        try:
            heard = self.b.heard(q)
        except BaseException:                                # the strip is a bonus: never let it break a result
            heard = {}
        self.counter += 1
        token = f"{int(time.time())}-{self.counter}"
        self.last[token] = (q, meta, dict(kind=kind, id=ident))
        while len(self.last) > 8:
            self.last.popitem(last=False)
        body = dict(ok=True, token=token, input=dict(kind=kind, id=ident, **extra_input), results=res, heard=heard, source=source)
        bs = res.get("best_sound")
        if bs is not None and bs < self.b.weak_cosine():           # nothing in the pool is really close: say so instead of presenting weak matches as good
            body["warning"] = CAPTURE_MSG if kind == "capture" else POOL_MSG
        return body

    # ---- the three ways in
    def from_link(self, text, visitor=""):
        vid = video_id(text)
        if not vid:
            return 400, dict(error="not_youtube", message="That does not look like a YouTube link. Paste the address of a video (youtube.com/watch?v=... or youtu.be/...).")

        def run(times):
            known = getattr(self.b, "known", None)
            stored = None
            if known and known(vid):                          # in the pool, or brought by an earlier visitor: no YouTube, no download, no analysis
                t = time.time(); self._stage("loading the song's stored numbers")
                try:
                    stored = self.b.known_query(vid)
                except BaseException:                         # an unreadable stored file: analyse the song again instead of failing every time
                    stored = None
                times["lookup"] = time.time() - t
            if stored:
                q, meta = stored
                ttl, art = meta.get("title") or vid, meta.get("artist") or ""
                return self._finish("link", vid, q, dict(title=ttl, artist=art), DEFAULT_FEATURES, times,
                                    dict(title=ttl, artist=art, seconds=meta.get("duration") or 0), source="stored")
            t = time.time(); self._stage("looking up the song")
            info = self.b.info(vid)
            times["lookup"] = time.time() - t
            if info["duration"] and info["duration"] > MAX_SECONDS:
                raise DemoError("too_long", f"That video is {int(info['duration'] // 60)} minutes long. Pick a single song (under {MAX_SECONDS // 60} minutes).")
            t = time.time(); self._stage("downloading the audio")
            phase = "download"
            try:
                with self.b.download(vid) as path:
                    times["download"] = time.time() - t
                    phase = "analysis"
                    t = time.time(); self._stage("listening to it (analysing)")
                    feats = self.b.analyse(path)
                    times["analyse"] = time.time() - t
                    tm = getattr(self.b, "last_timings", None)
                    if tm:                                          # where the analysis time went (decode / effnet / mood / rhythm ...): visible in the log, for the booth laptop
                        times["_detail"] = ", ".join(f"{k} {v:.1f}" for k, v in tm.items() if k != "total" and v >= 0.05)
            except DemoError:
                raise
            except BaseException as e:
                if phase == "analysis":
                    raise DemoError("analysis_failed", "The song downloaded but could not be analysed" + (f" ({str(e)[:90]})" if str(e) else "") + ". Try the tab capture.", fallback="capture")
                raise DemoError("download_failed", "YouTube blocked the download for this video" + (f" ({str(e)[:90]})" if str(e) else "") + ".", fallback="capture")
            put = getattr(self.b, "cache_put", None)
            if put:
                try:
                    put(vid, feats, dict(title=info["title"], artist=info["channel"], duration=info["duration"]))
                except BaseException:                         # a full disk or an odd value must not cost the visitor their result
                    pass
            q = self.b.query(feats)
            return self._finish("link", vid, q, dict(title=info["title"], artist=info["channel"]), DEFAULT_FEATURES, times,
                                dict(title=info["title"], artist=info["channel"], seconds=info["duration"]))
        return self._job("link", vid, run, visitor)

    def search(self, text, visitor=""):
        """Candidates for a typed song name (not a 'job': it only reads YouTube's search page). Each candidate says whether its numbers are stored already."""
        q = re.sub(r"\s+", " ", (text or "").strip())[:90]
        if len(q) < 2:
            return 400, dict(error="empty", message="Type a song name, and the artist if you can.")
        if not self.ready:
            return 503, dict(error="warming_up", message=self.warm_error or "The song pool is still loading: wait for the green light at the top of the page.")
        t0, err, res = time.time(), "", []
        try:
            res = self.b.search(q, 5)
            known = getattr(self.b, "known", lambda v: False)
            for r in res:
                r["instant"] = bool(known(r["id"]))
            return 200, dict(ok=True, query=q, results=res)
        except DemoError as e:
            err = e.code
            return 200, dict(ok=False, error=e.code, message=e.message, query=q, results=[])
        except BaseException as e:
            err = f"internal: {type(e).__name__}"
            return 200, dict(ok=False, error="search_failed", message="YouTube search did not answer. Paste the song's link instead.", query=q, results=[])
        finally:
            append_row(self.log, LOG_COLS, dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), visitor=clean_visitor(visitor), kind="search", input=q, title=f"{len(res)} results", ok=int(not err), error=err,
                                                seconds_total=round(time.time() - t0, 1)))

    def from_clip(self, wav_bytes, seconds=30, visitor=""):
        if not wav_bytes or len(wav_bytes) > MAX_CLIP_BYTES or wav_bytes[:4] != b"RIFF":
            return 400, dict(error="bad_clip", message="The recording did not arrive as a WAV file. Try the capture again.")

        def run(times):
            t = time.time(); self._stage("listening to the recording (analysing)")
            with tempfile.TemporaryDirectory(prefix="hg_demo_") as d:          # audio deleted when this block ends
                p = os.path.join(d, "clip.wav")
                with open(p, "wb") as f:
                    f.write(wav_bytes)
                sig, feats = self.b.analyse_clip(p)
            times["analyse"] = time.time() - t
            if feats is None:
                raise DemoError("silent", "The recording was (almost) silent. In the sharing window choose the tab with the song and tick \"Also share tab audio\".")
            q = self.b.query(feats)
            return self._finish("capture", "tab", q, {}, DEFAULT_FEATURES, times, dict(title="your recording", artist="", seconds=seconds))
        return self._job("capture", "tab", run, visitor)

    def get_samples(self):
        if not self.ready:
            return []
        if self.samples_cache is None:
            try:
                self.samples_cache = self.b.samples()
            except BaseException:
                self.samples_cache = []
        return self.samples_cache

    def from_sample(self, key, visitor=""):
        known = {s["key"]: s for s in self.get_samples()}
        if key not in known:
            return 400, dict(error="unknown_sample", message="That sample song is not on the list.")

        def run(times):
            t = time.time(); self._stage("loading the stored numbers")
            q, meta = self.b.sample_query(key)
            times["lookup"] = time.time() - t
            s = known[key]
            return self._finish("sample", key, q, meta, DEFAULT_FEATURES, times, dict(title=s["title"], artist=s["artist"]))
        return self._job("sample", key, run, visitor)

    def refine(self, token, features):
        feats = [f for f in (features or "").split("+") if f in VALID_FEATURES]
        if token not in self.last or not feats:
            return 400, dict(error="bad_request", message="Unknown result or no feature chosen.")
        q, meta, inp = self.last[token]

        def run(times):
            res = shape(self.b.recommend(q, meta, self.k, "+".join(feats)), self.k)
            return dict(ok=True, token=token, input=dict(inp), results=res)
        return self._job("refine", token, run)

    def rate(self, data):
        token, which = str(data.get("token", "")), str(data.get("list", ""))
        rating, add = data.get("rating"), str(data.get("would_add", "")).lower()
        if token not in self.last or which not in ("A", "B") or add not in ("yes", "no", "") or not (rating in (None, "") or rating in (1, 2, 3, 4, 5)):
            return 400, dict(error="bad_request", message="Could not save that answer.")
        inp = self.last[token][2]
        append_row(self.feedback, FEEDBACK_COLS, dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), visitor=clean_visitor(data.get("visitor")), token=token, kind=inp["kind"], input=inp["id"], list=which,
                                                       rec_key=str(data.get("rec_key", ""))[:60], rec_title=str(data.get("rec_title", ""))[:120],
                                                       rating=rating if rating is not None else "", would_add=add))
        return 200, dict(ok=True)


def make_handler(demo, html_path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            b = body if isinstance(body, bytes) else (json.dumps(body, default=_plain) if not isinstance(body, str) else body).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

        def _length(self, limit):
            """The Content-Length of the request, 0..limit; anything else (negative, not a number, too big) is refused before a single byte is read."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise DemoError("bad_request", "Could not read the request.", status=400)
            if n < 0:
                raise DemoError("bad_request", "Could not read the request.", status=400)
            if n > limit:
                raise DemoError("too_big", "Request too large.", status=413)
            return n

        def _json_body(self, limit=20000):
            n = self._length(limit)
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise DemoError("bad_request", "Could not read the request.", status=400)
            return d if isinstance(d, dict) else {}

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                with open(html_path, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/status":
                return self._send(200, demo.status())
            if path == "/api/samples":
                return self._send(200, demo.get_samples())
            self._send(404, {})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/capture":
                    n = self._length(MAX_CLIP_BYTES)
                    code, body = demo.from_clip(self.rfile.read(n), visitor=(parse_qs(u.query).get("visitor") or [""])[0])
                else:
                    d = self._json_body()
                    if u.path == "/api/link":
                        code, body = demo.from_link(d.get("url"), d.get("visitor"))
                    elif u.path == "/api/search":
                        code, body = demo.search(d.get("q"), d.get("visitor"))
                    elif u.path == "/api/sample":
                        code, body = demo.from_sample(str(d.get("key", "")), d.get("visitor"))
                    elif u.path == "/api/refine":
                        code, body = demo.refine(str(d.get("token", "")), str(d.get("features", "")))
                    elif u.path == "/api/rate":
                        code, body = demo.rate(d)
                    else:
                        code, body = 404, {}
            except DemoError as e:
                code, body = e.status, dict(error=e.code, message=e.message)
            self._send(code, body)
    return H


def make_server(demo, host="127.0.0.1", port=8765, html_path=os.path.join(HERE, "demo.html")):
    return ThreadingHTTPServer((host, port), make_handler(demo, html_path))


def summary(log=LOG, feedback=FEEDBACK):
    """Print what the rehearsal / the demo day produced: runs and failures, typical seconds per stage, and the 'would add' answers per list."""
    import statistics
    if not os.path.exists(log):
        print("no runs logged yet (results/demo_log.csv)")
        return
    rows = list(csv.DictReader(open(log, encoding="utf-8-sig")))
    runs = [r for r in rows if r["kind"] in ("link", "capture", "sample")]
    print(f"{len(runs)} runs: " + ", ".join(f"{k} {sum(r['kind'] == k for r in runs)}" for k in ("link", "capture", "sample")))
    vis = collections.defaultdict(list)
    for r in runs:
        if r.get("visitor") and r["ok"] == "1":
            vis[r["visitor"]].append(r)
    if vis:
        print(f"{len(vis)} visitors with at least one song, {sum(len(v) for v in vis.values()) / len(vis):.1f} songs each on average (each song gets its own lists: songs are never blended)")
    bad = collections.Counter(r["error"] for r in runs if r["ok"] == "0")
    print("failures: " + (", ".join(f"{k} x{v}" for k, v in bad.most_common()) if bad else "none"))
    for kind in ("link", "capture", "sample"):
        ok = [r for r in runs if r["kind"] == kind and r["ok"] == "1"]
        if ok:
            def med(col):
                v = [float(r[col]) for r in ok if r.get(col) not in (None, "")]
                return f"{statistics.median(v):.0f}" if v else "-"
            slow = max(float(r["seconds_total"] or 0) for r in ok)
            print(f"  {kind}: median {med('seconds_total')} s in total (lookup {med('seconds_lookup')}, download {med('seconds_download')}, "
                  f"analyse {med('seconds_analyse')}, match {med('seconds_match')}); slowest {slow:.0f} s; {len(ok)} worked")
    if os.path.exists(feedback):
        fb = list(csv.DictReader(open(feedback, encoding="utf-8-sig")))
        for which, name in (("A", "closest in sound"), ("B", "sound + features")):
            sub = [r for r in fb if r["list"] == which and r["would_add"] in ("yes", "no")]
            if sub:
                print(f"  '{name}': would add {sum(r['would_add'] == 'yes' for r in sub)} of {len(sub)} ({100 * sum(r['would_add'] == 'yes' for r in sub) / len(sub):.0f}%)")


def benchmark(text, b=None, printer=print):
    """How fast is analysis on THIS machine, and what do the speed-ups cost? Downloads one song (or finds it by name), analyses it in four ways and compares the recommendations
    with those of the full analysis (the way the pool songs were analysed). Run it on the booth laptop."""
    b = b or Backends()
    vid, title = video_id(text), text
    if not vid:
        found = b.search(text, 1)
        if not found:
            raise SystemExit(f"nothing found on YouTube for {text!r}")
        vid, title = found[0]["id"], found[0]["title"]
    printer(f"song: {title} ({vid})")
    t = time.time(); b.warm(); printer(f"pool loaded in {time.time() - t:.0f} s (this happens once, when the server starts)")
    modes = [("full, as the pool songs were analysed", False, None), ("fast: skips models the demo never reads", True, None),
             ("fast + only the middle 90 s", True, 90), ("fast + only the middle 60 s", True, 60)]
    rows, base = [], None
    t_dl = time.time()
    with b.download(vid) as path:
        printer(f"download + conversion to mp3: {time.time() - t_dl:.1f} s (yt-dlp and ffmpeg: it depends on the connection and the CPU, not on the models)")
        for label, fast, secs in modes:
            t = time.time(); feats, tm = b.analyse_full(path, fast, secs); took = time.time() - t
            q = b.query(feats)
            top = [r["key"] for r in b.recommend(q, {}, 10, DEFAULT_FEATURES)["A"][:10]]
            whole = np.asarray(q["whole"], float)
            if base is None:
                base = (top, whole)
            cos = float(whole @ base[1] / (np.linalg.norm(whole) * np.linalg.norm(base[1]) + 1e-12))
            rows.append(dict(mode=label, seconds=took, same=len(set(top) & set(base[0])), cos=cos, detail=", ".join(f"{k} {v:.1f}" for k, v in tm.items() if k != "total" and v >= 0.05)))
    printer(f"\n{'way of analysing':42s} {'seconds':>8s}  {'same top-10 as full':>20s}  {'Sound match to full':>20s}   where the time went")
    for r in rows:
        printer(f"{r['mode']:42s} {r['seconds']:8.1f}  {str(r['same']) + ' of 10':>20s}  {r['cos']:20.4f}   {r['detail']}")
    full, fast = rows[0], rows[1]
    full = dict(full, seconds=max(full['seconds'], 1e-9))
    printer(f"\nfast mode saves {100 * (1 - fast['seconds'] / full['seconds']):.0f}% and should give the SAME top 10 ({fast['same']} of 10 here)"
            + ("" if fast["same"] >= 9 else "  !! it should be identical: tell me about this output")
            + "\nThe demo uses the FULL analysis unless you start it with --fast or --excerpt (you chose accuracy over speed): the rows below are for information.")
    for r in rows[2:]:
        ok = r["same"] >= 8
        printer(f"{r['mode']}: saves {100 * (1 - r['seconds'] / full['seconds']):.0f}% but keeps {r['same']} of 10 matches: " + ("acceptable if you need the speed (start the demo with --excerpt "
                + ("90" if "90" in r["mode"] else "60") + ")" if ok else "too much changes: keep whole songs"))
    printer("One song is one data point: run it for 3 songs of different styles before deciding on an excerpt.")
    return rows


def _run(cmd, timeout=45):
    """(return code, stdout, stderr) of a command, never raising: (-1, '', reason) when it could not run."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, "", f"{type(e).__name__}"


def doctor(port=8765, run=_run, which=None, meminfo="/proc/meminfo", here=HERE, jobs=None):
    """The pre-flight check for the demo: a list of (level, text), level 'ok' / 'warn' / 'fail'. Everything that can fail on the day is checked here, in a minute."""
    import shutil, socket, datetime, importlib.util
    which = which or shutil.which
    out, add = [], (lambda lvl, t: out.append((lvl, t)))
    add("ok", f"Python {sys.version.split()[0]}")
    code, so, _ = run(["yt-dlp", "--version"], 20)
    if code != 0:
        add("fail", "yt-dlp is not installed or does not run: pip install -U yt-dlp")
    else:
        ver = so.strip()
        try:
            age = (datetime.date.today() - datetime.datetime.strptime(ver[:10], "%Y.%m.%d").date()).days
        except ValueError:
            age = None
        add("warn" if age is not None and age > 60 else "ok", f"yt-dlp {ver}" + (f" ({age} days old: pip install -U yt-dlp, an old one is the most common reason for a blocked download)" if age and age > 60 else ""))
    add("ok" if which("ffmpeg") else "fail", "ffmpeg found" if which("ffmpeg") else "ffmpeg is missing: yt-dlp cannot make the audio file without it")
    add("ok" if importlib.util.find_spec("essentia") else "fail", "Essentia is installed" if importlib.util.find_spec("essentia") else "Essentia is not importable here: activate the project venv (source .venv/bin/activate)")
    for name, why in (("results/ai_tags.csv", "the AI filter has no tags"), ("results/index.csv", "no analysed songs are listed")):
        add("ok" if os.path.exists(os.path.join(here, name)) else "fail", f"{name} exists" if os.path.exists(os.path.join(here, name)) else f"{name} is missing: {why}")
    lists = [fn for fn in __import__("results_index").POOL_LISTS if os.path.exists(os.path.join(here, fn))]
    add("ok" if lists else "fail", f"{len(lists)} pool list file(s) found" if lists else "no pool_*.csv list found")
    try:
        avail = next(int(l.split()[1]) for l in open(meminfo) if l.startswith("MemAvailable")) / 1024 / 1024
        add("ok" if avail >= 8 else "warn" if avail >= 4 else "fail", f"{avail:.1f} GB of memory free" + ("" if avail >= 8 else ": close other programs and stop analysis jobs; the pool and models need about 6 GB"))
    except (OSError, StopIteration, ValueError):
        add("warn", "could not read the free memory")
    try:
        import models
        missing = [n for n in ("effnet", "musicnn", "instruments", "emomusic", "vggish", "emomusic_vggish") if not models.available(n)]
        add("fail" if missing else "ok", f"analysis models missing: {', '.join(missing)} (run  python models.py, about 60 MB)" if missing else "the analysis models are present")
    except Exception as e:
        add("warn", f"could not check the models ({type(e).__name__})")
    if lists:
        from results_index import pool_keys
        keys = pool_keys(here)
        have = sum(os.path.exists(os.path.join(here, "results", f"{k}.npz")) for k in keys)
        add("ok" if keys and have >= 0.98 * len(keys) else "fail", f"{have} of {len(keys)} pool songs have their numbers" + ("" if keys and have >= 0.98 * len(keys) else " (on a booth laptop: unzip the demo bundle inside the project folder; on the desktop: finish the analysis)"))
    running = other_jobs_running() if jobs is None else jobs
    add("warn" if running else "ok", "an analysis / pool-growing job is running: the demo will be slow (stop it first)" if running else "no analysis job is running")
    try:
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", port))
        add("ok", f"port {port} is free")
    except OSError:
        add("fail", f"port {port} is in use: a demo (maybe a practice-mode one, --fake) is still running in another terminal. Find it with  pgrep -af \"[d]emo_server\"  and stop it with  kill PID  (or start this one with --port 8800)")
    t = time.time()
    code, so, se = run(["yt-dlp", "-q", "--no-warnings", "--no-playlist", "--force-ipv4", "--skip-download", "--print", "%(title)s", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"], 45)
    if code == 0 and so.strip():
        add("ok", f"YouTube answered in {time.time() - t:.0f} s ({so.strip().splitlines()[0][:40]})")
    else:
        reason = (se.strip().splitlines() or ["no answer"])[-1][:110]
        add("warn", f"YouTube would not answer ({reason}): the paste-a-link route may fail; the tab capture and the samples still work")
    sp = os.path.join(here, "demo_samples.csv")
    if os.path.exists(sp):
        n = max(0, sum(1 for _ in open(sp, encoding="utf-8-sig")) - 1)
        add("ok", f"demo_samples.csv has {n} song(s) (only for the operator's safety net: http://localhost:{port or 8765}/?samples=1)")
    else:
        add("ok", "no demo_samples.csv: fine, visitors never see samples (the operator's ?samples=1 view then uses automatic ones)")
    if os.environ.get("HG_YT_COOKIES_FILE"):
        add("ok" if os.path.exists(os.environ["HG_YT_COOKIES_FILE"]) else "fail", "HG_YT_COOKIES_FILE is set" + ("" if os.path.exists(os.environ["HG_YT_COOKIES_FILE"]) else " but the file does not exist"))
    code, so, _ = run(["hostname", "-I"], 5)
    if code == 0 and so.split():
        add("ok", f"from a phone or another laptop (same Wi-Fi): http://{so.split()[0]}:{port}  (start with --host 0.0.0.0)")
    return out


def rehearse(links_path, demo, out_csv=os.path.join(RES, "demo_rehearsal.csv"), printer=print):
    """Run every line of a text file (a song NAME like a visitor would type, or a YouTube link; # = comment) through the real pipeline, without the browser, and print one line
    each with the seconds it took. A name is searched first and the first candidate is used, so the search is rehearsed too. Returns the rows; a failure that would show the
    tab-capture box is marked CAPTURE, a song served from stored numbers is marked (stored)."""
    if not os.path.exists(links_path):
        raise SystemExit(f"{links_path} not found. Make a text file with one song per line (a song name and artist, or a YouTube link; # starts a comment). "
                         f"There is an example: cp rehearsal_songs.txt {links_path}")
    with open(links_path, encoding="utf-8-sig") as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    if not lines:
        raise SystemExit(f"{links_path} has no songs in it")
    if not demo.ready:
        demo.warm()
    if not demo.ready:
        raise SystemExit(f"the pool did not load: {demo.warm_error}")
    rows = []
    for i, text in enumerate(lines, 1):
        t = time.time()
        target, picked, why = text, "", ""
        if not video_id(text) and "://" not in text and not re.match(r"^(www\.)?[\w-]+\.[a-z]{2,}/", text):        # a NAME (not a web address): search it, take the first candidate, like a visitor's tap
            code0, found = demo.search(text)
            res = (found.get("results") or []) if code0 == 200 else []
            if not res:
                why = "no_search_result"
            else:
                target, picked = res[0]["id"], res[0]["title"]
        if why:
            code, body, ok = 0, {}, False
        else:
            code, body = demo.from_link(target)
            ok = code == 200 and body.get("ok")
            why = "" if ok else ("CAPTURE " if body.get("fallback") == "capture" else "") + str(body.get("error", ""))
        title = (body.get("input") or {}).get("title", "") or picked
        top = ((body.get("results") or {}).get("A") or [{}])[0].get("title", "") if ok else ""
        src = body.get("source", "") if ok else ""
        secs = round(time.time() - t, 1)
        rows.append(dict(n=i, asked=text, ok=int(bool(ok)), error=why, title=title, source=src, seconds=secs, top1=top))
        printer(f"{i:2d} {'OK  ' if ok else 'FAIL'} {secs:5.1f}s  {text[:30]:30s} -> {(title or '-')[:30]:30s} top: {top[:26]:26s} {'(stored) ' if src == 'stored' else ''}{why}")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    good = [r["seconds"] for r in rows if r["ok"]]
    stored = sum(r["source"] == "stored" for r in rows)
    printer(f"\n{len(good)} of {len(rows)} worked ({stored} served from stored numbers)" + (f"; median {sorted(good)[len(good) // 2]:.0f} s, slowest {max(good):.0f} s" if good else "")
            + f"; {sum(r['error'].startswith('CAPTURE') for r in rows)} would need the tab capture. Saved {out_csv}")
    return rows


def other_jobs_running():
    """True when an analysis or a pool-growing job is running (it would make the demo slow)."""
    try:
        out = subprocess.run(["pgrep", "-f", "[r]un_tests.py|[b]oost_artists.sh|[b]oost3.sh"], capture_output=True, text=True).stdout.split()
        return [p for p in out if p != str(os.getpid())]
    except OSError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this computer only; 0.0.0.0 = other devices on the network too")
    ap.add_argument("--k", type=int, default=6, help="songs per list")
    ap.add_argument("--summary", action="store_true", help="print what the logged runs and answers show, then exit")
    ap.add_argument("--check", action="store_true", help="pre-flight check of everything the demo needs (yt-dlp, ffmpeg, memory, port, YouTube, ...), then exit")
    ap.add_argument("--fake", action="store_true", help="PRACTICE MODE: canned matches (no models, no pool); the page shows a banner. For testing the page and the browser on a busy machine")
    ap.add_argument("--benchmark", metavar="SONG", help="time the analysis on THIS machine and compare the speed-ups with the full analysis: a song name or a YouTube link, then exit")
    ap.add_argument("--excerpt", type=int, default=0, metavar="SECONDS", help="analyse only the middle SECONDS of songs longer than that (faster, slightly different numbers; check with --benchmark first). Default: whole songs")
    ap.add_argument("--fast", action="store_true", help="skip the models the app never reads (same numbers for what it reads, quicker). Default: the full analysis, exactly as the pool songs were analysed")
    ap.add_argument("--rehearse", metavar="LINKS.txt", help="run the links of this file (one per line) through the real pipeline and print the timings, then exit")
    a = ap.parse_args()
    if a.summary:
        return summary()
    if a.excerpt:
        os.environ["HG_DEMO_EXCERPT"] = str(a.excerpt)
    if a.fast:
        os.environ["HG_DEMO_FAST"] = "1"
    if a.benchmark:
        os.environ.setdefault("HG_YT_TIMEOUT", "120")
        if other_jobs_running():
            print("!! an analysis / pool-growing job is running: the timings will be slower than on the day.")
        benchmark(a.benchmark)
        return
    if a.check:
        marks = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}
        res = doctor(a.port)
        for lvl, text in res:
            print(f"{marks[lvl]} {text}")
        print(f"\n{sum(l == 'fail' for l, _ in res)} to fix, {sum(l == 'warn' for l, _ in res)} to look at")
        return
    if a.rehearse:
        os.environ.setdefault("HG_YT_TIMEOUT", "120")
        if other_jobs_running():
            print("!! an analysis / pool-growing job is running: the timings will be slower than on the day.")
        rehearse(a.rehearse, Demo(k=a.k))
        return
    if a.fake:
        d = tempfile.mkdtemp(prefix="hg_fake_")
        demo = Demo(FakeBackends(), k=a.k, log=os.path.join(d, "log.csv"), feedback=os.path.join(d, "fb.csv"))
        demo.fake = True
        srv = make_server(demo, a.host, a.port)
        threading.Thread(target=demo.warm, daemon=True).start()
        print(f"PRACTICE MODE on http://localhost:{a.port}: the matches are canned, not real. Ctrl+C stops it.")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        return
    os.environ.setdefault("HG_YT_TIMEOUT", "120")                  # a download that takes longer than this fails over to the tab capture
    if other_jobs_running():
        print("!! an analysis / pool-growing job is running: the demo will be slow and may run out of memory. Stop it before the demo day.")
    import sources
    old = sources.sweep_stale_temp(120)                            # audio folders a killed demo / analysis left in the temp folder (rule 1: no audio is kept)
    if old:
        print(f"removed {old} leftover temporary audio folder(s) from an earlier run")
    demo = Demo(k=a.k)
    srv = make_server(demo, a.host, a.port)
    threading.Thread(target=demo.warm, daemon=True).start()
    print(f"demo on http://localhost:{a.port}  (loading the pool in the background; the page shows a green light when ready). Ctrl+C stops it.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
