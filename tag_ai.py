"""Tag pool songs that are confirmed or likely AI-generated  ->  results/ai_tags.csv   (YouTube songs; other sites rarely carry AI music)

  python tag_ai.py               # read every YouTube pool song's description / hashtags / channel (yt-dlp, no quota; ~30 min), then tag
  python tag_ai.py --retag       # re-tag from the saved metadata without downloading anything

CONFIRMED: the song's own title, description or hashtags say it (Suno, Udio, "AI-generated", "made with AI", "AI vocals", #aimusic ...).
LIKELY:    three or more soft signs together, none of which is proof alone:
             * a label-style title ("Genre x Genre | mood | Original Song")      * several mood words in the title (emotional, cinematic, healing ...)
             * very few views (< 1,000) and few likes                                * a tiny channel (< 1,000 subscribers) with a "Music / Records / Radio / Flow" style name
             * a very long title (> 70 characters)
This is a guess from labels and engagement, not an audio detector: a human artist can be 'likely' and a quiet AI song can be missed.
`ai_policy()` turns the tags into a rule for recommendations: show (keep all, with a note) / hide-low (default: drop AI songs with under
10,000 views, keep the popular ones) / hide (drop all AI songs).
"""
import argparse, csv, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import pool_keys, POOL_LISTS, list_key, RES

META = os.path.join(RES, "youtube_meta.jsonl")
OUT = os.path.join(RES, "ai_tags.csv")
FIELDS = ["key", "status", "reasons", "views", "likes", "followers", "channel"]
HIGH_VIEWS = 10_000          # hide-low keeps AI songs at or above this many views

CONFIRM = re.compile(r"\b(suno(\s?ai)?|udio|aiva|soundraw|mubert|boomy|loudly|riffusion|ai[- ]generated|generated (by|with|using|from) (an? )?ai|"
                     r"(made|created|produced|composed|written|sung|voiced) (by|with|using|via) (an? )?(ai|artificial intelligence|suno|udio)|"
                     r"ai[- ]?(music|song|songs|cover|vocals?|voice|singer|artist|assisted|lyrics|composed)|artificial intelligence|"
                     r"#ai\b|#aimusic|#aiartist|#aisong|#sunoai|#udio|made with ai)\b", re.I)
MOODY = re.compile(r"\b(emotional|cinematic|dreamy|ethereal|healing|soothing|soulful|heartfelt|powerful|432 ?hz|aesthetic|vibes?|"
                   r"romantic|melancholic|nostalgic|haunting|velvet|smoky|midnight|golden hour)\b", re.I)
LABEL = re.compile(r"(\|.*\b(neo[- ]?soul|city pop|j-?pop|k-?pop|c-?pop|r&b|lo-?fi|chill|vocal|ballad|dream pop|synth ?pop|hip-?hop|indie|"
                   r"alternative|original (song|music))\b)|[×]|\boriginal (song|music)\b", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐️]")
GENRE_TAIL = re.compile(r"\b(korean|japanese|chinese|cantonese|mandarin|taiwanese|thai|vietnamese|indonesian)[ -]?(hip-?hop|indie|r&b|pop|rock|ballad|city pop|soul)\b|"
                        r"\b(cantopop|mandopop|j-?pop|k-?pop|c-?pop|city pop)\b", re.I)
BRACKET_GENRE = re.compile(r"^\s*[\[【《(][^\]】》)]*\b(rock|pop|indie|hip-?hop|r&b|ballad|lo-?fi|jazz|soul|folk|ost)\b[^\]】》)]*[\]】》)]", re.I)
NAMEY = re.compile(r"\b(music|records?|radio|flow|studio|lab|sounds?|vibes?|tv|fm|network|collective|project|sessions?)\b", re.I)


