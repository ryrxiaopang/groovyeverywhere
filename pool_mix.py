"""How much of the recommendation pool is in our focus genres AND has singing?

  python pool_mix.py

Genre = the genre the song was collected under (its pool group: pool_rock, pool_vocal_pop, pool_audius_hip-hop_rap,
pool_jamendo_korean_rnb, ...). That is the site's / artist's own label, not something we measured.
Singing = the instrument model's 'voice' score. The cut-off is set from songs that Jamendo labels vocal or
instrumental (the same check as evaluate.py T3, score 0.88), and printed with its accuracy.
"""
import os
from collections import Counter
import numpy as np
import psycopg
from pgvector.psycopg import register_vector
import models

DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")
FOCUS = ["pop", "rnb", "hiphop", "indie", "alternative", "rock", "singer-songwriter", "electronic"]
from results_index import genre_of


def vec(v):
    return np.asarray(v.to_numpy() if hasattr(v, "to_numpy") else v, float)


def singing():
    """(rows, sung bool array, cut-off, agreement, n vocal, n instrumental) for every analysed song."""
    vi = models.classes("instruments").index("voice")
    with psycopg.connect(DB) as conn:
        register_vector(conn)
        rows = conn.execute("""SELECT s.song_key, coalesce(s.test_group, ''), f.instruments,
                                      lower(coalesce(s.vocal_instrumental, '')), coalesce(s.in_pool, false)
                               FROM songs s JOIN features f USING (song_key)
                               WHERE f.instruments IS NOT NULL AND NOT coalesce(s.excluded, false)""").fetchall()
    voice = np.array([vec(r[2])[vi] for r in rows])
    label = np.array([r[3] for r in rows])

    # cut-off: the one that best separates Jamendo's own vocal / instrumental labels (balanced accuracy)
    lab = np.isin(label, ("vocal", "instrumental"))
    y = label[lab] == "vocal"; s = voice[lab]
    best_t, best_acc = 0.5, 0.0
    if y.sum() < 10 or (~y).sum() < 10:
        raise SystemExit("too few songs with Jamendo's vocal/instrumental label to set the singing cut-off")
    for t in np.unique(np.quantile(s, np.linspace(0.02, 0.98, 97))):
        acc = 0.5 * (np.mean(s[y] >= t) + np.mean(s[~y] < t))
        if acc > best_acc:
            best_t, best_acc = float(t), acc
    sung = voice >= best_t
    return rows, sung, best_t, best_acc, int(y.sum()), int((~y).sum())


def main():
    rows, sung, best_t, best_acc, nv, ni = singing()
    pool = np.array([r[4] for r in rows])
    if not pool.any():
        raise SystemExit("no songs marked as in the pool: run python import_results.py first")
    print(f"singing cut-off: voice score >= {best_t:.2f}, which agrees with Jamendo's vocal/instrumental label "
          f"{100 * best_acc:.0f}% of the time (balanced, {nv} vocal / {ni} instrumental songs)\n")

    P = [i for i in range(len(rows)) if pool[i]]
    genres = [genre_of(rows[i][1]) for i in P]
    by = Counter(); by_sung = Counter()
    for i, g in zip(P, genres):
        by[g] += 1; by_sung[g] += bool(sung[i])
    n = len(P)
    focus_n = sum(by[g] for g in FOCUS); focus_s = sum(by_sung[g] for g in FOCUS)
    print(f"{'focus genre':18s} {'songs':>6s} {'with singing':>13s}")
    for g in FOCUS:
        print(f"  {g:16s} {by[g]:6d} {by_sung[g]:7d} ({100 * by_sung[g] / max(by[g], 1):3.0f}%)")
    print(f"  {'all focus':16s} {focus_n:6d} {focus_s:7d} ({100 * focus_s / max(focus_n, 1):3.0f}%)\n")
    other = {g: c for g, c in by.items() if g not in FOCUS}
    other_s = sum(by_sung[g] for g in other)
    print(f"other genres: {sum(other.values())} songs, {other_s} with singing")
    print("  " + ", ".join(f"{g} {c}" for g, c in sorted(other.items(), key=lambda x: -x[1])))
    print(f"\nwhole pool: {n} songs, {int(sung[P].sum())} with singing ({100 * sung[P].mean():.0f}%)")
    print(f"focus genre AND singing: {focus_s} songs = {100 * focus_s / n:.0f}% of the pool")


if __name__ == "__main__":
    main()
