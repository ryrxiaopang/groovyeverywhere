"""Label every pool song with its language, for the demo's language filter (English, Chinese, Korean, Japanese, other).

  pip install lingua-language-detector          # once, on the desktop only (an offline language detector, about 300 MB; nothing is sent anywhere)
  python song_languages.py                      # writes results/song_languages.csv and prints the counts and samples to check by eye

Run it after the pool changes (new songs) and before make_demo_bundle.py (the bundle carries the file; the laptop does not need the detector).
A song missing from the file counts as "unknown" and is always shown, so a new song is never hidden by mistake.

How a song is labelled, in this order (the first rule that applies wins):
  1. the writing in the TITLE: Hangul = Korean, kana = Japanese, Chinese characters = Chinese, Thai / Cyrillic / Arabic / ... = other;
  2. the search group it came from (kpop, khiphop ... = Korean; cpop, mrnb, chiphop, twindie, mrock, cantopop = Chinese; jpop, jrock ... = Japanese);
  3. the writing in the ARTIST name (same as 1);
  4. Latin-script titles: the detector (English, Spanish, Portuguese, French, Italian, German, Vietnamese) reads the SONG NAME only
     (brackets, "feat. ...", the artist's name and stock words such as "official video" taken out). "Other" only when fairly sure: another language
     at least 0.6 and 0.3 ahead of English, never from a one-word name alone; letters such as ñ ¿ ã or Vietnamese ones, and phrases such as
     "clip officiel" or "letra", also count. When the name only leans that way, the song's own YouTube description (link lines, hashtags, stock
     phrases removed) must agree strongly (0.8). Otherwise the song counts as English, so an English song is rarely hidden; the price is that some
     Spanish or French songs stay visible. (Second fix 16 Oct: artist names in titles made 8 of 15 sampled "other" songs wrong.)
     (The first version read title + description together: 10 of 15 sampled "other" songs were English, because descriptions are often in the
     artist's or label's language. Fixed 16 Oct.)
Mandarin and Cantonese are one label (Chinese): they cannot be told apart from the characters.
"""
import argparse, collections, csv, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from results_index import RES

OUT = os.path.join(RES, "song_languages.csv")
LABELS = ("english", "chinese", "korean", "japanese", "other", "unknown")
GROUP_LABEL = {**{g: "korean" for g in ("kpop", "krnb", "khiphop", "kindie", "kballad", "klofi")},
               **{g: "chinese" for g in ("cpop", "mrnb", "chiphop", "twindie", "mrock", "cantopop")},
               **{g: "japanese" for g in ("jpop", "jrnb", "citypop", "jindie", "jrock", "jhiphop")}}
