"""Retrieve locally, judge with the host model, never block. Given a task or a diff,
return the few claims most likely to apply, each with its evidence."""
import hashlib
import json
import math
import os

import numpy as np

from . import anchors as A
from . import paths, store
from .classify import QUERY_PREFIX, embed


def _index_load():
    if os.path.exists(paths.INDEX):
        with open(paths.INDEX) as f:
            return json.load(f)
    return {}


def _index_save(ix):
    tmp = paths.INDEX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ix, f)
    os.replace(tmp, paths.INDEX)


def claim_vectors(claims):
    """Embedding per claim, cached by statement hash so edits re-embed and nothing else does."""
    ix = _index_load()
    todo, vecs = [], {}
    for c in claims:
        h = hashlib.sha1(c["statement"].encode("utf-8")).hexdigest()
        e = ix.get(c["id"])
        if e and e.get("h") == h:
            vecs[c["id"]] = np.asarray(e["v"], dtype=np.float32)
        else:
            todo.append((c, h))
    if todo:
        E = embed([c["statement"] for c, _ in todo], normalize=True)
        for (c, h), v in zip(todo, E):
            vecs[c["id"]] = v
            ix[c["id"]] = {"h": h, "v": [round(float(x), 5) for x in v]}
        _index_save(ix)
    return vecs


def rank(query, diff="", project="", k=3, anchor_weight=0.3, claims=None):
    project = project or os.getcwd()
    repo = A.toplevel(project) or project
    claims = claims if claims is not None else store.list_claims(project=repo, status="held")
    if not claims:
        return []
    text = (query or "").strip()
    if diff:
        text = (text + "\n\n" + diff[:4000]).strip()
    if not text:
        return []
    q = embed([QUERY_PREFIX + text], normalize=True)[0]
    vecs = claim_vectors(claims)
    touched = set(A.working_tree_symbols(repo, diff).keys()) if diff else set()
    out = []
    for c in claims:
        sim = float(q @ vecs[c["id"]])
        ov = A.anchor_overlap(c.get("anchors") or [], touched) if touched else 0.0
        out.append(dict(claim=c, similarity=round(sim, 3), anchor_overlap=round(ov, 2),
                        score=round(sim + anchor_weight * ov, 3)))
    out.sort(key=lambda r: -r["score"])
    return out[:k]


def default_floor(n_claims):
    """The score a claim needs before the prompt hook mentions it, given how many claims were
    ranked. The best score among unrelated claims rises with their number by chance alone, so a
    fixed floor is too strict for a new store and too loose for a large one. Measured on 97 real
    claims with 42 related and 30 unrelated prompts (2026-09-26), this keeps unrelated prompts
    firing at about 3-10% at any size: with 1 claim it shows 86% of related claims where a fixed
    0.65 showed 68%, and with 97 it fires on 10% of unrelated prompts where 0.65 fired on 23%."""
    return 0.61 + 0.015 * math.log(max(1, n_claims))


def render(results, floor=0.0, header=True):
    """Text for the host agent. It states what the tool is and is not."""
    results = [r for r in results if r["score"] >= floor]
    if not results:
        return ""
    lines = []
    if header:
        lines.append("Claims on record that may apply to this work (from rejected-futures; "
                     "decide yourself whether each one applies, and say so when you depart from one):")
    for r in results:
        c = r["claim"]
        lines.append(f"\n- [{c['id']}] ({c.get('kind')}, {c.get('scope')}, since {c.get('since')}, "
                     f"score {r['score']:.2f}) {c['statement']}")
        for ev in (c.get("evidence") or [])[:2]:
            q = (ev.get("quote") or "").strip().replace("\n", " ")
            if q:
                lines.append(f"    evidence {str(ev.get('at', ''))[:10]} {str(ev.get('session', ''))[:8]}: \"{q[:220]}\"")
        if c.get("anchors"):
            lines.append("    anchors: " + ", ".join(c["anchors"][:4]))
    return "\n".join(lines)
