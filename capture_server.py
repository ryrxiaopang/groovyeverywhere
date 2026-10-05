"""Capture test: can the models still recognise a song captured from a browser tab or a microphone?

  python capture_server.py            then open http://localhost:8765 in Chrome or Edge on Windows
  python capture_server.py --summary  results so far, per capture method and site

The page records 30 seconds (tab audio, or the microphone while a song plays out loud), sends it here,
and gets back the 10 closest songs. The audio goes into a temporary file, is analysed and deleted at once.
Only numbers are logged, to results/capture_log.csv.

ONLY capture from sites that allow it: Jamendo, Audius and Free Music Archive pages (Creative Commons /
artist-permitted).
Spotify's User Guidelines forbid recording its content and feeding it to a machine learning model;
YouTube's Terms forbid reproducing content except as YouTube authorises. See the plan doc, section 10.
"""
import csv, json, os, sys, tempfile, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "results", "capture_log.csv")
FIELDS = ["time", "method", "site", "expected_key", "position", "top_share_pct", "neighbour_overlap",
          "top1_key", "top1_title", "top1_score",
          "expected_score", "rms_db", "silent_share", "seconds"]
ALLOWED_SITES = ("jamendo", "audius", "fma", "local file")
MAX_SILENT = 0.5        # more than half the clip silent -> don't use it (same rule for both tests)


def clip_query(wav_path):
    """THE one way a captured clip becomes numbers, used by both the capture test and the blind test, so the
    capture test measures exactly what the blind lists use: check silence, then the full analysis (which trims
    leading/trailing silence first). Returns (signal, feats or None)."""
    import analyze, match
    es = analyze._es()
    sig = match.signal_check(es.MonoLoader(filename=wav_path, sampleRate=16000, resampleQuality=1)())
    if sig["silent_share"] > MAX_SILENT:
        return sig, None
    sig["level_gain_db"] = even_out_volume(wav_path)
    feats, _ = analyze.analyse(wav_path)
    return sig, feats


TARGET_RMS = 0.2     # about -14 dBFS, the level of a finished release


def even_out_volume(wav_path):
    """Turn the capture up (or down) to a standard level before analysis. The robustness test showed the Sound
    model is level-sensitive: an 18 dB quieter clip was found first 48% of the time, 100% after this step.
    Works on the 16-bit WAV the capture page sends; anything else is left as it is. Returns the gain in dB."""
    import wave
    try:
        with wave.open(wav_path, "rb") as w:
            params = w.getparams()
            if params.sampwidth != 2:
                return 0.0
            a = np.frombuffer(w.readframes(params.nframes), dtype="<i2").astype(np.float64) / 32768.0
    except (wave.Error, EOFError):
        return 0.0
    rms = float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0
    if rms < 1e-6:
        return 0.0
    gain = TARGET_RMS / rms
    peak = float(np.abs(a).max()) * gain
    if peak > 0.99:                      # never push the loudest moments past the maximum (no clipping)
        gain *= 0.99 / peak
    out = np.clip(a * gain, -1, 1)
    with wave.open(wav_path, "wb") as w:
        w.setparams(params)
        w.writeframes((out * 32767).astype("<i2").tobytes())
    return round(20 * np.log10(gain), 1)


