"""The rf command."""
import argparse
import json
import os
import subprocess
import sys
import time

from . import anchors as A
from . import paths, store
from .sources import claude_code


def log(msg):
    paths.ensure()
    line = f"{store.now_iso()} {msg}"
    with open(paths.LOG, "a") as f:
        f.write(line + "\n")
    return line


# ---- scan --------------------------------------------------------------------------------

def scan(all_files=False, threshold=None, quiet=False, limit_files=None):
    from .classify import Model
    cfg = store.load_config()
    model = Model.load()
    th = threshold if threshold is not None else (cfg["threshold"] or model.threshold)
    state = store.load_state()
    seen = set(state.get("seen", []))
    files = list(claude_code.session_files())
    if limit_files:
        files = files[-limit_files:]
    fresh = []
    for p in files:
        st = os.stat(p)
        rec = state["files"].get(p)
        if not all_files and rec and rec.get("size") == st.st_size and rec.get("mtime") == st.st_mtime:
            continue
        fresh.append((p, st))
    new_triples = []
    for p, st in fresh:
        for t in claude_code.triples(p):
            if t["turn"] in seen:
                continue
            if t["kind"] != "turn":
                seen.add(t["turn"])  # compaction summaries: kept out of the classifier for now
                continue
            if any(store.same_project(t["project"], s) for s in cfg["skip_projects"]):
                seen.add(t["turn"])
                continue
            new_triples.append(t)
        state["files"][p] = {"size": st.st_size, "mtime": st.st_mtime}
    flagged = []
    if new_triples:
        probs = model.score(new_triples)
        for t, p in zip(new_triples, probs):
            seen.add(t["turn"])
            if p >= th:
                flagged.append(dict(id=t["turn"], source=t["source"], session=t["session"], ts=t["ts"],
                                    project=t["project"], branch=t["branch"], p=round(float(p), 3),
                                    prev=t["prev"][-600:], user=t["user"][:2000], next=t["next"][:1500],
                                    status="open", found=store.now_iso()))
        store.append_candidates(flagged)
    state["seen"] = sorted(seen)
    state["last_scan"] = store.now_iso()
    store.save_state(state)
    msg = f"scan: {len(fresh)} changed session files, {len(new_triples)} new turns, {len(flagged)} flagged at {th:.2f}"
    log(msg)
    if not quiet:
        print(msg)
    return flagged


def watch(interval):
    print(f"watching {claude_code.ROOT} every {interval}s; claims in {paths.CLAIMS}")
    while True:
        try:
            scan(quiet=True)
        except Exception as e:
            log(f"scan failed: {e}")
        time.sleep(interval)


# ---- anchors -----------------------------------------------------------------------------

def anchor_claim(cid, share=0.1, max_n=8):
    """Anchors from the claim's origin commits: the ones listed on the claim, else the commits
    made in the window after each evidence turn (to the next human turn, or the rest of the day)."""
    from datetime import datetime, timedelta
    c = store.load_claim(cid)
    repo = A.toplevel(c.get("project") or "") if c.get("project") else None
    if not repo:
        return 0
    hashes = list(c.get("commits") or [])
    if not hashes:
        for ev in c.get("evidence") or []:
            at = str(ev.get("at") or "")
            if not at:
                continue
            until = ev.get("until")
            if not until:
                try:
                    t0 = datetime.fromisoformat(at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                until = (t0 + timedelta(days=1 if len(at) == 10 else 0, hours=0 if len(at) == 10 else 6)).isoformat()
            hashes += A.commits_between(repo, at, until)[:12]
    texts = {}
    for h in dict.fromkeys(hashes):
        texts.update(A.commit_symbols(repo, h))
    if not texts:
        return 0
    c["anchors"] = A.derive(c["statement"], texts, share=share, max_n=max_n)
    store.save_claim(c)
    return len(c["anchors"])


# ---- git diff of the working tree ----------------------------------------------------------

def working_diff(repo):
    out = subprocess.run(["git", "-C", repo, "diff", "HEAD", "-U0", "-M"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        out = subprocess.run(["git", "-C", repo, "diff", "-U0", "-M"], capture_output=True, text=True)
    return out.stdout


# ---- hooks for Claude Code -------------------------------------------------------------------

def hook(event):
    """Reads the hook JSON on stdin; prints context for the model when something applies."""
    from . import recall as R
    cfg = store.load_config()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    repo = A.toplevel(cwd) or cwd
    if event == "prompt":
        prompt = data.get("prompt") or ""
        if len(prompt) < 12 or prompt.startswith("/"):
            return 0
        claims = store.list_claims(project=repo, status="held")
        res = R.rank(prompt, project=repo, k=cfg["top_k"], anchor_weight=cfg["anchor_weight"], claims=claims)
        floor = cfg["recall_floor"] if cfg["recall_floor"] is not None else R.default_floor(len(claims))
        text = R.render(res, floor=floor)
        if text:
            print(text)
        return 0
    if event == "edit":
        fp = (data.get("tool_input") or {}).get("file_path") or ""
        if not fp:
            return 0
        rel = os.path.relpath(fp, repo) if fp.startswith(repo) else fp
        hits = []
        for c in store.list_claims(project=repo, status="held", include_personal=False):
            if any(a.split("::")[0] == rel for a in c.get("anchors") or []):
                hits.append(dict(claim=c, score=1.0, similarity=0, anchor_overlap=1.0))
        if hits:
            text = R.render(hits[:cfg["top_k"]])
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}))
        return 0
    return 0


