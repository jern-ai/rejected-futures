"""Anchoring a claim to code. The origin commits are the ones made in the window between
the human turn that formed the claim and the next human turn. Each hunk of those commits
is attributed to its enclosing definition; only the definitions whose changed text resembles
the claim are kept (the derived scope line). Diffs are read the same way at recall time."""
import math
import os
import re
import subprocess
from collections import Counter

import numpy as np

DEFS = {
    ".fs": [re.compile(r"^(?:let|and|type|module|exception)\s+(?:rec\s+|private\s+|internal\s+|inline\s+)*(\w[\w.]*)"),
            re.compile(r"^\s{2,8}(?:let|and|member|static member|abstract|override|default|type|module)\s+"
                       r"(?:rec\s+|private\s+|internal\s+|inline\s+|this\.|_\.|x\.)*(\w[\w.]*)")],
    ".ts": [re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class|interface|type|enum|namespace)\s+(\w+)"),
            re.compile(r"^\s{2,8}(?:export\s+)?(?:async\s+)?(?:function\*?|const|let|static|private|public|get|set)\s+(\w+)"
                       r"|^\s{2,8}(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]|, ]+)?\s*\{$")],
    ".py": [re.compile(r"^(?:class|def|async def)\s+(\w+)"), re.compile(r"^\s{2,8}(?:def|async def)\s+(\w+)")],
    ".sh": [re.compile(r"^(?:function\s+)?(\w+)\s*\(\)\s*\{?")],
    ".go": [re.compile(r"^(?:func|type)\s+(?:\([^)]*\)\s*)?(\w+)")],
    ".rs": [re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl|mod|type|const|static)\s+(\w+)"),
            re.compile(r"^\s{2,8}(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)")],
    ".cs": [re.compile(r"^\s*(?:public|private|internal|protected|static|sealed|abstract|partial|\s)*\s*(?:class|interface|record|struct|enum)\s+(\w+)"),
            re.compile(r"^\s{4,12}(?:public|private|internal|protected|static|virtual|override|async|\s)+[\w<>\[\],? ]+\s+(\w+)\s*\(")],
    ".java": [re.compile(r"^\s*(?:public|private|protected|static|final|abstract|\s)*\s*(?:class|interface|record|enum)\s+(\w+)"),
              re.compile(r"^\s{4,12}(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\],? ]+\s+(\w+)\s*\(")],
    ".rb": [re.compile(r"^(?:class|module|def)\s+([\w.:]+)"), re.compile(r"^\s{2,8}def\s+([\w.?!]+)")],
}
for a, b in ((".tsx", ".ts"), (".js", ".ts"), (".mjs", ".ts"), (".jsx", ".ts"), (".fsx", ".fs"),
             (".bash", ".sh"), (".kt", ".java"), (".scala", ".java")):
    DEFS[a] = DEFS[b]

NOISE = ("docs/", "README", ".css", ".md", "roadmap", ".lock", "package-lock", ".snap", ".min.")


def is_code(path):
    return not any(n in path for n in NOISE)


def rules_for(path):
    return DEFS.get(os.path.splitext(path)[1])


def enclosing(lines, lineno, rules, is_bash=False):
    top = nested = None
    for i in range(min(lineno, len(lines)) - 1, -1, -1):
        L = lines[i]
        if is_bash and L.startswith("}"):
            return None, None
        if nested is None and len(rules) > 1:
            m = rules[1].match(L)
            if m:
                nested = next((g for g in m.groups() if g), None)
        m0 = rules[0].match(L)
        if m0:
            top = m0.group(1)
            break
    return top, nested


def key(path, top=None, nested=None):
    k = path
    if top:
        k += "::" + top
        if nested:
            k += "::" + nested
    return k


def git(repo, *args, text=True):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=text).stdout


def toplevel(path):
    out = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


def symbols_of_diff(diff_text, read_file):
    """{symbol key: changed text} for a unified diff. read_file(path) returns the post-image
    lines or None; files without a recognised language anchor as a whole."""
    syms, cur, rules, lines, k = {}, None, None, None, None
    for L in diff_text.splitlines():
        if L.startswith("+++ "):
            p = L[4:].strip()
            cur = p[2:] if p.startswith("b/") else (None if p == "/dev/null" else p)
            rules = rules_for(cur) if cur else None
            lines = read_file(cur) if (cur and rules) else None
            k = None
            if cur and not rules:
                k = key(cur)
                syms.setdefault(k, "")
        elif L.startswith("@@") and cur and rules and lines is not None:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", L)
            if not m:
                continue
            start = int(m.group(1))
            top, nested = enclosing(lines, max(start, 1), rules, cur.endswith(".sh"))
            k = key(cur, top, nested)
            syms.setdefault(k, "")
        elif L.startswith("@@") and cur and rules and lines is None:
            k = key(cur)
            syms.setdefault(k, "")
        elif k is not None and (L.startswith("+") or L.startswith("-")) and not L.startswith(("+++", "---")):
            if len(syms[k]) < 1500:
                syms[k] += L[1:] + "\n"
    return syms


def commit_symbols(repo, h):
    diff = git(repo, "show", "--format=", "-U0", "-M", h)

    def read_file(p):
        out = subprocess.run(["git", "-C", repo, "show", f"{h}:{p}"], capture_output=True, text=True)
        return out.stdout.splitlines() if out.returncode == 0 else None

    return symbols_of_diff(diff, read_file)


def working_tree_symbols(repo, diff_text):
    def read_file(p):
        fp = os.path.join(repo, p)
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                return f.read().splitlines()
        except OSError:
            return None

    return symbols_of_diff(diff_text, read_file)


def commits_between(repo, since_iso, until_iso, author=None):
    args = ["log", "--format=%H", f"--since={since_iso}"]
    if until_iso:
        args.append(f"--until={until_iso}")
    if author:
        args.append(f"--author={author}")
    args.append("--all")
    return [h for h in git(repo, *args).split() if h]


def derive(claim_text, symbol_texts, share=0.1, max_n=8, min_n=1):
    """Keep the origin symbols whose changed text is closest to the claim."""
    from .classify import embed, QUERY_PREFIX
    items = [(k, t) for k, t in symbol_texts.items() if is_code(k.split("::")[0])]
    if not items:
        return []
    q = embed([QUERY_PREFIX + claim_text], normalize=True)
    E = embed([f"{k}\n{t}" for k, t in items], normalize=True)
    S = (q @ E.T)[0]
    keep = max(min_n, min(max_n, int(round(share * len(items)))))
    order = np.argsort(-S)[:keep]
    return [items[i][0] for i in order]


def anchor_overlap(anchors, touched):
    """Share of a claim's anchors a diff touches; a file-level match counts half."""
    if not anchors or not touched:
        return 0.0
    touched_files = {t.split("::")[0] for t in touched}
    hit = 0.0
    for a in anchors:
        if a in touched:
            hit += 1.0
        elif a.split("::")[0] in touched_files:
            hit += 0.5
    return hit / len(anchors)
