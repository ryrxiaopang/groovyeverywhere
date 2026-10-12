"""Copy everything in results/ into PostgreSQL (no re-analysis, safe to run again).

  python import_results.py            # imports / updates every analysed song
  python similar.py 959961            # then: the 10 closest songs by Sound, straight from the database

Connection: environment variable HG_DB (setup_db.sh sets it), default
postgresql://hg:hg@localhost:5432/hiddengems
"""
import json, os, time
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")


def cls_idx(head, name, default):
    try:
        import models
        c = [x.lower() for x in models.classes(head)]
        return c.index(name)
    except Exception:
        return default


def mtg_info():
    """jamendo_id -> (split, {kind: set(tags)})"""
    out = {}
    for split, fn in (("validation", "split0-autotagging-validation.tsv"), ("train", "split0-autotagging-train.tsv"),
                      ("test", "split0-autotagging-test.tsv")):
        p = os.path.join(HERE, "data", fn)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            next(f)
            for line in f:
                x = line.rstrip("\n").split("\t")
                tags = {"genre": set(), "mood": set(), "instrument": set()}
                for t in x[5:]:
                    k, v = t.split("---")
                    tags["mood" if k.startswith("mood") else k].add(v)
                out[int(x[0].split("_")[1])] = (split, tags)
    return out


