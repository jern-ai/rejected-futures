"""Train the candidate classifier from the hand-labelled turns of the 2026-09-14 experiment
and write src/rejected_futures/model.json. Needs scikit-learn; the product does not.

    python tools/train.py <scratchpad dir with triples.json, scored.json, labels.py, unseen_sample_keys.json>

The labelled triples are also saved (redacted, private) under $RF_HOME/training so the model
can be retrained without the scratchpad."""
import json
import os
import random
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rejected_futures import paths  # noqa: E402
from rejected_futures.classify import features  # noqa: E402


def load_labelled(scratch):
    sys.path.insert(0, scratch)
    from labels import label_c, label_z, label_u  # noqa
    triples = json.load(open(os.path.join(scratch, "triples.json")))
    scored = json.load(open(os.path.join(scratch, "scored.json")))
    by_key = {(t["project"], t["session"], t["ts"]): t for t in triples}
    key_of = lambda s: (s["project"], s["session"], s["ts"])
    cand = sorted([s for s in scored if s["score"] >= 2], key=lambda s: (s["project"], s["ts"] or ""))
    random.seed(7)
    control = random.sample([s for s in scored if s["score"] == 0], 60)
    out = []
    for k, s in enumerate(cand):
        t = by_key.get(key_of(s))
        if t is not None:
            out.append((t, label_c(k), "cand"))
    for k, s in enumerate(control):
        t = by_key.get(key_of(s))
        if t is not None:
            out.append((t, label_z(k), "ctrl"))
    p = os.path.join(scratch, "unseen_sample_keys.json")
    if os.path.exists(p):
        for k, (pr, se, ts, _) in enumerate(json.load(open(p))):
            t = by_key.get((pr, se, ts))
            if t is not None:
                out.append((t, label_u(k), "unseen"))
    return [(t, 1 if l == "pos" else 0, src) for t, l, src in out if l != "summary"]


def main():
    if len(sys.argv) > 1:
        labelled = load_labelled(sys.argv[1])
        paths.ensure()
        os.makedirs(os.path.join(paths.HOME, "training"), exist_ok=True)
        with open(os.path.join(paths.HOME, "training", "labelled.json"), "w") as f:
            json.dump([dict(t, y=y, src=src) for t, y, src in labelled], f)
    else:
        rows = json.load(open(os.path.join(paths.HOME, "training", "labelled.json")))
        labelled = [(r, r["y"], r["src"]) for r in rows]
    ys = np.array([y for _, y, _ in labelled])
    src = np.array([s for _, _, s in labelled])
    X = features([t for t, _, _ in labelled])
    print(f"{len(ys)} labelled turns, {int(ys.sum())} positive, {X.shape[1]} features")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=1)
    prob = np.zeros(len(ys))
    for tr, te in skf.split(X, ys):
        clf = LogisticRegression(C=2.0, max_iter=3000, class_weight="balanced").fit(X[tr], ys[tr])
        prob[te] = clf.predict_proba(X[te])[:, 1]
    print("\n5-fold cross-validation:")
    print("  thr  prec  rec  F1   recall on regex-missed positives")
    chosen = None
    for th in np.arange(0.20, 0.91, 0.05):
        pred = prob >= th
        tp = int(((pred == 1) & (ys == 1)).sum()); fp = int(((pred == 1) & (ys == 0)).sum()); fn = int(((pred == 0) & (ys == 1)).sum())
        P = tp / max(tp + fp, 1); R = tp / max(tp + fn, 1); F = 2 * P * R / max(P + R, 1e-9)
        ctrl = src == "ctrl"
        cr = ((prob[ctrl] >= th) & (ys[ctrl] == 1)).sum() / max(ys[ctrl].sum(), 1)
        print(f"  {th:.2f} {P:.2f}  {R:.2f} {F:.2f}  {cr:.2f}")
        if chosen is None and R < 0.85:
            chosen = round(float(th - 0.05), 2)
    chosen = chosen or 0.4
    clf = LogisticRegression(C=2.0, max_iter=3000, class_weight="balanced").fit(X, ys)
    model = dict(coef=[round(float(x), 6) for x in clf.coef_[0]], intercept=float(clf.intercept_[0]),
                 threshold=chosen, views=["user", "user+next"], embedding="BAAI/bge-small-en-v1.5",
                 trained_on=len(ys), positives=int(ys.sum()))
    out = os.path.join(os.path.dirname(__file__), "..", "src", "rejected_futures", "model.json")
    with open(out, "w") as f:
        json.dump(model, f)
    print(f"\nwrote {os.path.relpath(out)} with threshold {chosen} (highest threshold keeping CV recall >= 0.85)")


if __name__ == "__main__":
    main()