CLAUDE_HOOKS = {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "rf hook prompt", "timeout": 20}]}],
    "PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "rf hook edit", "timeout": 10}]}],
}


def setup_claude(write):
    exe = subprocess.run(["which", "rf"], capture_output=True, text=True).stdout.strip() or sys.argv[0]
    cmd_dir = os.path.expanduser("~/.claude/commands")
    src = os.path.join(os.path.dirname(__file__), "commands", "rf-mine.md")
    settings = os.path.expanduser("~/.claude/settings.json")
    hooks = json.loads(json.dumps(CLAUDE_HOOKS).replace('"rf hook', f'"{exe} hook'))
    print("1. MCP server (recall, record, candidates, resolve), user scope:\n")
    print(f"   claude mcp add --scope user rejected-futures -- {exe} serve\n")
    print(f"2. Slash command /rf-mine -> {cmd_dir}/rf-mine.md")
    print(f"3. Hooks in {settings}:\n")
    print("   " + json.dumps({"hooks": hooks}, indent=2).replace("\n", "\n   "))
    if not write:
        print("\nRun again with --write to install 2 and 3; run the claude mcp add line yourself.")
        return
    os.makedirs(cmd_dir, exist_ok=True)
    with open(src) as f, open(os.path.join(cmd_dir, "rf-mine.md"), "w") as g:
        g.write(f.read())
    cur = {}
    if os.path.exists(settings):
        with open(settings) as f:
            cur = json.load(f)
    hk = cur.setdefault("hooks", {})
    for ev, entries in hooks.items():
        lst = hk.setdefault(ev, [])
        if not any("rf hook" in json.dumps(e) or f"{exe} hook" in json.dumps(e) for e in lst):
            lst.extend(entries)
    tmp = settings + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f, indent=2)
    os.replace(tmp, settings)
    print("\ninstalled the command and the hooks")


# ---- main --------------------------------------------------------------------------------

