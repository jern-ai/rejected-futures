"""The MCP server: recall and record, plus the candidate queue the host model distils.
Runs over stdio. Nothing here calls a provider."""
import os

from mcp.server.mcpserver import MCPServer

from . import anchors as A
from . import recall as R
from . import store

mcp = MCPServer("rejected-futures", instructions=(
    "Decision memory mined from this developer's own agent transcripts and git history. "
    "Call recall before the first edit of a task and before committing. Claims are context, "
    "never a gate: judge whether each applies, and say so when you depart from one. "
    "Call record when the developer corrects you or states a rule, so it is kept without "
    "waiting for the watcher. Call candidates and resolve to distil flagged turns into claims."))


def _project(project):
    p = project or os.getcwd()
    return A.toplevel(p) or p


@mcp.tool()
def recall(query: str, diff: str = "", project: str = "", k: int = 3) -> str:
    """Return the claims most relevant to a task description and/or a unified diff, with
    evidence and code anchors. query: what is about to be done. diff: optional `git diff`
    output. project: repository path (defaults to the current directory)."""
    cfg = store.load_config()
    res = R.rank(query, diff=diff, project=_project(project), k=k, anchor_weight=cfg["anchor_weight"])
    return R.render(res) or "No claims on record for this repository match that."


@mcp.tool()
def record(statement: str, kind: str = "decision", scope: str = "repository", project: str = "",
           quote: str = "", anchors: list[str] | None = None) -> str:
    """Record a claim now, in the developer's terms. kind: decision | invariant | preference |
    rejected | fact. scope: repository (this repo only) or personal (every repo). quote: the
    developer's words that formed it. anchors: optional path::symbol keys it governs."""
    ev = [dict(source="agent", at=store.now_iso(), quote=quote)] if quote else []
    c = store.new_claim(statement, kind=kind, scope=scope, project=_project(project) if scope == "repository" else "",
                        evidence=ev, anchors=anchors or [])
    return f"recorded {c['id']}"


@mcp.tool()
def candidates(limit: int = 10, project: str = "") -> str:
    """Flagged (turn, resolution) pairs from past sessions that nobody has read yet. Read each
    and call resolve with a claim or a skip. Only pairs for the current repository by default;
    pass project="*" for all."""
    cs = store.open_candidates(project=None if project == "*" else _project(project), limit=limit)
    if not cs:
        return "No open candidates."
    out = []
    for c in cs:
        out.append(f"=== {c['id']} [{(c.get('ts') or '')[:10]} {c.get('project', '')} p={c.get('p', 0):.2f}]\n"
                   f"--- assistant before (tail): {c.get('prev', '')[-400:]}\n"
                   f"--- USER: {c.get('user', '')[:1200]}\n"
                   f"--- assistant after (head): {c.get('next', '')[:800]}")
    return "\n\n".join(out)


@mcp.tool()
def resolve(candidate_id: str, action: str, statement: str = "", kind: str = "decision",
            scope: str = "repository", quote: str = "") -> str:
    """Resolve a candidate: action "claim" records a claim from it (statement, kind, scope;
    quote defaults to the user's turn), action "skip" marks it read with nothing to keep."""
    cs = [c for c in store.load_candidates() if c.get("id") == candidate_id]
    if not cs:
        return f"no candidate {candidate_id}"
    c = cs[0]
    if action == "skip":
        store.resolve_candidate(candidate_id, "skipped")
        return f"skipped {candidate_id}"
    if action != "claim" or not statement.strip():
        return "action must be claim (with a statement) or skip"
    ev = [dict(source=c.get("source", "claude-code"), session=c.get("session", ""), at=c.get("ts", ""),
               quote=(quote or c.get("user", ""))[:600])]
    claim = store.new_claim(statement, kind=kind, scope=scope, project=c.get("project", "") if scope == "repository" else "",
                            since=c.get("ts"), evidence=ev)
    store.resolve_candidate(candidate_id, "claimed", claim["id"])
    try:
        from .cli import anchor_claim
        n = anchor_claim(claim["id"])
        return f"recorded {claim['id']} ({n} anchors)"
    except Exception as e:  # anchoring is best effort
        return f"recorded {claim['id']} (no anchors: {e})"


@mcp.tool()
def claims(project: str = "", status: str = "held") -> str:
    """List claims for a repository (plus personal ones). status: held | retired | contradicted | all."""
    cs = store.list_claims(project=_project(project), status=status)
    if not cs:
        return "No claims."
    return "\n".join(f"[{c['id']}] ({c.get('kind')}, {c.get('scope')}, {c.get('status')}, since {c.get('since')}) {c['statement']}"
                     for c in cs)


@mcp.tool()
def retire(claim_id: str, status: str = "retired") -> str:
    """Mark a claim retired (no longer held) or contradicted (the code now departs from it)."""
    c = store.load_claim(claim_id)
    c["status"] = status
    store.save_claim(c)
    return f"{claim_id} is now {status}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
