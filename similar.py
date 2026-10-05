"""The 10 closest songs by Sound, straight from PostgreSQL (shows the database works).

  python similar.py 959961                          # a Jamendo id (or a song key: fma_2048, audius_abc)
  python similar.py "japanese girl"                 # or part of a title
  python similar.py "japanese girl" --instrument piano          # songs featuring piano come first
  python similar.py "japanese girl" --instrument piano --only   # only songs featuring piano
  python similar.py --instruments                   # list the instruments you can pick

The favourite instrument only re-orders (or filters) the closest Sound matches: it never pulls in a song that
doesn't sound like the starting song. Results come from the recommendation pool, one song per artist.
"""
import argparse, os, sys
import numpy as np
import psycopg
from pgvector.psycopg import register_vector
import scoring

DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")
TOP_SHARE = 0.10         # the instrument may choose among the closest 10% by Sound (the app's 90% match bar)


def vec(v):
    return np.asarray(v.to_numpy() if hasattr(v, "to_numpy") else v, float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*")
    ap.add_argument("--instrument", help="favourite instrument, e.g. piano (see --instruments)")
    ap.add_argument("--only", action="store_true", help="only songs featuring that instrument")
    ap.add_argument("--instruments", action="store_true", help="list the instruments you can pick")
    a = ap.parse_args()
    if a.instruments:
        print("You can pick: " + ", ".join(scoring.INSTRUMENT_CHOICES)); return
    if a.instrument and a.instrument.lower() not in scoring.INSTRUMENT_CHOICES:
        sys.exit(f"unknown instrument {a.instrument!r}. You can pick: {', '.join(scoring.INSTRUMENT_CHOICES)}")
    if a.only and a.instrument and a.instrument.lower() not in scoring.ONLY_OK:
        sys.exit(f"'--only' is offered for {', '.join(sorted(scoring.ONLY_OK))}: for {a.instrument} the detector "
                 "is wrong too often to leave other songs out. Without --only it still moves those songs up.")
    q = " ".join(a.query) or "959961"
    with psycopg.connect(DB) as conn:
        register_vector(conn)
        # exact song key (fma_2048, jamendo_959961) first, then an exact title, then a bare Jamendo number,
        # then part of a title; ties go to pool songs, then alphabetical, so the pick is always the same
        row = conn.execute("""SELECT s.song_key, s.title, s.artist, f.sound FROM songs s JOIN features f USING (song_key)
                              WHERE s.song_key = %s OR lower(s.title) = lower(%s)
                                 OR (s.source = 'jamendo' AND s.source_id = %s) OR s.title ILIKE %s
                              ORDER BY (s.song_key = %s) DESC, (lower(s.title) = lower(%s)) DESC,
                                       (s.source = 'jamendo' AND s.source_id = %s) DESC,
                                       coalesce(s.in_pool, false) DESC, s.song_key
                              LIMIT 1""", (q, q, q, f"%{q}%", q, q, q)).fetchone()
        if not row:
            sys.exit(f"no song matching {q!r}")
        key, title, artist, v = row
        n_pool = conn.execute("SELECT count(*) FROM songs WHERE coalesce(in_pool, false)").fetchone()[0]
        CANDIDATES = max(60, int(n_pool * TOP_SHARE)) if a.instrument else 60
        # exact search over the pool (a few thousand songs: fast). The quick index search would stop after
        # ~40 songs and THEN drop the non-pool ones, returning far fewer than asked for.
        conn.execute("SET LOCAL enable_indexscan = off")
        found = conn.execute(
            """SELECT s.song_key, s.title, s.artist, 1 - (f.sound <=> %s) AS cosine, s.test_group
               FROM features f JOIN songs s USING (song_key)
               WHERE s.song_key <> %s AND coalesce(s.in_pool, false) AND NOT coalesce(s.excluded, false)
                 AND (coalesce(%s, '') = '' OR lower(trim(coalesce(s.artist, ''))) <> lower(trim(%s)))
               ORDER BY f.sound <=> %s LIMIT %s""", (v, key, artist, artist, v, CANDIDATES)).fetchall()
        if not found:
            sys.exit("no pool songs found: run python import_results.py (it marks which songs are in the pool)")
        favour = None
        if a.instrument:
            import models
            names = models.classes("instruments")
            pool = conn.execute("""SELECT s.song_key, f.instruments FROM songs s JOIN features f USING (song_key)
                                   WHERE coalesce(s.in_pool, false) AND f.instruments IS NOT NULL""").fetchall()
            pk = [k for k, _ in pool]
            M = np.stack([vec(x) for _, x in pool])
            present, _ = scoring.instrument_presence(M, names, a.instrument.lower())
            some = (scoring.instrument_somewhere(M, names, a.instrument.lower())
                    if a.instrument.lower() in scoring.SOME_OK else np.zeros(len(pk), bool))
            tier_of = {k: (2 if p else 1 if s_ else 0) for k, p, s_ in zip(pk, present, some)}
            # 2 = clearly features it, 1 = it's in there somewhere (top 5 instruments), 0 = not detected
            tier = [tier_of.get(k, 0) for k, *_ in found]
            favour = [t_ == 2 for t_ in tier]
    print(f"Closest to: {title} / {artist}" + (f"   (favourite instrument: {a.instrument}"
                                                + (", only" if a.only else "") + ")" if a.instrument else "") + "\n")
    seen, order = set(), list(range(len(found)))
    if favour is not None:
        if a.only:
            order = [i for i in order if tier[i] == 2]
        else:
            # songs that clearly feature it first (the user asked for it); songs with only "some" of it take
            # every other place, so weaker Sound matches never crowd out the closest ones; Sound order within each
            first = [i for i in order if tier[i] == 2]
            some_ = [i for i in order if tier[i] == 1]
            rest = [i for i in order if tier[i] == 0]
            mixed = []
            while some_ or rest:
                if some_: mixed.append(some_.pop(0))
                if rest: mixed.append(rest.pop(0))
            order = first + mixed
    shown = 0
    for i in order:
        k, t, ar, sim, g = found[i]
        if (ar or "").strip().lower() in seen:     # one song per artist (case and spaces ignored)
            continue
        seen.add((ar or "").strip().lower())
        mark = {2: "  [features it]", 1: "  [some]", 0: ""}[tier[i]] if favour is not None else ""
        print(f"  {sim:.3f}  {t} / {ar}  [{g}]{mark}")
        shown += 1
        if shown == 10:
            break
    if favour is not None and not any(favour):
        n_some = sum(t_ == 1 for t_ in tier)
        print(f"\n  none of the {len(found)} closest matches clearly feature {a.instrument}"
              + (f"; {n_some} have some, marked [some] and given every other place" if n_some and not a.only else "")
              + (". Try without --only" if a.only else "")
              + ". The instrument never pulls in songs that don't sound alike.")
    elif favour is not None and a.only and shown < 10:
        print(f"\n  only {shown} of the {CANDIDATES} closest matches feature {a.instrument}: "
              "a short honest list beats padding with poor matches")


if __name__ == "__main__":
    main()