def package_version():
    """The installed distribution's version, falling back to the source __version__."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("rejected-futures")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    from . import __version__
    return __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rf", description=__doc__)
    ap.add_argument("--version", action="version", version=f"rf {package_version()}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="read new transcript turns and flag candidates")
    s.add_argument("--all", action="store_true", help="re-read every session file")
    s.add_argument("--threshold", type=float)
    s.add_argument("--last", type=int, help="only the N most recent session files")
    s = sub.add_parser("watch", help="scan on an interval")
    s.add_argument("--interval", type=int, default=120)
    s = sub.add_parser("candidates", help="flagged turns waiting for a read")
    s.add_argument("--project", default="")
    s.add_argument("--all", action="store_true")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("claims", help="list claims")
    s.add_argument("--project", default="")
    s.add_argument("--all", action="store_true", help="every project")
    s.add_argument("--status", default="held")
    s = sub.add_parser("show", help="print one claim file")
    s.add_argument("id")
    s = sub.add_parser("record", help="record a claim by hand")
    s.add_argument("statement")
    s.add_argument("--kind", default="decision", choices=store.KINDS)
    s.add_argument("--scope", default="repository", choices=store.SCOPES)
    s.add_argument("--project", default="")
    s.add_argument("--quote", default="")
    s = sub.add_parser("retire", help="mark a claim retired or contradicted")
    s.add_argument("id")
    s.add_argument("--status", default="retired", choices=("retired", "contradicted", "held"))
    s = sub.add_parser("skip", help="mark a candidate read with nothing to keep")
    s.add_argument("id")
    s = sub.add_parser("anchor", help="derive code anchors for a claim from its origin commits")
    s.add_argument("id", nargs="?", help="claim id; omit for every claim without anchors")
    s = sub.add_parser("recall", help="claims most relevant to a task")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--diff", action="store_true", help="include the working tree diff")
    s.add_argument("--project", default="")
    s.add_argument("-k", type=int, default=3)
    s = sub.add_parser("check", help="claims relevant to the working tree diff (pre-commit)")
    s.add_argument("--project", default="")
    sub.add_parser("serve", help="run the MCP server over stdio")
    s = sub.add_parser("hook", help="Claude Code hook entry points")
    s.add_argument("event", choices=("prompt", "edit"))
    s = sub.add_parser("setup", help="install into a host agent")
    s.add_argument("host", choices=("claude-code",))
    s.add_argument("--write", action="store_true")
    s = sub.add_parser("duplicates", help="held claim pairs that may be the same decision")
    s.add_argument("--threshold", type=float, default=0.80)
    sub.add_parser("status", help="where things are and how many")
    a = ap.parse_args(argv)

    if a.cmd == "scan":
        scan(all_files=a.all, threshold=a.threshold, limit_files=a.last)
    elif a.cmd == "watch":
        watch(a.interval)
    elif a.cmd == "candidates":
        proj = None if a.all else (A.toplevel(a.project or os.getcwd()) or a.project or os.getcwd())
        cs = store.open_candidates(project=proj, limit=a.limit)
        if not cs:
            print("no open candidates" + ("" if a.all else " for this project (try --all)"))
        for c in cs:
            print(f"=== {c['id']} [{(c.get('ts') or '')[:10]} {c.get('project', '')} p={c.get('p', 0):.2f}]")
            print("--- USER: " + c.get("user", "")[:600].replace("\n", " "))
            print("--- assistant after: " + c.get("next", "")[:300].replace("\n", " ") + "\n")
    elif a.cmd == "claims":
        proj = None if a.all else (A.toplevel(a.project or os.getcwd()) or a.project or os.getcwd())
        cs = store.list_claims(project=proj, status=a.status)
        for c in cs:
            line = (f"[{c['id']}] ({c.get('kind')}, {c.get('scope')}, {c.get('status')}, since {c.get('since')}, "
                    f"{len(c.get('anchors') or [])} anchors) {c['statement']}")
            if c.get("status") == "superseded" and c.get("superseded_by"):
                line += f" superseded by {c['superseded_by']}"
            print(line)
        print(f"{len(cs)} claims")
    elif a.cmd == "show":
        with open(store.claim_path(a.id)) as f:
            print(f.read())
    elif a.cmd == "record":
        proj = A.toplevel(a.project or os.getcwd()) or a.project or os.getcwd()
        scope = a.scope
        p = proj if scope == "repository" else ""
        dup = store.find_duplicate(a.statement, p, scope, a.quote)
        if dup:
            did, how = dup
            if how == "quote":
                if a.quote:
                    store.add_evidence(did, dict(source="cli", at=store.now_iso(), quote=a.quote))
                print(f"already on record as {did}; evidence added")
                return 0
            old = store.load_claim(did)
            if store.same_scope(old, dict(scope=scope, project=p)):
                ev = [dict(source="cli", at=store.now_iso(), quote=a.quote)] if a.quote else []
                c = store.supersede(did, a.statement, kind=a.kind, project=p, evidence=ev)
                print(f"recorded {c['id']}; supersedes {did}")
                return 0
        ev = [dict(source="cli", at=store.now_iso(), quote=a.quote)] if a.quote else []
        c = store.new_claim(a.statement, kind=a.kind, scope=scope, project=p, evidence=ev)
        print("recorded", c["id"])
    elif a.cmd == "retire":
        c = store.load_claim(a.id)
        c["status"] = a.status
        store.save_claim(c)
        print(a.id, "is now", a.status)
    elif a.cmd == "skip":
        store.resolve_candidate(a.id, "skipped")
        print("skipped", a.id)
    elif a.cmd == "anchor":
        ids = [a.id] if a.id else [c["id"] for c in store.list_claims(status="all") if not c.get("anchors") and c.get("project")]
        for cid in ids:
            print(cid, anchor_claim(cid), "anchors")
    elif a.cmd in ("recall", "check"):
        from . import recall as R
        cfg = store.load_config()
        proj = A.toplevel(a.project or os.getcwd()) or a.project or os.getcwd()
        diff = working_diff(proj) if (a.cmd == "check" or a.diff) else ""
        query = getattr(a, "query", "") or ("the change in the working tree" if diff else "")
        res = R.rank(query, diff=diff, project=proj, k=getattr(a, "k", cfg["top_k"]), anchor_weight=cfg["anchor_weight"])
        for r in res:
            print(f"{r['score']:.3f} (sim {r['similarity']:.3f}, anchors {r['anchor_overlap']:.2f}) [{r['claim']['id']}] {r['claim']['statement'][:160]}")
        if not res:
            print("no claims for this project")
    elif a.cmd == "serve":
        from .mcp_server import main as serve
        serve()
    elif a.cmd == "hook":
        return hook(a.event)
    elif a.cmd == "setup":
        setup_claude(a.write)
    elif a.cmd == "duplicates":
        pairs = store.duplicate_pairs(threshold=a.threshold)
        if not pairs:
            print("no duplicate pairs at or above", a.threshold)
        for score, x, y in pairs:
            print(f"{score:.3f} [{x['id']}] {x['statement'][:80]}")
            print(f"      [{y['id']}] {y['statement'][:80]}")
    elif a.cmd == "status":
        st = store.load_state()
        cs = store.load_candidates()
        cl = store.list_claims(status="all")
        print(f"home        {paths.HOME}")
        print(f"last scan   {st.get('last_scan', 'never')}; {len(st.get('files', {}))} session files, {len(st.get('seen', []))} turns seen")
        print(f"candidates  {sum(1 for c in cs if c.get('status') == 'open')} open, {sum(1 for c in cs if c.get('status') == 'claimed')} claimed, {sum(1 for c in cs if c.get('status') == 'skipped')} skipped")
        by = {}
        for c in cl:
            by[c.get("status")] = by.get(c.get("status"), 0) + 1
        print(f"claims      {len(cl)} " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