def num(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def meta(k):
    p = os.path.join(RES, "meta", f"{k}.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def excluded_keys():
    from results_index import excluded_keys as ek
    return ek(HERE)


def main(quiet=False):
    from results_index import latest_rows
    say = (lambda *a: None) if quiet else print
    rows = latest_rows(RES)
    done = {k: r for k, r in rows.items() if r["status"] == "done" and os.path.exists(os.path.join(RES, f"{k}.npz"))}
    say(f"{len(done)} analysed songs to import into {DB.split('@')[-1]}")
    excl = excluded_keys()
    from results_index import pool_keys
    in_pool = pool_keys(HERE)
    vgv, vga = cls_idx("emomusic_vggish", "valence", 0), cls_idx("emomusic_vggish", "arousal", 1)
    mtg = mtg_info()
    iv, ia = cls_idx("emomusic", "valence", 0), cls_idx("emomusic", "arousal", 1)
    dv, da = cls_idx("deam", "valence", 0), cls_idx("deam", "arousal", 1)
    hp, sd = cls_idx("mood_happy", "happy", 0), cls_idx("mood_sad", "sad", 1)
    ag, rl = cls_idx("mood_aggressive", "aggressive", 0), cls_idx("mood_relaxed", "relaxed", 1)
    t0 = time.time(); skipped = 0
    with psycopg.connect(DB, autocommit=False) as conn:
        with open(os.path.join(HERE, "schema.sql")) as f:
            conn.execute(f.read())
        register_vector(conn)
        cur = conn.cursor()
        for n, (k, r) in enumerate(done.items(), 1):
            try:
                d = dict(np.load(os.path.join(RES, f"{k}.npz")))
            except Exception:
                say(f"  skipped a damaged file: {k} (run python check_results.py --fix)"); skipped += 1
                continue
            m = meta(k)
            r = {**r, **{f: m.get(f) for f in ("title", "artist", "album", "licence", "page", "listens")
                         if m.get(f) not in (None, "")}}
            src = r.get("source") or k.split("_")[0]
            sid = str(r.get("id") or k.split("_", 1)[1])
            split, tags = mtg.get(int(sid), (None, None)) if src == "jamendo" and sid.isdigit() else (None, None)
            cur.execute("""INSERT INTO songs (song_key, source, source_id, title, artist, album, duration_s, listens,
                           licence, page, vocal_instrumental, speed_label, mtg_split, test_group)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (song_key) DO UPDATE SET title=EXCLUDED.title, artist=EXCLUDED.artist,
                           album=EXCLUDED.album, licence=EXCLUDED.licence, page=EXCLUDED.page,
                           listens=EXCLUDED.listens, test_group=EXCLUDED.test_group""",
                        (k, src, sid, r.get("title"), r.get("artist"), r.get("album"), num(r.get("duration_listed")),
                         int(num(r.get("listens"))) if num(r.get("listens")) is not None else None,
                         r.get("licence"), r.get("page"), r.get("vocalinstrumental") or None,
                         r.get("speed") or None, split, r.get("group")))
            f32 = lambda x: np.asarray(x, dtype=np.float32)
            ew = d["emomusic_whole"]; dw = d["deam_whole"]
            cand = {c: (d[c].tolist() if d[c].ndim else float(d[c])) for c in d
                    if c.startswith("cand_") and not c.startswith("cand_error") and c != "cand_vggish_whole"}
            timings = {c: num(r.get(c)) for c in r if c.startswith("t_")}
            cur.execute("""INSERT INTO features (song_key, analysis_version, file_duration_s, trimmed_duration_s,
                           full_length_ok, sound, instruments, valence, arousal, deam_valence, deam_arousal, p_happy,
                           p_sad, p_aggressive, p_relaxed, bpm, beat_confidence, steadiness, busyness, danceability,
                           loudness_db, candidates, timings)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (song_key) DO UPDATE SET analysis_version=EXCLUDED.analysis_version,
                           analysed_at=now(), sound=EXCLUDED.sound, instruments=EXCLUDED.instruments,
                           valence=EXCLUDED.valence, arousal=EXCLUDED.arousal, deam_valence=EXCLUDED.deam_valence,
                           deam_arousal=EXCLUDED.deam_arousal, p_happy=EXCLUDED.p_happy, p_sad=EXCLUDED.p_sad,
                           p_aggressive=EXCLUDED.p_aggressive, p_relaxed=EXCLUDED.p_relaxed, bpm=EXCLUDED.bpm,
                           beat_confidence=EXCLUDED.beat_confidence, steadiness=EXCLUDED.steadiness,
                           busyness=EXCLUDED.busyness, danceability=EXCLUDED.danceability,
                           loudness_db=EXCLUDED.loudness_db, candidates=EXCLUDED.candidates, timings=EXCLUDED.timings""",
                        (k, int(d["analysis_version"]) if "analysis_version" in d else 1,
                         float(d["file_duration"]), float(d["trimmed_duration"]),
                         bool(d["full_length_ok"]) if np.asarray(d["full_length_ok"]).dtype == bool else None,
                         f32(d["effnet_whole"]), f32(d["instruments_whole"]),
                         float(ew[iv]), float(ew[ia]), float(dw[dv]), float(dw[da]),
                         float(d["mood_happy_whole"][hp]), float(d["mood_sad_whole"][sd]),
                         float(d["mood_aggressive_whole"][ag]), float(d["mood_relaxed_whole"][rl]),
                         float(d["rhythm_bpm"]), float(d["rhythm_confidence"]),
                         None if np.isnan(float(d["rhythm_steadiness"])) else float(d["rhythm_steadiness"]),
                         float(d["rhythm_busyness"]), float(d["rhythm_danceability"]), float(d["rhythm_loudness_db"]),
                         json.dumps(cand), json.dumps(timings)))
            vg = d["cand_emomusic_vggish_whole"] if "cand_emomusic_vggish_whole" in d else None
            cur.execute("""UPDATE features SET vg_valence=%s, vg_arousal=%s WHERE song_key=%s""",
                        (float(vg[vgv]) if vg is not None else None, float(vg[vga]) if vg is not None else None, k))
            cur.execute("""UPDATE songs SET release_date=%s, excluded=%s, in_pool=%s WHERE song_key=%s""",
                        (m.get("release_date") or None, k in excl, k in in_pool, k))
            for p, (a, b) in enumerate(d["parts"]):
                cur.execute("""INSERT INTO song_parts (song_key, part, start_s, end_s, sound, instruments, valence, arousal)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (song_key, part) DO UPDATE SET sound=EXCLUDED.sound,
                               instruments=EXCLUDED.instruments, valence=EXCLUDED.valence, arousal=EXCLUDED.arousal""",
                            (k, p, float(a), float(b), f32(d["effnet_parts"][p]), f32(d["instruments_parts"][p]),
                             float(d["emomusic_parts"][p][iv]), float(d["emomusic_parts"][p][ia])))
            if tags:
                for kind, vals in tags.items():
                    for v in vals:
                        cur.execute("INSERT INTO song_tags (song_key, kind, tag) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (k, kind, v))
            if n % 200 == 0:
                conn.commit(); say(f"  {n} songs...")
        conn.commit()
        c = conn.execute("""SELECT count(*), count(*) FILTER (WHERE f.analysis_version >= 2),
                                   count(*) FILTER (WHERE s.in_pool AND NOT s.excluded)
                            FROM features f JOIN songs s USING (song_key)""").fetchone()
    if skipped:
        print(f"  {skipped} damaged file(s) skipped: run python check_results.py --fix")
    print(f"database: {c[0]} songs ({c[2]} in the pool, {c[1]} with the candidate models); "
          f"copied in {time.time()-t0:.0f}s")
    return c[0]


if __name__ == "__main__":
    main()
