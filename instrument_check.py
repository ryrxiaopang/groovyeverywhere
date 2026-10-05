"""Check the 'favourite instrument' option against human labels before users rely on it.

  python instrument_check.py

For every instrument a user can pick (scoring.INSTRUMENT_CHOICES) it reports, on the songs that have human
instrument labels (MTG-Jamendo):
  right when it says yes  - of the songs the app would call "has piano", how many humans also tagged piano
  finds                   - of the songs humans tagged piano, how many the app finds
  pool songs              - how many recommendation-pool songs would count as having it
for a few settings of the rule, so we can choose the setting with numbers instead of guessing.
"""
import os
import numpy as np
import psycopg
from pgvector.psycopg import register_vector
import models, scoring

DB = os.environ.get("HG_DB", "postgresql://hg:hg@localhost:5432/hiddengems")
SETTINGS = [(2, 95.0), (2, 90.0), (5, 101.0)]      # current rule first      # (top N strongest, pool percentile); 101 = top-N only


def main():
    names = models.classes("instruments")
    with psycopg.connect(DB) as conn:
        register_vector(conn)
        rows = conn.execute("""SELECT s.song_key, f.instruments, coalesce(s.in_pool, false)
                               FROM songs s JOIN features f USING (song_key)
                               WHERE f.instruments IS NOT NULL AND NOT coalesce(s.excluded, false)""").fetchall()
        tags = {}
        for k, t in conn.execute("SELECT song_key, tag FROM song_tags WHERE kind = 'instrument'"):
            tags.setdefault(k, set()).add(t.split("---")[-1].strip().lower())
    keys = [r[0] for r in rows]
    inst = np.stack([np.asarray(r[1].to_numpy() if hasattr(r[1], "to_numpy") else r[1], float) for r in rows])
    in_pool = np.array([r[2] for r in rows], bool)
    labelled = np.array([k in tags for k in keys])
    print(f"{len(keys)} analysed songs, {in_pool.sum()} in the pool, {labelled.sum()} with human instrument labels\n")
    if not in_pool.any():
        print("(no songs marked in_pool: run python import_results.py first)")
    for top, pct in SETTINGS:
        rule = f"in top {top}" + (f" or top {100 - pct:.0f}% of pool" if pct <= 100 else " only")
        print(f"rule: {rule}")
        print(f"  {'instrument':22s} {'right when yes':>14s} {'finds':>7s} {'labelled':>8s} {'pool songs':>11s}")
        for choice, cls in scoring.INSTRUMENT_CHOICES.items():
            # the pool percentile is taken over the pool, as in the app
            ref = inst[in_pool] if in_pool.any() else inst
            _, strength_ref = scoring.instrument_presence(ref, names, choice, top=top, pct=min(pct, 100.0))
            cutoff = np.nanpercentile(strength_ref, pct) if pct <= 100 else np.inf
            cols = [names.index(c) for c in cls if c in names]
            strength = inst[:, cols].max(axis=1)
            in_top = np.isin(np.argsort(-inst, axis=1)[:, :top], cols).any(axis=1)
            present = in_top | (strength >= cutoff)
            truth = np.array([bool(tags.get(k, set()) & set(cls)) for k in keys])
            L = labelled
            yes = present & L
            prec = (truth & yes).sum() / max(yes.sum(), 1)
            rec = (truth & present & L).sum() / max((truth & L).sum(), 1)
            print(f"  {choice:22s} {100 * prec:13.0f}% {100 * rec:6.0f}% {int((truth & L).sum()):8d} "
                  f"{int((present & in_pool).sum()):11d}")
        print()
    print("A good rule is right when it says yes most of the time (ideally 60%+) while still finding a fair share.\n"
          "Instruments with few labelled songs (under ~15) can't be judged yet.")


if __name__ == "__main__":
    main()
