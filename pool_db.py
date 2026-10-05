"""Read the song numbers from PostgreSQL: the store the app uses.

  load(pool_only=True)  -> dict of arrays, or None (then callers read the results/ files and say so)

Pool songs = songs in a pool list (pool_list.csv, pool_audius.csv, ...) that are analysed and not marked
i_agree = n. Membership and exclusions are read from the lists at load time, so a mark you just made counts
even before the next import. If the database holds fewer of those songs than results/ (an import was missed),
it is not used: the files are the full record, and the caller falls back to them.
Both mood models are returned (vg_* = VGGish, the chosen one; mc_* = the original); the caller uses one model
for every song, never a mix.
"""
import os
import numpy as np

DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")


def _vec(v):
    if v is None:
        return None
    if hasattr(v, "to_numpy"):          # pgvector's Vector type (newer versions return this instead of a list)
        v = v.to_numpy()
    return np.asarray(v, dtype=float)


def _expected(pool_only):
    """Analysed songs according to the files (the full record)."""
    from results_index import latest_rows, pool_keys, RES
    rows = latest_rows(RES)
    done = {k for k, r in rows.items() if r["status"] == "done" and os.path.exists(os.path.join(RES, f"{k}.npz"))}
    return done & pool_keys() if pool_only else done


def load(pool_only=True):
    try:
        import psycopg
        from pgvector.psycopg import register_vector
        conn = psycopg.connect(DB, connect_timeout=3)
    except Exception as e:
        print(f"  (database not reachable: {str(e).splitlines()[0][:120]}; reading results/ files instead)")
        return None
    want = _expected(pool_only)
    if not want:
        return None
    try:
        with conn:
            register_vector(conn)
            rows = conn.execute("""
                SELECT s.song_key, s.source, coalesce(s.artist, ''), coalesce(s.title, ''), coalesce(s.page, ''),
                       s.listens, coalesce(s.test_group, ''), f.sound, f.instruments,
                       f.vg_valence, f.vg_arousal, f.valence, f.arousal,
                       f.bpm, f.beat_confidence, coalesce(f.steadiness, 0), f.busyness
                FROM songs s JOIN features f USING (song_key)
                WHERE s.song_key = ANY(%s) ORDER BY s.song_key""", (sorted(want),)).fetchall()
            parts = {}
            for k, p, v in conn.execute("SELECT song_key, part, sound FROM song_parts WHERE song_key = ANY(%s)",
                                        (sorted(want),)):
                parts.setdefault(k, {})[p] = _vec(v)
    except Exception as e:
        print(f"  (database query failed: {str(e).splitlines()[0][:120]}; run python import_results.py; "
              "reading results/ files instead)")
        return None
    if len(rows) < len(want):
        print(f"  (the database has {len(rows)} of {len(want)} analysed songs: run python import_results.py; "
              "reading results/ files instead)")
        return None
    P = {k: [] for k in ("key", "source", "artist", "artist_name", "title", "link", "listens", "group", "whole",
                         "parts", "inst", "va_vg", "va_mc", "bpm", "confidence", "steadiness", "busyness")}
    for (k, src, artist, title, page, listens, group, sound, inst, vgv, vga, v, a, bpm, conf, stead, busy) in rows:
        whole = _vec(sound)
        pp = [parts.get(k, {}).get(i) for i in range(3)]
        pp = [x if x is not None else whole for x in pp]
        P["key"].append(k); P["source"].append(src); P["artist"].append((artist or k).lower()); P["artist_name"].append(artist)
        P["title"].append(title); P["group"].append(group)
        P["link"].append(page or (f"https://www.jamendo.com/track/{k.split('_', 1)[1]}" if k.startswith("jamendo_") else ""))
        P["listens"].append(float(listens) if listens is not None else np.nan)
        P["whole"].append(whole); P["parts"].append(np.stack(pp)); P["inst"].append(_vec(inst))
        P["va_vg"].append([np.nan if vgv is None else vgv, np.nan if vga is None else vga]); P["va_mc"].append([v, a])
        P["bpm"].append(bpm or 0.0); P["confidence"].append(conf or 0.0)
        P["steadiness"].append(stead or 0.0); P["busyness"].append(busy or 0.0)
    for k in ("whole", "parts", "inst", "va_vg", "va_mc", "bpm", "confidence", "steadiness", "busyness", "listens"):
        P[k] = np.array(P[k], float)
    P["from"] = "database"
    return P
