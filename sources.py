"""Get song info + a temporary audio file from Jamendo, Audius, FMA or YouTube.

Rules kept here:
  * Only tracks the site marks as downloadable are used (Jamendo/Audius). FMA is the open research dataset.
  * YouTube audio (via yt-dlp) is used ONLY to compute and store the recommendation numbers; the audio file
    itself is deleted the instant analysis ends, exactly like every other source. No audio is ever kept.
  * Audio goes into a TemporaryDirectory and is deleted as soon as analysis ends.
  * Keys come from environment variables; nothing personal is sent.
      JAMENDO_CLIENT_ID   (required for Jamendo)  https://devportal.jamendo.com
      AUDIUS_API_KEY      (optional, higher limits) https://api.audius.co/plans
      (YouTube needs yt-dlp + ffmpeg on PATH; song lists are built with build_youtube.py)
"""
from __future__ import annotations
import os, re, time, contextlib, tempfile, subprocess, glob
import requests

JAMENDO = "https://api.jamendo.com/v3.0"
AUDIUS = "https://api.audius.co/v1"
UA = {"User-Agent": "HiddenGems-student-project/0.1"}
_last = [0.0]


def _polite(min_gap=0.35):
    """Never hammer an API: at most ~3 requests per second."""
    gap = time.time() - _last[0]
    if gap < min_gap:
        time.sleep(min_gap - gap)
    _last[0] = time.time()


_SECRET = re.compile(r"(client_id|api_key|key|access_token)=[^&\s'\")]+", re.I)


def redact(text):
    """Error text without keys: a failed request's message contains its full URL (with the API key), and error
    text is written to index.csv, the logs and the backups."""
    return _SECRET.sub(r"\1=REDACTED", str(text))


def safe_exc(e):
    """The same kind of exception (and the same .response, so status codes still work) with keys removed."""
    try:
        err = type(e)(redact(e))
    except Exception:
        err = requests.RequestException(redact(e))
    err.response = getattr(e, "response", None)
    return err


def _get(url, params=None, headers=None, stream=False, tries=3):
    for i in range(tries):
        _polite()
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=60, stream=stream)
            if r.status_code == 429 and i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            r.raise_for_status()                 # (a 429 on the last try is raised here, never returned as None)
            return r
        except requests.RequestException as e:
            if i == tries - 1:
                raise safe_exc(e) from None
            time.sleep(2 * (i + 1))


# ------------------------------------------------------------------ Jamendo
LISTEN_KEYS = ("rate_listened_total", "listened_total", "listens_total", "rate_listens_total")


def _track_info(t):
    mi = t.get("musicinfo") or {}
    st = t.get("stats") or {}
    listens = next((st[k] for k in LISTEN_KEYS if st.get(k) not in (None, "")), None)
    return dict(
        source="jamendo", id=int(t["id"]), title=t.get("name"), artist=t.get("artist_name"),
        album=t.get("album_name"), duration=float(t.get("duration") or 0),
        download_allowed=bool(t.get("audiodownload_allowed")), download_url=t.get("audiodownload") or "",
        licence=t.get("license_ccurl"), listens=listens, stats=st,
        artist_id=t.get("artist_id"), album_id=t.get("album_id"), release_date=t.get("releasedate"),
        tags_site=" ".join((mi.get("tags") or {}).get("genres") or []),
        vocalinstrumental=mi.get("vocalinstrumental"), speed=mi.get("speed"),
        acousticelectric=mi.get("acousticelectric"), gender=mi.get("gender"),
        page=t.get("shareurl"))


def _jamendo_query(cid, batch):
    r = _get(f"{JAMENDO}/tracks/", params={
        "client_id": cid, "format": "json", "limit": 200, "id": " ".join(str(x) for x in batch),
        "include": "musicinfo stats licenses", "audiodlformat": "mp32"})
    data = r.json()
    if data.get("headers", {}).get("status") != "success":
        raise RuntimeError(f"Jamendo error: {data.get('headers')}")
    return data["results"]


def jamendo_tracks(ids):
    """Metadata for Jamendo track ids. Asks in batches of 20, then re-asks one by one (slowly) for
    any id a batch didn't return, so a busy or rate-limited API can't make songs look 'missing'.
    An id counts as missing only if the single-id request also comes back empty."""
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if not cid:
        raise SystemExit("Set JAMENDO_CLIENT_ID first (free at https://devportal.jamendo.com)")
    out = {}
    for i in range(0, len(ids), 20):
        batch = [int(x) for x in ids[i:i + 20]]
        for t in _jamendo_query(cid, batch):
            out[int(t["id"])] = _track_info(t)
        time.sleep(1.0)
    gaps = [x for x in ids if int(x) not in out]
    if gaps:
        print(f"  re-checking {len(gaps)} songs one by one (to be sure they are really gone)...")
    for x in gaps:
        time.sleep(1.0)
        for t in _jamendo_query(cid, [int(x)]):
            out[int(t["id"])] = _track_info(t)
    if gaps:
        print(f"  {sum(int(x) in out for x in gaps)} of them were found on the second try")
    return out


