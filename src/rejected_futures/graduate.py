"""Graduation suggestions: held claims worth moving into the repository as a test or a doc
line, ranked, with a proposed target each. Read-only: it writes no claim, candidate or state
file. This is the first step of a larger feature; only the suggestion list is implemented."""
import os

from . import store

KIND_ORDER = {"invariant": 0, "rejected": 1, "decision": 2, "fact": 3, "preference": 4}

DOC_NAMES = ("CLAUDE.md", "AGENTS.md")

NO_DOC = "doc (no CLAUDE.md or AGENTS.md in this repository)"

PERSONAL_DOC = "doc: ~/.claude/CLAUDE.md"


def _repo_doc(project):
    """The repository doc target: CLAUDE.md or AGENTS.md at the root if one exists, else the
    note that neither does. Never proposes creating a new file."""
    root = project or ""
    for name in DOC_NAMES:
        if root and os.path.exists(os.path.join(root, name)):
            return f"doc: {name}"
    return NO_DOC


def target_for(claim):
    """(target, covers) for one claim. target is "test" or a "doc..." string; covers is the
    anchors a test should cover (empty for a doc target)."""
    anchors = list(claim.get("anchors") or [])
    if claim.get("scope") == "personal":
        return PERSONAL_DOC, []
    kind = claim.get("kind")
    if kind == "invariant":
        return "test", anchors[:3]
    if kind == "rejected":
        if anchors:
            return "test", anchors[:3]
        return _repo_doc(claim.get("project")), []
    return _repo_doc(claim.get("project")), []


def _live_evidence(claim):
    return [e for e in (claim.get("evidence") or []) if not e.get("superseded")]


def _restated(claim):
    return len(_live_evidence(claim)) > 1


def _sort_key(claim):
    """Restated first; then kind (invariant, rejected, decision, fact, preference); then
    anchored before unanchored; then older since first; then id for stability."""
    return (
        0 if _restated(claim) else 1,
        KIND_ORDER.get(claim.get("kind"), len(KIND_ORDER)),
        0 if claim.get("anchors") else 1,
        str(claim.get("since") or ""),
        str(claim.get("id") or ""),
    )


def suggest(project=None, limit=10):
    """Ranked held claims for a project (repository claims plus personal ones), each with its
    proposed target. project None means every project. Returns a list of dicts; writes
    nothing."""
    claims = store.list_claims(project=project, status="held")
    claims.sort(key=_sort_key)
    if limit is not None:
        claims = claims[:limit]
    out = []
    for c in claims:
        target, covers = target_for(c)
        out.append(dict(id=c["id"], kind=c.get("kind"), scope=c.get("scope"),
                        since=c.get("since"), evidence=len(c.get("evidence") or []),
                        anchors=len(c.get("anchors") or []), target=target, covers=covers,
                        statement=c["statement"]))
    return out


def render(suggestions):
    """The suggestion text, one block per claim, ending with a count line."""
    if not suggestions:
        return "no held claims for this project"
    lines = []
    for s in suggestions:
        target = s["target"]
        if target == "test" and s["covers"]:
            target = "test (covers: " + ", ".join(s["covers"]) + ")"
        lines.append(f"[{s['id']}] ({s['kind']}, {s['scope']}, {s['since']}, "
                     f"{s['evidence']} evidence, {s['anchors']} anchors) -> {target}")
        lines.append(s["statement"].replace("\n", " ")[:160])
    lines.append(f"{len(suggestions)} claims suggested")
    return "\n".join(lines)
