"""Claims are plain files: one Markdown file per claim with YAML front matter, yours to
edit. Candidates (pairs the classifier flagged, waiting for a read) live in one JSON
lines file. State remembers which turns were seen."""
import json
import os
import re
import time
from datetime import datetime, timezone

import yaml

from . import paths

KINDS = ("decision", "invariant", "preference", "rejected", "fact")
SCOPES = ("repository", "personal")
STATUSES = ("held", "retired", "contradicted", "suggested", "superseded")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    words = s.split("-")
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > limit:
            break
        out = (out + "-" + w) if out else w
    return out or "claim"


# ---- state ----------------------------------------------------------------------------

def load_state():
    if os.path.exists(paths.STATE):
        with open(paths.STATE) as f:
            return json.load(f)
    return {"files": {}, "seen": []}


def save_state(state):
    paths.ensure()
    tmp = paths.STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, paths.STATE)


def load_config():
    cfg = {"threshold": None, "recall_floor": None, "anchor_weight": 0.3, "top_k": 3,
           "skip_projects": []}
    if os.path.exists(paths.CONFIG):
        with open(paths.CONFIG) as f:
            cfg.update(json.load(f))
    return cfg


# ---- candidates -----------------------------------------------------------------------

def append_candidates(cands):
    paths.ensure()
    with open(paths.CANDIDATES, "a") as f:
        for c in cands:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def load_candidates():
    if not os.path.exists(paths.CANDIDATES):
        return []
    out = []
    with open(paths.CANDIDATES) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def save_candidates(cands):
    paths.ensure()
    tmp = paths.CANDIDATES + ".tmp"
    with open(tmp, "w") as f:
        for c in cands:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    os.replace(tmp, paths.CANDIDATES)


def open_candidates(project=None, limit=None):
    cs = [c for c in load_candidates() if c.get("status", "open") == "open"]
    if project:
        cs = [c for c in cs if same_project(c.get("project", ""), project)]
    cs.sort(key=lambda c: -c.get("p", 0))
    return cs[:limit] if limit else cs


def resolve_candidate(cid, status, claim_id=None):
    cs = load_candidates()
    hit = None
    for c in cs:
        if c.get("id") == cid:
            c["status"] = status
            c["resolved"] = now_iso()
            if claim_id:
                c["claim"] = claim_id
            hit = c
    if hit is None:
        raise KeyError(cid)
    save_candidates(cs)
    return hit


# ---- claims ---------------------------------------------------------------------------

FRONT = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


def claim_path(cid):
    return os.path.join(paths.CLAIMS, cid + ".md")


def load_claim(cid_or_path):
    p = cid_or_path if cid_or_path.endswith(".md") else claim_path(cid_or_path)
    with open(p, encoding="utf-8") as f:
        raw = f.read()
    m = FRONT.match(raw)
    if not m:
        raise ValueError(f"{p}: no front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    meta["statement"] = m.group(2).strip()
    meta.setdefault("id", os.path.splitext(os.path.basename(p))[0])
    meta.setdefault("evidence", [])
    meta.setdefault("anchors", [])
    meta.setdefault("status", "held")
    meta.setdefault("scope", "repository")
    meta.setdefault("project", "")
    return meta


def save_claim(c):
    paths.ensure()
    body = c["statement"].strip() + "\n"
    meta = {k: v for k, v in c.items() if k != "statement"}
    meta["updated"] = now_iso()
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=100)
    with open(claim_path(c["id"]), "w", encoding="utf-8") as f:
        f.write("---\n" + front + "---\n" + body)
    return c["id"]


def list_claims(project=None, status="held", include_personal=True):
    paths.ensure()
    out = []
    for f in sorted(os.listdir(paths.CLAIMS)):
        if not f.endswith(".md"):
            continue
        try:
            c = load_claim(os.path.join(paths.CLAIMS, f))
        except Exception:
            continue
        if status and status != "all" and c.get("status") != status:
            continue
        if project:
            if c.get("scope") == "personal":
                if not include_personal:
                    continue
            elif not same_project(c.get("project", ""), project):
                continue
        out.append(c)
    return out


def same_project(a, b):
    if not a or not b:
        return False
    a = os.path.realpath(os.path.expanduser(a)).rstrip("/")
    b = os.path.realpath(os.path.expanduser(b)).rstrip("/")
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def new_claim(statement, kind="decision", scope="repository", project="", since=None,
              evidence=None, anchors=None, status="held"):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    base = slugify(statement)
    cid = base
    n = 2
    while os.path.exists(claim_path(cid)):
        cid = f"{base}-{n}"
        n += 1
    c = dict(id=cid, kind=kind, scope=scope, status=status,
             since=(since or now_iso())[:10], project=project if scope == "repository" else "",
             anchors=list(anchors or []), evidence=list(evidence or []),
             created=now_iso(), statement=statement.strip())
    save_claim(c)
    return c