def fetch_all_api():
    """Titles, descriptions, hashtags, views, likes and channel size through the official YouTube Data API: 50 videos per request
    (1 quota unit each), so ~100 units for the whole pool and no bot-detection problems (yt-dlp was throttled after a few hundred)."""
    import requests
    key = os.environ["YOUTUBE_API_KEY"]
    members = pool_keys()
    keys = set()
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            keys |= {list_key(r) for r in csv.DictReader(open(p, encoding="utf-8-sig")) if list_key(r) in members and list_key(r).startswith("youtube_")}
    keys = sorted(keys)
    print(f"{len(keys)} YouTube pool songs; reading them through the API", flush=True)

    def call(path, **params):
        for attempt in range(4):
            r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params={**params, "key": key}, timeout=30)
            if r.status_code in (429, 500, 503):
                time.sleep(10 * (attempt + 1)); continue
            if r.status_code == 403 and "quota" in r.text.lower():
                raise SystemExit("YouTube API quota used up for today; run again after it resets (midnight Pacific time)")
            r.raise_for_status()
            return r.json()
        raise RuntimeError("YouTube API kept failing")

    recs, chan_ids = {}, set()
    for i in range(0, len(keys), 50):
        batch = keys[i:i + 50]
        ids = [k.split("_", 1)[1] for k in batch]
        data = call("videos", part="snippet,statistics", id=",".join(ids))
        got = {it["id"]: it for it in data.get("items", [])}
        for k, vid in zip(batch, ids):
            it = got.get(vid)
            if not it:
                recs[k] = dict(key=k, available=False, error="not returned by the API (removed or private)")
                continue
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            recs[k] = dict(key=k, title=sn.get("title"), description=(sn.get("description") or "")[:1500], tags=(sn.get("tags") or [])[:30],
                           views=int(st.get("viewCount") or 0), likes=int(st.get("likeCount") or 0), followers=None,
                           channel=sn.get("channelTitle"), channel_id=sn.get("channelId"), upload_date=(sn.get("publishedAt") or "")[:10],
                           available=True)
            chan_ids.add(sn.get("channelId"))
        if (i // 50) % 20 == 0:
            print(f"  {min(i + 50, len(keys))} / {len(keys)}", flush=True)
    subs, ch = {}, sorted(c for c in chan_ids if c)
    for i in range(0, len(ch), 50):
        for it in call("channels", part="statistics", id=",".join(ch[i:i + 50])).get("items", []):
            st = it.get("statistics", {})
            subs[it["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount") or 0)
    with open(META, "w", encoding="utf-8") as out:
        for r in recs.values():
            if r.get("channel_id") in subs:
                r["followers"] = subs[r["channel_id"]]
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"read {sum(1 for r in recs.values() if r.get('title'))} songs, {sum(1 for r in recs.values() if not r.get('title'))} not returned", flush=True)


def fetch_all(threads):
    import yt_dlp
    members = pool_keys()
    keys = []
    for fn in POOL_LISTS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            keys += [list_key(r) for r in csv.DictReader(open(p, encoding="utf-8-sig")) if list_key(r) in members and list_key(r).startswith("youtube_")]
    keys = sorted(set(keys))
    have = set()
    if os.path.exists(META):
        for line in open(META, encoding="utf-8"):
            try:
                have.add(json.loads(line)["key"])
            except Exception:
                pass
    todo = [k for k in keys if k not in have]
    print(f"{len(keys)} YouTube pool songs; {len(todo)} still to read", flush=True)
    lock, n = threading.Lock(), [0]
    out = open(META, "a", encoding="utf-8")

    def work(k):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
                i = ydl.extract_info("https://www.youtube.com/watch?v=" + k.split("_", 1)[1], download=False)
            rec = dict(key=k, title=i.get("title"), description=(i.get("description") or "")[:1500], tags=(i.get("tags") or [])[:30],
                       views=i.get("view_count"), likes=i.get("like_count"), followers=i.get("channel_follower_count"),
                       channel=i.get("channel") or i.get("uploader"), upload_date=i.get("upload_date"), available=True)
        except Exception as e:
            msg = str(e).lower()
            rec = dict(key=k, available=not any(w in msg for w in ("unavailable", "private", "removed", "terminated", "not available")),
                       error=str(e)[:100])
        with lock:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            n[0] += 1
            if n[0] % 250 == 0:
                print(f"  {n[0]} / {len(todo)}", flush=True)

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(work, todo))
    out.close()