def analyse_clip(wav_path):
    sig, feats = clip_query(wav_path)
    return sig, (None if feats is None else np.asarray(feats["effnet_whole"], float))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "capture.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/tap":
            with open(os.path.join(HERE, "tap.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/taps":
            self._send(200, json.dumps(read_taps()))
        else:
            self._send(404, "{}")

    def _blind(self, q):
        """Blind test: a friend's song played from a phone near the microphone -> 3 hidden lists (results/blind/)."""
        import analyze, blind_test, match
        friend, song = (q.get("friend") or "").strip()[:20], (q.get("song") or "").strip()[:120]
        feature = q.get("feature", "sound")
        if not friend or not song or not blind_test.valid_feature(feature):
            return self._send(400, json.dumps({"error": "friend, song and a valid feature are needed"}))
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with tempfile.TemporaryDirectory(prefix="hg_blind_") as d:      # audio deleted when this block ends
            p = os.path.join(d, "clip.wav")
            with open(p, "wb") as f:
                f.write(body)
            try:
                sig, feats = clip_query(p)
                if feats is None:
                    return self._send(200, json.dumps({"warning": "Too quiet: move the phone closer and turn it up, then try again.", "signal": sig}))
            except Exception as e:
                return self._send(500, json.dumps({"error": f"could not analyse the clip: {e}"}))
        try:
            q_ = blind_test.query_from_analysis(feats)
            lists = blind_test.make_lists(q_, feature, seed=int(time.time()))
            if lists["weak_capture"]:          # probably room noise, not the song: don't let it into the test
                return self._send(200, json.dumps({"warning": f"Not saved: the recording doesn't sound like music "
                    f"(closest match only {lists['best_sound_cosine']}). Move the phone closer, turn it up, "
                    "keep the room quiet, and record again.", "signal": sig}))
            blind_test.save_capture(friend, song, feature, q_, lists, sig)
        except BaseException as e:          # incl. SystemExit: one bad request must never stop the server
            return self._send(500, json.dumps({"error": f"could not build the lists: {e}"}))
        n = len({s["key"] for L in blind_test.LISTS for s in lists[L]})
        self._send(200, json.dumps({"songs": n, "signal": sig}))

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/taps":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                save_tap(q.get("id", ""), q.get("bpm", ""))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(read_taps()))
        if u.path == "/blind":
            return self._blind({k: v[0] for k, v in parse_qs(u.query).items()})
        if u.path != "/analyse":
            return self._send(404, "{}")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        method, site = q.get("method", "tab"), q.get("site", "other").lower()
        if site not in ALLOWED_SITES:
            return self._send(400, json.dumps({"error": f"'{site}' isn't a site we're allowed to capture from. "
                                                        f"Use a Jamendo, Audius or Free Music Archive page."}))
        expected = (q.get("expected") or "").strip()
        if expected.isdigit():
            expected = ("fma_" if site == "fma" else "jamendo_") + expected
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        t = time.time()
        with tempfile.TemporaryDirectory(prefix="hg_cap_") as d:      # audio deleted when this block ends
            p = os.path.join(d, "clip.wav")
            with open(p, "wb") as f:
                f.write(body)
            try:
                sig, emb = analyse_clip(p)
            except Exception as e:
                return self._send(500, json.dumps({"error": f"could not analyse the clip: {e}"}))
        import match
        res = dict(signal=sig, results=[])
        row = dict(time=time.strftime("%Y-%m-%d %H:%M"), method=method, site=site, expected_key=expected,
                   rms_db=sig["rms_db"], silent_share=sig["silent_share"])
        if emb is None:
            res["warning"] = "The capture was (almost) silent: the site may block recording, or tab audio wasn't shared."
        else:
            keys, meta, _, _ = match.library()
            order, s = match.rank(emb, method="windows")   # any ~30 s stretch (robustness test: 100% vs 95%)
            for i in order[:10]:
                r = meta[i]
                res["results"].append(dict(key=keys[i], title=r.get("title", ""), artist=r.get("artist", ""),
                                           score=round(float(s[i]), 3),
                                           link=r.get("page") or (f"https://www.jamendo.com/track/{keys[i].split('_', 1)[1]}"
                                                                  if keys[i].startswith("jamendo_") else "")))
            pos = match.position_of(expected, order) if expected else None
            res["expected_position"] = pos
            if pos is not None:
                # Finding the exact song is stricter than the app needs. What matters for recommendations:
                # does the clip pull up the same NEIGHBOURS as the real song? (share of the 20 closest in common)
                _, _, W, _ = match.library()
                ti = keys.index(expected)                     # (not `t`: that holds the start time for "seconds")
                o_true, _ = match.rank(W[ti], exclude={expected}, prepared=True)
                o_clip = [i for i in order if i != ti]
                overlap = len(set(o_clip[:20]) & set(o_true[:20].tolist())) / 20
                res["neighbour_overlap"] = overlap
                row.update(top_share_pct=round(100 * pos / len(keys), 1), neighbour_overlap=round(overlap, 2))
            row.update(position=pos if pos is not None else ("not in library" if expected else ""),
                       top1_key=keys[order[0]], top1_title=meta[order[0]].get("title", ""),
                       top1_score=round(float(s[order[0]]), 3),
                       expected_score=round(float(s[keys.index(expected)]), 3) if expected in keys else "")
        row["seconds"] = round(time.time() - t, 1)
        new = not os.path.exists(LOG)
        if not new:                                   # an older log with fewer columns: rewrite it with the new ones
            with open(LOG, newline="") as f:
                rd = csv.DictReader(f); old_rows = list(rd)
            if rd.fieldnames != FIELDS:
                with open(LOG + ".tmp", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(old_rows)
                os.replace(LOG + ".tmp", LOG)
        with open(LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if new: w.writeheader()
            w.writerow(row)
        self._send(200, json.dumps(res))


TAPS = os.path.join(HERE, "taps.csv")
TAP_COLS = ["jamendo_id", "title", "artist", "group", "listen", "tapped_bpm"]


def read_taps():
    if not os.path.exists(TAPS):
        return []
    with open(TAPS, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_tap(song_id, bpm):
    """Write one tapped speed (or 'none' / '' to clear) into taps.csv, all-or-nothing, keeping a .bak copy."""
    v = str(bpm).strip().lower()
    if v not in ("none", ""):
        b = float(v)
        if not 30 <= b <= 300:
            raise ValueError("speed must be between 30 and 300 BPM")
        v = f"{b:.1f}"
    rows = read_taps()
    if not any(r["jamendo_id"] == song_id for r in rows):
        raise ValueError("song not in taps.csv")
    for r in rows:
        if r["jamendo_id"] == song_id:
            r["tapped_bpm"] = v
    with open(TAPS + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=TAP_COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    if os.path.exists(TAPS):
        import shutil
        shutil.copyfile(TAPS, TAPS + ".bak")
    os.replace(TAPS + ".tmp", TAPS)


def summary():
    if not os.path.exists(LOG):
        print("no captures yet"); return
    with open(LOG) as f:
        rows = list(csv.DictReader(f))
    groups = {}
    for r in rows:
        groups.setdefault((r["method"], r["site"]), []).append(r)
    print(f"{'method':6s} {'site':10s} {'n':>3s} {'silent':>6s} {'found #1':>9s} {'top 10':>7s} {'same 20 neighbours':>19s}"
          "  (songs with a known answer)")
    for (m, s), g in sorted(groups.items()):
        known = [r for r in g if str(r["position"]).isdigit()]
        p = [int(r["position"]) for r in known]
        silent = sum(float(r["silent_share"] or 0) > 0.8 for r in g)
        f1 = f"{sum(x == 1 for x in p)}/{len(p)}" if p else "-"
        t10 = f"{sum(x <= 10 for x in p)}/{len(p)}" if p else "-"
        ov = [float(r["neighbour_overlap"]) for r in g if r.get("neighbour_overlap") not in (None, "")]
        ovs = f"{100 * sum(ov) / len(ov):.0f}%" if ov else "-"
        print(f"{m:6s} {s:10s} {len(g):3d} {silent:6d} {f1:>9s} {t10:>7s} {ovs:>19s}")
    print("\nEach capture (newest last):")
    for r in rows[-12:]:
        print(f"  {r['method']:4s} {r.get('expected_key') or '(no song)':20s} position {str(r.get('position') or '-'):>6s}"
              f"  top score {r.get('top1_score') or '-':>6s}  its score {r.get('expected_score') or '-':>6s}"
              f"  loudness {r.get('rms_db') or '-':>6s} dB  neighbours {r.get('neighbour_overlap') or '-'}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        summary(); sys.exit()
    import match, sources
    sources.sweep_stale_temp()
    n = len(match.library()[0])
    print(f"library: {n} analysed songs. Open http://localhost:8765 in Chrome or Edge (Ctrl+C here to stop).")
    print("tapping page: http://localhost:8765/tap")
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
