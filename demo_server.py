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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RES = os.path.join(HERE, "results")
LOG = os.path.join(RES, "demo_log.csv")
FEEDBACK = os.path.join(RES, "demo_feedback.csv")
SAMPLES_CSV = os.path.join(HERE, "demo_samples.csv")        # optional: key,title,artist of the sample songs you want on the page
LOG_COLS = ["time", "kind", "input", "title", "ok", "error", "seconds_total", "seconds_lookup", "seconds_download", "seconds_analyse", "seconds_match"]
FEEDBACK_COLS = ["time", "token", "kind", "input", "list", "rec_key", "rec_title", "rating", "would_add"]
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


def append_row(path, cols, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


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
        return dict(title=d.get("title") or "", channel=d.get("channel") or d.get("uploader") or "", duration=float(d.get("duration") or 0))

    def download(self, vid):
        """A context manager that yields the path of the downloaded audio and deletes it afterwards."""
        import sources
        return sources.temp_audio(dict(source="youtube", download_allowed=True, download_url=f"https://www.youtube.com/watch?v={vid}"))

    def analyse(self, path):
        import analyze
        feats, _ = analyze.analyse(path)
        return feats

    def analyse_clip(self, wav_path):
        import capture_server
        return capture_server.clip_query(wav_path)           # the same way the blind test turns a clip into numbers: (signal check, feats or None)

    def query(self, feats):
        import blind_test as bt
        return bt.query_from_analysis(feats)

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
        import numpy as np, blind_test as bt
        P = bt.pool()
        have = {k: (t, a) for k, t, a in zip(P["key"], P["title"], P["artist_name"])}
        if os.path.exists(SAMPLES_CSV):
            with open(SAMPLES_CSV, encoding="utf-8-sig") as f:
                rows = [r for r in csv.DictReader(f) if r.get("key") in have and os.path.exists(os.path.join(RES, f"{r['key']}.npz"))]
            return [dict(key=r["key"], title=r.get("title") or have[r["key"]][0], artist=r.get("artist") or have[r["key"]][1]) for r in rows]
        return auto_samples(P["key"], P["title"], P["artist_name"], P["group"], P["listens"])


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

    # ---- start-up
    def warm(self):
        try:
            self.pool_size = self.b.warm()
            self.ready = True
        except BaseException as e:                            # a missing pool must show on the page, not kill the server
            self.warm_error = f"{type(e).__name__}: {e}"[:200]

    def status(self):
        busy = self.lock.locked()
        return dict(ready=self.ready, pool=self.pool_size, error=self.warm_error, busy=busy, stage=self.stage if busy else "",
                    elapsed=round(time.time() - self.since, 1) if busy else 0)

    def _stage(self, s):
        self.stage = s

    # ---- one job at a time
    def _job(self, kind, ident, fn):
        """Run fn(times) under the lock; returns (http status, body dict). Every run is logged."""
        if not self.ready:
            return 503, dict(error="warming_up", message=self.warm_error or "The song pool is still loading: wait for the green light at the top of the page.")
        if not self.lock.acquire(blocking=False):
            return 429, dict(error="busy", message="Another song is being analysed. Try again in a moment.")
        t0, times, title, err = time.time(), {}, "", ""
        self.since = time.time()
        try:
            body = fn(times)
            title = (body.get("input") or {}).get("title", "")
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
            append_row(self.log, LOG_COLS, dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), kind=kind, input=ident, title=title, ok=int(not err),
                                                error=err, seconds_total=round(time.time() - t0, 1),
                                                **{f"seconds_{k}": round(v, 1) for k, v in times.items()}))

    def _finish(self, kind, ident, q, meta, features, times, extra_input):
        t = time.time()
        self._stage("finding matches")
        res = shape(self.b.recommend(q, meta, self.k, features), self.k)
        times["match"] = time.time() - t
        self.counter += 1
        token = f"{int(time.time())}-{self.counter}"
        self.last[token] = (q, meta, dict(kind=kind, id=ident))
        while len(self.last) > 8:
            self.last.popitem(last=False)
        return dict(ok=True, token=token, input=dict(kind=kind, id=ident, **extra_input), results=res)

    # ---- the three ways in
    def from_link(self, text):
        vid = video_id(text)
        if not vid:
            return 400, dict(error="not_youtube", message="That does not look like a YouTube link. Paste the address of a video (youtube.com/watch?v=... or youtu.be/...).")

        def run(times):
            t = time.time(); self._stage("looking up the song")
            info = self.b.info(vid)
            times["lookup"] = time.time() - t
            if info["duration"] and info["duration"] > MAX_SECONDS:
                raise DemoError("too_long", f"That video is {int(info['duration'] // 60)} minutes long. Pick a single song (under {MAX_SECONDS // 60} minutes).")
            t = time.time(); self._stage("downloading the audio")
            try:
                with self.b.download(vid) as path:
                    times["download"] = time.time() - t
                    t = time.time(); self._stage("listening to it (analysing)")
                    feats = self.b.analyse(path)
                    times["analyse"] = time.time() - t
            except DemoError:
                raise
            except BaseException as e:
                raise DemoError("download_failed", "YouTube blocked the download for this video" + (f" ({str(e)[:90]})" if str(e) else "") + ".", fallback="capture")
            q = self.b.query(feats)
            return self._finish("link", vid, q, dict(title=info["title"], artist=info["channel"]), DEFAULT_FEATURES, times,
                                dict(title=info["title"], artist=info["channel"], seconds=info["duration"]))
        return self._job("link", vid, run)

    def from_clip(self, wav_bytes, seconds=30):
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
            body = self._finish("capture", "tab", q, {}, DEFAULT_FEATURES, times, dict(title="your recording", artist="", seconds=seconds))
            if (body["results"].get("best_sound") or 1) < self.b.weak_cosine():
                body["warning"] = "The recording does not sound much like music (noise or a very quiet tab), so these matches may be weak."
            return body
        return self._job("capture", "tab", run)

    def get_samples(self):
        if not self.ready:
            return []
        if self.samples_cache is None:
            try:
                self.samples_cache = self.b.samples()
            except BaseException:
                self.samples_cache = []
        return self.samples_cache

    def from_sample(self, key):
        known = {s["key"]: s for s in self.get_samples()}
        if key not in known:
            return 400, dict(error="unknown_sample", message="That sample song is not on the list.")

        def run(times):
            t = time.time(); self._stage("loading the stored numbers")
            q, meta = self.b.sample_query(key)
            times["lookup"] = time.time() - t
            s = known[key]
            return self._finish("sample", key, q, meta, DEFAULT_FEATURES, times, dict(title=s["title"], artist=s["artist"]))
        return self._job("sample", key, run)

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
        append_row(self.feedback, FEEDBACK_COLS, dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), token=token, kind=inp["kind"], input=inp["id"], list=which,
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

        def _json_body(self, limit=20000):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise DemoError("too_big", "Request too large.", status=413)
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
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > MAX_CLIP_BYTES:
                        raise DemoError("too_big", "Recording too large.", status=413)
                    code, body = demo.from_clip(self.rfile.read(n))
                else:
                    d = self._json_body()
                    if u.path == "/api/link":
                        code, body = demo.from_link(d.get("url"))
                    elif u.path == "/api/sample":
                        code, body = demo.from_sample(str(d.get("key", "")))
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
    a = ap.parse_args()
    if a.summary:
        return summary()
    os.environ.setdefault("HG_YT_TIMEOUT", "120")                  # a download that takes longer than this fails over to the tab capture
    if other_jobs_running():
        print("!! an analysis / pool-growing job is running: the demo will be slow and may run out of memory. Stop it before the demo day.")
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