def jamendo_search(**filters):
    """e.g. jamendo_search(fuzzytags='happy rock', vocalinstrumental='vocal', limit=20).
    Only returns downloadable tracks."""
    cid = os.environ["JAMENDO_CLIENT_ID"]
    p = {"client_id": cid, "format": "json", "include": "musicinfo stats",
         "audiodlformat": "mp32", **filters}
    return [t for t in _get(f"{JAMENDO}/tracks/", params=p).json()["results"] if t.get("audiodownload_allowed")]


# ------------------------------------------------------------------ Audius
def _audius_headers():
    k = os.environ.get("AUDIUS_API_KEY")
    return {"Authorization": f"Bearer {k}"} if k else {}


AUDIUS_STATS = {"returned": 0, "not_downloadable": 0, "kept": 0}


def audius_search(query, limit=10, genre=None, offset=0):
    """Downloadable, not-gated Audius tracks for a search query."""
    p = {"query": query, "limit": limit, "only_downloadable": "true"}
    if genre:
        p["genre"] = genre
    if offset:
        p["offset"] = offset
    data = _get(f"{AUDIUS}/tracks/search", params=p, headers=_audius_headers()).json().get("data", [])
    return _audius_parse(data)


def audius_trending(genre=None, underground=False, time="allTime", limit=100, offset=0):
    """Trending lists (another way in when search returns few downloadable tracks)."""
    path = "/tracks/trending/underground" if underground else "/tracks/trending"
    p = {"limit": limit, "offset": offset}
    if not underground:
        p["time"] = time
        if genre:
            p["genre"] = genre
    data = _get(f"{AUDIUS}{path}", params=p, headers=_audius_headers()).json().get("data", [])
    return _audius_parse(data, genre_filter=genre if underground else None)


def audius_user_tracks(user_id, limit=100, offset=0):
    """An artist's own tracks (only the downloadable, not-gated ones are returned)."""
    data = _get(f"{AUDIUS}/users/{user_id}/tracks", params={"limit": limit, "offset": offset},
                headers=_audius_headers()).json().get("data", [])
    return _audius_parse(data)


def audius_track_owner(track_id):
    """Artist id of one track (works for any track, downloadable or not)."""
    t = _get(f"{AUDIUS}/tracks/{track_id}", headers=_audius_headers()).json().get("data") or {}
    return (t.get("user") or {}).get("id")


def _audius_parse(data, genre_filter=None):
    out = []
    for t in data or []:
        AUDIUS_STATS["returned"] += 1
        if genre_filter and t.get("genre") != genre_filter:
            continue
        acc = t.get("access") or {}
        if (not t.get("is_downloadable") or t.get("is_stream_gated") or t.get("is_download_gated")
                or (acc and acc.get("download") is False)):
            AUDIUS_STATS["not_downloadable"] += 1
            continue
        AUDIUS_STATS["kept"] += 1
        out.append(dict(source="audius", id=t["id"], title=t.get("title"),
                        artist=(t.get("user") or {}).get("name"), duration=float(t.get("duration") or 0),
                        listens=t.get("play_count"), genre=t.get("genre"), mood=t.get("mood"),
                        site_bpm=t.get("bpm"), bpm_custom=t.get("is_custom_bpm"), licence=t.get("license"),
                        page=("https://audius.co" + t["permalink"]) if str(t.get("permalink", "")).startswith("/") else t.get("permalink"),
                        artist_id=(t.get("user") or {}).get("id"), release_date=t.get("release_date"),
                        tags=t.get("tags") or "", description=(t.get("description") or "")[:300],
                        handle=(t.get("user") or {}).get("handle"),
                        download_allowed=True, download_url=f"{AUDIUS}/tracks/{t['id']}/download"))
    return out


# ------------------------------------------------------------------ Free Music Archive (research dataset)
FMA_FULL = "https://os.unil.cloud.switch.ch/fma/fma_full.zip"
_fma = {}


def _fma_zip():
    """The FMA archive opened over the internet: only its table of contents (~10 MB) is read now, and later only
    the bytes of each song asked for. Opened once per run."""
    if "z" not in _fma:
        try:
            from remotezip import RemoteZip
        except ImportError:
            raise RuntimeError("FMA songs need: pip install remotezip")
        _fma["z"] = RemoteZip(FMA_FULL, timeout=(15, 60))   # give up on a stalled read instead of hanging
    return _fma["z"]