def classify(rec):
    t = rec.get("title") or ""
    text = " ".join([t, rec.get("description") or "", " ".join(rec.get("tags") or [])])
    m = CONFIRM.search(text)
    if m:
        return "confirmed", f"says so: '{m.group(0).strip()}'"
    pts, why = 0, []
    views, likes, fol = rec.get("views") or 0, rec.get("likes") or 0, rec.get("followers")
    if LABEL.search(t) or GENRE_TAIL.search(t) or BRACKET_GENRE.search(t):
        pts += 1; why.append("genre label in the title")
    if EMOJI.search(t):
        pts += 1; why.append("emoji decoration in the title")
    if len(MOODY.findall(t)) >= 2:
        pts += 1; why.append("several mood words in the title")
    if views < 1000 and likes < 25:
        pts += 1; why.append("almost no views or likes")
    if views < 150:
        pts += 1; why.append("under 150 views")
    if fol is not None and fol < 1000 and NAMEY.search(rec.get("channel") or ""):
        pts += 1; why.append("tiny channel with a label-style name")
    if len(t) > 70:
        pts += 1; why.append("very long title")
    return ("likely", "; ".join(why)) if pts >= 3 else ("none", "; ".join(why))


def tag():
    rows = []
    for line in open(META, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not rec.get("title"):
            continue
        st, why = classify(rec)
        rows.append(dict(key=rec["key"], status=st, reasons=why, views=rec.get("views") or 0, likes=rec.get("likes") or 0,
                         followers=rec.get("followers") if rec.get("followers") is not None else "", channel=rec.get("channel") or ""))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    from collections import Counter
    print("tags:", dict(Counter(r["status"] for r in rows)), "->", OUT)


def load_tags():
    """key -> (status, reasons, views); {} if tag_ai.py has not been run."""
    if not os.path.exists(OUT):
        return {}
    return {r["key"]: (r["status"], r["reasons"], float(r["views"] or 0)) for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))}


def norm_name(s):
    """Channel / artist name for comparing: accents folded, lower case, punctuation gone ('clouds.rap' = 'Clouds Rap', 'kanegi.' = 'kanegi')."""
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w]+", " ", s.replace("_", " ")).split())


def load_name_list(name, here=HERE):
    """Set of normalised names from a text file in the project folder (one per line, # starts a comment); empty if the file is missing."""
    p = os.path.join(here, name)
    if not os.path.exists(p):
        return set()
    with open(p, encoding="utf-8-sig") as f:
        return {norm_name(l.split("#")[0]) for l in f if l.split("#")[0].strip()} - {""}


def load_channels(res=RES):
    """key -> channel name, from results/ai_tags.csv ({} if tag_ai.py has not been run)."""
    if not os.path.exists(OUT):
        return {}
    return {r["key"]: r.get("channel") or "" for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))}


def ai_policy(status, views, policy):
    """True when the song should be KEPT under the policy ('show', 'hide-low' or 'hide')."""
    if status == "none" or policy == "show":
        return True
    if policy == "hide":
        return False
    return views >= HIGH_VIEWS          # hide-low


def ai_reason(status, views, chan, artist, policy, keep, block):
    """Why a song leaves the pool as AI music, or None. chan / artist are norm_name()d; keep / block are the sets from ai_keep.txt / ai_block.txt.
    ai_keep.txt wins over everything; then a blocked channel; then the AI tag under the policy ('confirmed' / 'likely')."""
    if keep & ({chan, artist} - {""}):
        return None
    if chan and chan in block:
        return "blocked channel"
    if not ai_policy(status, views, policy):
        return status
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--retag", action="store_true")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    if not a.retag:
        if os.environ.get("YOUTUBE_API_KEY"):
            fetch_all_api()
        else:
            fetch_all(a.threads)
    tag()
