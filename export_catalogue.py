"""One neat list of EVERY song the project has touched -> catalogue.csv (opens in Excel / Google Sheets).

  python export_catalogue.py

One row per song: where it came from, track id, title, artist, album, length, licence, link (for crediting
the artist), popularity and its rank, what it was used for, whether it was analysed, the human tags
it was tested against, and a few of the numbers the models produced.
Also prints a short summary (songs per source, per use, per status).
"""
import csv, glob, os, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")


def role_of(group):
    g = group or ""
    if g.startswith("train_"): return "training (own mood model)"
    if g.startswith("pool_"): return "recommendation pool"
    if g.startswith("eval_"): return "evaluation (big pass)"
    return "edge-case test"


def mtg():
    out = {}
    for split, fn in (("validation", "split0-autotagging-validation.tsv"), ("train", "split0-autotagging-train.tsv"),
                      ("test", "split0-autotagging-test.tsv")):
        p = os.path.join(HERE, "data", fn)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            next(f)
            for line in f:
                x = line.rstrip("\n").split("\t"); t = {"genre": [], "mood": [], "instrument": []}
                for tag in x[5:]:
                    k, v = tag.split("---"); t["mood" if k.startswith("mood") else k].append(v)
                out[x[0].split("_")[1].lstrip("0")] = (split, t, x[1], x[2])
    return out


def main():
    lists = {}
    for fn in ("edge_cases.csv", "bigpass.csv", "pool_list.csv", "pool_audius.csv", "pool_korean.csv", "pool_audius_more.csv", "pool_vocal.csv", "pool_fma.csv", "pool_youtube.csv"):
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    src = re.sub(r"[^a-z]", "", (r.get("source") or "jamendo").lower()) or "jamendo"
                    tid = str(r.get("track_id") or r.get("jamendo_id"))
                    lists[f"{src}_{tid}"] = {**r, "source": src, "track_id": tid}
    from results_index import latest_rows
    idx = latest_rows(RES)
    from results_index import read_meta, best_link
    meta = {}
    for p in glob.glob(os.path.join(RES, "meta", "*.json")):
        k = os.path.basename(p)[:-5]
        meta[k] = read_meta(k, RES)          # a damaged info file counts as empty (check_results.py --fix)
    tags = mtg()
    keys = sorted(set(lists) | set(idx))
    status_words = {"done": "analysed", "missing": "gone from its site", "not_downloadable": "not downloadable",
                    "failed": "failed (will retry)"}
    rows = []
    for k in keys:
        L, I, M = lists.get(k, {}), idx.get(k, {}), meta.get(k, {})
        src = re.sub(r"[^a-z]", "", (L.get("source") or I.get("source") or k.split("_")[0]).lower()) or "jamendo"
        tid = L.get("track_id") or str(I.get("id") or k.split("_", 1)[1])
        split, t, mtg_artist, mtg_album = tags.get(tid.lstrip("0"), (None, None, "", "")) if src == "jamendo" else (None, None, "", "")
        num = lambda v: float(v) if v not in (None, "", "None") else None
        row = dict(
            song_key=k, source=src, track_id=tid,
            title=M.get("title") or I.get("title") or L.get("title") or "",
            artist=M.get("artist") or I.get("artist") or L.get("artist") if not str(L.get("artist", "")).startswith("artist_") else (M.get("artist") or I.get("artist") or ""),
            album=M.get("album") or I.get("album") or (L.get("album") if not str(L.get("album", "")).startswith("album_") else ""),
            duration_s=round(num(M.get("duration") or I.get("duration_listed") or L.get("duration")) or 0, 1) or "",
            release_date=M.get("release_date", ""),
            licence=M.get("licence") or I.get("licence") or L.get("licence") or "",
            link=M.get("page") or I.get("page") or L.get("listen") or "",
            listen_link=best_link(k, M.get("page") or I.get("page") or L.get("listen") or ""),
            popularity=num(M.get("listens") if M.get("listens") not in (None, "") else (I.get("listens") or L.get("listens"))),
            used_for=role_of(I.get("group") or L.get("group")),
            test_group=I.get("group") or L.get("group") or "",
            status=status_words.get(I.get("status"), "not run yet") if I else "not run yet",
            mtg_split=split or "", mtg_artist_id=mtg_artist, mtg_album_id=mtg_album,
            human_genre_tags=" ".join(t["genre"]) if t else "", human_mood_tags=" ".join(t["mood"]) if t else "",
            human_instrument_tags=" ".join(t["instrument"]) if t else "",
            site_genre=M.get("genre") or I.get("site_genre") or L.get("site_genre") or "",
            site_mood=M.get("mood") or I.get("site_mood") or L.get("site_mood") or "",
            site_bpm=M.get("site_bpm") or I.get("site_bpm") or L.get("site_bpm") or "",
            i_agree=L.get("i_agree", ""))
        p = os.path.join(RES, f"{k}.npz")
        if I.get("status") == "done" and os.path.exists(p):
            d = np.load(p)
            ew = d["emomusic_whole"]
            row.update(model_happiness_1to9=round(float(ew[0]), 2), model_energy_1to9=round(float(ew[1]), 2),
                       model_bpm=round(float(d["rhythm_bpm"]), 1), model_beat_confidence=round(float(d["rhythm_confidence"]), 2),
                       loudness_db=round(float(d["rhythm_loudness_db"]), 1),
                       full_length_ok=I.get("full_length_ok", ""))
        rows.append(row)
    # popularity rank and obscurity, within each source, among songs with a known popularity
    for src in {r["source"] for r in rows}:
        grp = [r for r in rows if r["source"] == src and r["popularity"] is not None and r["status"] == "analysed"]
        if not grp:
            continue
        vals = np.array([r["popularity"] for r in grp])
        order = np.argsort(-vals)
        for rank, i in enumerate(order, 1):
            grp[i]["popularity_rank"] = rank
            grp[i]["obscurity_pct"] = round(100.0 * np.mean(vals > vals[i]), 1)   # share of songs MORE popular
    cols = ["song_key", "source", "track_id", "title", "artist", "album", "duration_s", "release_date", "licence", "link", "listen_link",
            "popularity", "popularity_rank", "obscurity_pct", "used_for", "test_group", "status", "mtg_split",
            "mtg_artist_id", "mtg_album_id", "human_genre_tags", "human_mood_tags", "human_instrument_tags",
            "site_genre", "site_mood", "site_bpm", "model_happiness_1to9", "model_energy_1to9", "model_bpm",
            "model_beat_confidence", "loudness_db", "full_length_ok", "i_agree"]
    rows.sort(key=lambda r: (r["used_for"], r["test_group"], str(r["artist"]).lower(), str(r["title"]).lower()))
    out = os.path.join(HERE, "catalogue.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:          # utf-8-sig: Excel shows accents correctly
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    # summary
    from collections import Counter
    print(f"catalogue.csv: {len(rows)} songs\n")
    for name, key in (("by source", "source"), ("by use", "used_for"), ("by status", "status")):
        c = Counter(r[key] for r in rows)
        print(name + ": " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    an = [r for r in rows if r["status"] == "analysed"]
    print(f"\npopularity known for {sum(r['popularity'] is not None for r in an)} of {len(an)} analysed songs")


if __name__ == "__main__":
    main()
