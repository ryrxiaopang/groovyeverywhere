"""Train OUR OWN small happy-vs-sad model (a candidate Mood) on the TRAINING-split songs.

  python train_mood.py        -> own_mood.npz (used by evaluate.py as the candidate "own model")

What it learns from: the numbers we already compute for every song (Sound's 1,280 + MusiCNN's 200),
labelled happy or sad by people (MTG-Jamendo tags), using ONLY songs from the train_mood_* groups.
It is then scored by evaluate.py on validation songs it never saw (different split, no shared artists).
Method: logistic regression (a weighted sum of the numbers, squashed to a 0-1 'how happy' score)
with a penalty against over-fitting, picked by 5-fold cross-validation grouped by artist.
"""
import csv, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")


def load_train():
    from results_index import latest_rows
    rows = latest_rows(RES)
    X, y, art = [], [], []
    for k, r in rows.items():
        g = r.get("group", "")
        if r["status"] != "done" or g not in ("train_mood_happy", "train_mood_sad"):
            continue
        p = os.path.join(RES, f"{k}.npz")
        if not os.path.exists(p):
            continue
        d = np.load(p)
        X.append(np.concatenate([d["effnet_whole"], d["musicnn_whole"]]).astype(np.float64))
        y.append(1.0 if g == "train_mood_happy" else 0.0)
        art.append(r.get("mtg_artist") or r.get("artist") or k)
    return np.array(X), np.array(y), np.array(art)


def fit(X, y, lam, iters=600, lr=0.1):
    w = np.zeros(X.shape[1]); b = 0.0
    lr = lr / (1 + lam / len(y))          # smaller steps for strong penalties, so the fit can't overshoot and blow up
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w + b, -30, 30)))
        g = p - y
        w -= lr * (X.T @ g / len(y) + lam * w / len(y))
        b -= lr * g.mean()
    return w, b


def auc(s, y):
    pos, neg = s[y == 1], s[y == 0]
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def main():
    X, y, art = load_train()
    if len(y) < 100:
        raise SystemExit(f"only {len(y)} training songs analysed; run the big pass first (bigpass.csv)")
    print(f"{int(y.sum())} happy + {int((1 - y).sum())} sad training songs")
    if min(y.sum(), (1 - y).sum()) < 30:
        raise SystemExit("need at least 30 happy AND 30 sad training songs")
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    arts = np.unique(art); rng = np.random.default_rng(0); rng.shuffle(arts)
    fold = {a: i % 5 for i, a in enumerate(arts)}
    f = np.array([fold[a] for a in art])
    best = None
    for lam in (1.0, 10.0, 100.0, 1000.0, 10000.0):
        scores = []
        for k in range(5):
            tr, te = f != k, f == k
            if len(set(y[te])) < 2 or len(set(y[tr])) < 2:
                continue
            w, b = fit(Z[tr], y[tr], lam)
            scores.append(auc(Z[te] @ w + b, y[te]))
        m = float(np.mean(scores))
        print(f"  penalty {lam:7.1f}: cross-validated happy-vs-sad score {m:.3f}")
        if best is None or m > best[1]:
            best = (lam, m)
    w, b = fit(Z, y, best[0])
    np.savez(os.path.join(HERE, "own_mood.npz"), mu=mu, sd=sd, w=w, b=b, lam=best[0], cv_auc=best[1], n=len(y))
    print(f"saved own_mood.npz (penalty {best[0]}, cross-validated score {best[1]:.3f}); now run python evaluate.py")


if __name__ == "__main__":
    main()