OTHER_SCRIPTS = re.compile(r"[฀-๿Ѐ-ӿ؀-ۿ֐-׿ऀ-ॿͰ-Ͽঀ-৿஀-௿က-႟]")
VIET = re.compile(r"[ơưăđƠƯĂĐạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
STOCK = re.compile(r"\b(official|music|video|audio|lyrics?|visuali[sz]er|ft|feat|featuring|prod|mv|m/v|remix|version|live|performance|hd|4k)\b\.?", re.I)   # English stock words in titles of every language
IBERIAN = re.compile(r"[ñ¿¡ãõ]", re.I)
BOILER = re.compile(r"https?://|www\.|@|#|provided to youtube|auto-generated|℗|©|\b(listen|stream|follow|subscribe|download|official|"
                    r"directed|produced|producer|director|lyrics|music video|video by|spotify|apple music|instagram|tiktok|twitter|facebook|"
                    r"management|booking|records|label|copyright|all rights)\b", re.I)


MARKERS = re.compile(r"\b(clip officiel|paroles|letra|clipe oficial|v[ií]deo oficial|videoclip oficial|en vivo|ao vivo)\b", re.I)   # stock words of French / Spanish / Portuguese uploads


def song_part(title, artist):
    """The song's own name inside a YouTube title: bracketed parts, "feat. ..." and the "Artist - " / " | Artist" segments taken out, because
    artist names (Fousheé, Gesaffelstein, chloe moriondo) make the detector guess French or German for English songs."""
    from tag_ai import norm_name
    t = re.sub(r"[\(\[【《「][^\)\]】》」]*[\)\]】》」]", " ", title or "")
    t = re.sub(r"\b(feat|ft|featuring|prod|with)\b\.?.*$", " ", t, flags=re.I)
    a = norm_name(artist)
    parts = [x for x in re.split(r"\s+[-–—|:]\s+|\s*\|\s*", t) if x.strip()]
    keep = [x for x in parts if not (a and (norm_name(x) == a or (len(a) > 3 and a in norm_name(x))))]
    out = " ".join(keep or parts).strip()
    return out or (title or "")


def script_label(text):
    """The label given by the writing alone, or None for Latin script / no letters."""
    if re.search(r"[가-힯ᄀ-ᇿ]", text):
        return "korean"
    if re.search(r"[぀-ヿ]", text):
        return "japanese"
    if re.search(r"[一-鿿]", text):
        return "chinese"
    if OTHER_SCRIPTS.search(text):
        return "other"
    return None


def group_key(group):
    g = (group or "").lower()
    for p in ("yt_", "pool_vocal_", "pool_audius_", "pool_jamendo_", "pool_fma_", "pool_"):
        if g.startswith(p):
            return g[len(p):]
    return g


def clean_description(desc):
    """The lines of a YouTube description that say something about the song itself (often the lyrics), stock lines removed."""
    keep = [l.strip() for l in (desc or "").splitlines() if l.strip() and not BOILER.search(l)]
    return " ".join(keep)[:800]


def make_detector():
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        raise SystemExit("the language detector is not installed: run  pip install lingua-language-detector  (desktop only), then try again")
    names = ("ENGLISH", "SPANISH", "PORTUGUESE", "FRENCH", "ITALIAN", "GERMAN", "VIETNAMESE")   # 16 Oct: Latin, Tagalog, Dutch, Swedish, Indonesian
                                                                                                 # were mostly false alarms on English titles ("Rainy Day" = Indonesian)
    langs = [getattr(Language, n) for n in names if hasattr(Language, n)]
    det = LanguageDetectorBuilder.from_languages(*langs).build()

    def detect(text):
        """[(language name, confidence)] best first."""
        return [(c.language.name.lower(), float(c.value)) for c in det.compute_language_confidence_values(text)]
    return detect


def label_song(title, artist, group, description, detect):
    """(label, how it was decided)."""
    s = script_label(title or "")
    if s:
        return s, "title script"
    g = GROUP_LABEL.get(group_key(group))
    if g:
        return g, f"group {group_key(group)}"
    s = script_label(artist or "")
    if s:
        return s, "artist script"
    if VIET.search(title or ""):
        return "other", "vietnamese letters in the title"
    if IBERIAN.search(title or ""):
        return "other", "spanish / portuguese letters in the title"
    if MARKERS.search(title or ""):
        return "other", "'clip officiel' / 'letra' ... in the title"
    t = STOCK.sub(" ", song_part(title, artist))
    if not re.search(r"[A-Za-zÀ-ÿ]{2,}", t):
        return "unknown", "no words to read"
    conf = detect(t)                                   # the SONG TITLE decides: descriptions are often in the artist's or label's language, not the song's
    if not conf:
        return "english", "detector gave nothing"
    best, p = conf[0]
    en = next((v for l, v in conf if l == "english"), 0.0)
    one_word = len(re.findall(r"[A-Za-zÀ-ÿ']+", t)) <= 1                         # one-word titles ("Santeria", "kindergarten") fool the detector
    if best != "english" and not one_word and p >= 0.6 and p - en >= 0.3:
        return "other", f"{best} {p:.2f} (title)"
    desc = clean_description(description)
    if best != "english" and p >= 0.3 and len(desc) >= 40:     # the title leans to another language but not clearly: the song's own description must agree, strongly
        dc = detect(desc)
        if dc and dc[0][0] == best and dc[0][1] >= 0.8:
            return "other", f"{best} {p:.2f} (title) + description {dc[0][1]:.2f}"
    return "english", f"english {en:.2f}" + (f" (title leans {best} {p:.2f}, not sure)" if best != "english" else "")


def load_meta(res=RES):
    """{key: description} from results/youtube_meta.jsonl (tag_ai.py)."""
    out, p = {}, os.path.join(res, "youtube_meta.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
                out[r["key"]] = r.get("description") or ""
            except Exception:
                pass
    return out


def build(rows, descriptions, detect):
    """{key: (label, detail)} for pool rows (dicts with key, title, artist, group)."""
    return {r["key"]: label_song(r.get("title"), r.get("artist"), r.get("group"), descriptions.get(r["key"], ""), detect) for r in rows}


def write(labels, rows, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    titles = {r["key"]: r.get("title") or "" for r in rows}
    with open(path + ".tmp", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["key", "language", "how", "title"])
        for k, (lab, how) in sorted(labels.items()):
            w.writerow([k, lab, how, titles.get(k, "")])
    os.replace(path + ".tmp", path)


_cache = {"mtime": None, "labels": {}}


def load(path=OUT):
    """{key: label} from results/song_languages.csv ({} if it was never written); re-read when the file changes."""
    if not os.path.exists(path):
        return {}
    m = os.path.getmtime(path)
    if _cache["mtime"] != m:
        with open(path, encoding="utf-8-sig") as f:
            _cache["labels"] = {r["key"]: r["language"] for r in csv.DictReader(f)}
        _cache["mtime"] = m
    return _cache["labels"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=15, help="how many 'other' songs (and English ones) to print for checking by eye")
    a = ap.parse_args()
    from pool_summary import read_pool
    rows = [r for r in read_pool() if r["key"].startswith("youtube_")]
    detect = make_detector()
    labels = build(rows, load_meta(), detect)
    write(labels, rows)
    c = collections.Counter(lab for lab, _ in labels.values())
    print(f"{len(labels)} pool songs labelled -> {OUT}")
    for lab in LABELS:
        print(f"  {lab:9s} {c.get(lab, 0):6d}")
    by_lang = collections.Counter(how.split()[0] if re.fullmatch(r"[a-z]+ \d\.\d\d", how) else how for lab, how in labels.values() if lab == "other")
    print("  other, by language: " + ", ".join(f"{l} {n}" for l, n in by_lang.most_common(10)))
    rnd = random.Random(1)
    title = {r["key"]: f"{(r.get('title') or '')[:55]} | {(r.get('artist') or '')[:20]}" for r in rows}
    for lab in ("other", "english"):
        ks = [k for k, (l, _) in labels.items() if l == lab]
        print(f"\n{lab}: {min(a.sample, len(ks))} random songs to check (title | artist | why)")
        for k in rnd.sample(ks, min(a.sample, len(ks))):
            print(f"  {title[k]:78s} {labels[k][1]}")


if __name__ == "__main__":
    main()