def add_evidence(cid, ev):
    c = load_claim(cid)
    c["evidence"].append(ev)
    save_claim(c)
    return c


# ---- duplicate detection --------------------------------------------------------------

DUP_SIMILARITY = 0.88
MIN_QUOTE = 40


def _norm_quote(s):
    """Lower-cased, whitespace-collapsed text, for quote containment."""
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def find_duplicate(statement, project, scope, quote):
    """How a held claim this one repeats matched, or None.

    Returns (id, "quote") when the same words matched, or (id, "similar") when the statements
    are close enough to be the same topic. A personal claim reaches every repository, so a new
    repository-scope claim is compared with the repository claims in the same project
    (store.same_project) and with every held personal claim; a new personal claim is compared
    only with personal claims. A claim matches when either

    - the new quote, lower-cased and with whitespace collapsed, contains an existing claim's
      evidence quote or is contained in one, the shorter of the two being at least 40
      characters -- the record-then-mine case, which needs no model; or
    - the cosine similarity of the two statements, embedded the way recall.claim_vectors
      embeds claims (the same model, normalized), is at least 0.88; the most similar such claim
      is returned. Measured on 140 real claims, every pair at 0.88 or above was the same
      decision, and the first pair of different claims appeared at 0.866."""
    claims = []
    for c in list_claims(status="held"):
        cs = c.get("scope")
        if cs == "personal":
            claims.append(c)
        elif scope == "repository" and same_project(c.get("project", ""), project):
            claims.append(c)
    if not claims:
        return None
    nq = _norm_quote(quote)
    if nq:
        for c in claims:
            for ev in c.get("evidence") or []:
                ne = _norm_quote(ev.get("quote"))
                if min(len(nq), len(ne)) >= MIN_QUOTE and (nq in ne or ne in nq):
                    return (c["id"], "quote")
    from . import recall
    from .classify import embed
    q = embed([statement], normalize=True)[0]
    vecs = recall.claim_vectors(claims)
    best_id, best = None, -1.0
    for c in claims:
        sim = float(q @ vecs[c["id"]])
        if sim >= DUP_SIMILARITY and sim > best:
            best, best_id = sim, c["id"]
    if best_id is None:
        return None
    return (best_id, "similar")


def same_scope(a, b):
    """Whether two claims live in the same scope: same project for repository scope, or both
    personal."""
    if a.get("scope") != b.get("scope"):
        return False
    if a.get("scope") == "personal":
        return True
    return same_project(a.get("project", ""), b.get("project", ""))


def supersede(old_id, statement, kind="decision", project="", since=None, evidence=None,
              anchors=None):
    """Record a new claim that replaces an older one.

    The new claim is created as if there were no match. Its evidence is the new evidence
    followed by the old claim's evidence, each carried entry marked superseded. If it has no
    anchors of its own the old claim's anchors are copied. Then the old claim is marked
    superseded with superseded_by set to the new id."""
    old = load_claim(old_id)
    carried = []
    for ev in old.get("evidence") or []:
        e = dict(ev)
        e["superseded"] = True
        carried.append(e)
    new_anchors = list(anchors or []) or list(old.get("anchors") or [])
    c = new_claim(statement, kind=kind, scope=old.get("scope", "repository"), project=project,
                  since=since, evidence=list(evidence or []) + carried, anchors=new_anchors)
    old["status"] = "superseded"
    old["superseded_by"] = c["id"]
    save_claim(old)
    return c


def duplicate_pairs(threshold=0.80):
    """Held claim pairs that may be the same decision, cosine >= threshold, highest first.

    Each item is (score, a, b) with a and b whole claims. Claims are compared when they share a
    scope, and a personal claim is compared with every repository claim (it reaches every
    repository); repository claims in different projects are not compared. Read-only: it merges
    and retires nothing."""
    from . import recall
    claims = list_claims(status="held")
    personal = [c for c in claims if c.get("scope") == "personal"]
    groups = {}
    for c in claims:
        if c.get("scope") == "repository":
            groups.setdefault(c.get("project", ""), []).append(c)
    out = []

    def _pairwise(group):
        vecs = recall.claim_vectors(group)
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                sim = float(vecs[group[i]["id"]] @ vecs[group[j]["id"]])
                if sim >= threshold:
                    out.append((round(sim, 3), group[i], group[j]))

    if len(personal) >= 2:
        _pairwise(personal)
    for group in groups.values():
        if len(group) >= 2:
            _pairwise(group)
    for group in groups.values():
        if not group or not personal:
            continue
        vecs = recall.claim_vectors(personal + group)
        for p in personal:
            for r in group:
                sim = float(vecs[p["id"]] @ vecs[r["id"]])
                if sim >= threshold:
                    out.append((round(sim, 3), p, r))
    out.sort(key=lambda t: -t[0])
    return out