# ------------------------------------------------------------------ temporary audio
def sweep_stale_temp(max_age_s=7200):
    """Delete audio folders (hg_*, hg_cap_*, hg_blind_*) left behind by a run that was killed hard (power cut,
    kill -9): the `with` block that normally deletes them never got to run. Only folders untouched for more than
    `max_age_s` (2 h) go, so a run in progress is never disturbed. Returns how many were removed."""
    import shutil
    n = 0
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "hg_*")):
        try:
            if os.path.isdir(d) and not os.path.islink(d) and time.time() - os.path.getmtime(d) > max_age_s:
                shutil.rmtree(d); n += 1
        except OSError:
            pass
    return n


_YT_EXTRA = None


def _yt_extra():
    """Extra yt-dlp options for downloads. YouTube hides its audio links behind a JavaScript puzzle; the solver scripts that pip installs (yt-dlp-ejs) can lag
    behind YouTube, which ends in "HTTP Error 403: Forbidden" (16 Oct rehearsal: 2 of 17 songs). --remote-components ejs:github lets yt-dlp fetch the current
    solver (it fixed both). Only added when this yt-dlp knows the option (2025.11 or newer); HG_YT_REMOTE_EJS=0 turns it off. Needs deno installed."""
    global _YT_EXTRA
    if _YT_EXTRA is None:
        _YT_EXTRA = []
        if os.environ.get("HG_YT_REMOTE_EJS", "1") != "0":
            try:
                v = (subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=20).stdout or "").strip()
                if re.match(r"\d{4}\.\d{2}\.\d{2}", v) and v[:10] >= "2025.11.12":
                    _YT_EXTRA = ["--remote-components", "ejs:github"]
            except Exception:
                pass
    return _YT_EXTRA


@contextlib.contextmanager
def temp_audio(info):
    """Download into a temp folder, yield the path, delete everything afterwards."""
    if not info.get("download_allowed") or not info.get("download_url"):
        raise PermissionError("not downloadable")
    if info["source"] == "fma":                          # one song read out of the FMA research archive
        z = _fma_zip()
        name = f"fma_full/{int(info['id']) // 1000:03d}/{int(info['id']):06d}.mp3"
        try:
            z.getinfo(name)
        except KeyError:
            err = requests.HTTPError(f"{name} is not in the FMA archive")
            err.response = type("R", (), {"status_code": 404})()
            raise err
        with tempfile.TemporaryDirectory(prefix="hg_") as d:
            path = os.path.join(d, "song.mp3")
            with z.open(name) as src, open(path, "wb") as f:
                while True:
                    chunk = src.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            yield path
        return
    if info["source"] == "youtube":                      # audio fetched with yt-dlp, then deleted straight away
        with tempfile.TemporaryDirectory(prefix="hg_") as d:
            out = os.path.join(d, "song.%(ext)s")
            cmd = ["yt-dlp", *_yt_extra(), "-q", "--no-warnings", "--no-playlist", "--force-ipv4",
                   "--retries", "3", "--socket-timeout", "30", "--sleep-requests", "1",
                   "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0",
                   "-o", out, info["download_url"]]
            if os.environ.get("HG_YT_COOKIES_FILE"):          # optional: a cookies.txt exported from a browser that is signed in to YouTube (the demo uses it if YouTube blocks the download)
                cmd[1:1] = ["--cookies", os.environ["HG_YT_COOKIES_FILE"]]
            try:
                subprocess.run(cmd, check=True, timeout=float(os.environ.get("HG_YT_TIMEOUT", 600)),
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                msg = (e.stderr or b"").decode("utf-8", "replace").strip().lower()
                if any(w in msg for w in ("unavailable", "private", "removed", "not available",
                                          "age-restricted", "age restricted", "sign in", "copyright",
                                          "blocked", "terminated")):
                    err = requests.HTTPError("youtube video unavailable")   # treated like a deleted track:
                    err.response = type("R", (), {"status_code": 404})()    # marked 'missing', not retried 3x
                    raise err
                raise RuntimeError(f"yt-dlp failed: {msg[:200] or e}")
            files = glob.glob(os.path.join(d, "song.*"))
            if not files:
                raise RuntimeError("yt-dlp produced no audio file")
            yield files[0]
        return                                            # leaving the 'with' deletes the folder and the audio
    headers = _audius_headers() if info["source"] == "audius" else {}
    with tempfile.TemporaryDirectory(prefix="hg_") as d:
        r = _get(info["download_url"], headers=headers, stream=True)
        ctype = (r.headers.get("Content-Type") or "").lower()
        ext = next((e for k, e in (("wav", ".wav"), ("flac", ".flac"), ("ogg", ".ogg"), ("aiff", ".aiff"),
                                     ("mp4", ".m4a"), ("aac", ".m4a")) if k in ctype), ".mp3")
        path = os.path.join(d, "song" + ext)
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
        yield path
    # leaving the 'with' block deletes the folder and the audio in it
