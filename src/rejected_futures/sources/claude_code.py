"""Claude Code transcripts: ~/.claude/projects/<encoded cwd>/<session>.jsonl.

Yields one triple per human turn: the assistant text before it, the turn, and the
assistant text after it up to the next human turn (the resolution). Injected turns
(system reminders, command wrappers, task notifications) and sidechains are dropped.
Every string is redacted before it leaves this module."""
import json
import os
import time

from ..redact import redact

ROOT = os.path.expanduser("~/.claude/projects")
INJECTED = ("system-reminder", "command-name", "local-command", "task-notification",
            "create-pr-command", "ide_opened_file", "ide_selection", "ci-monitor-event")
SUMMARY_PREFIX = "This session is being continued from a previous conversation"
SETTLE_SECONDS = 600  # a turn with no resolution yet is final only once the file has been idle this long


def text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b["text"])
                elif b.get("type") == "tool_result":
                    return None
        return "\n".join(parts) if parts else None
    return None


def is_injected(u: str) -> bool:
    head = u[:80]
    return u.startswith("<") and any(t in head for t in INJECTED)


def session_files(root=ROOT):
    if not os.path.isdir(root):
        return
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if f.endswith(".jsonl"):
                yield os.path.join(p, f)


def parse(path):
    """Events of one session: dicts with role a/u, text, ts, uuid, cwd, branch."""
    events = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            m = r.get("message")
            if not isinstance(m, dict):
                continue
            t = r.get("type")
            if t == "assistant":
                a = text_of(m)
                if a:
                    events.append(dict(role="a", text=a, ts=r.get("timestamp"), uuid=r.get("uuid"),
                                       cwd=r.get("cwd"), branch=r.get("gitBranch")))
            elif t == "user" and not r.get("isSidechain") and not r.get("isMeta"):
                u = text_of(m)
                if u is None or is_injected(u):
                    continue
                events.append(dict(role="u", text=u, ts=r.get("timestamp"), uuid=r.get("uuid"),
                                   cwd=r.get("cwd"), branch=r.get("gitBranch")))
    return events


def triples(path, now=None):
    now = now or time.time()
    idle = now - os.path.getmtime(path)
    events = parse(path)
    session = os.path.splitext(os.path.basename(path))[0]
    idx = 0
    for i, e in enumerate(events):
        if e["role"] != "u":
            continue
        idx += 1
        prev_a = ""
        for j in range(i - 1, -1, -1):
            if events[j]["role"] == "a":
                prev_a = events[j]["text"]
                break
        nxt, next_ts, closed = [], None, False
        for j in range(i + 1, len(events)):
            if events[j]["role"] == "u":
                next_ts = events[j]["ts"]
                closed = True
                break
            nxt.append(events[j]["text"])
        if not closed and idle < SETTLE_SECONDS:
            continue  # the resolution is still being written
        text = e["text"]
        yield dict(
            source="claude-code", session=session, turn=e["uuid"], i=idx, ts=e["ts"], next_ts=next_ts,
            project=e.get("cwd") or "", branch=e.get("branch") or "",
            kind="summary" if text.startswith(SUMMARY_PREFIX) else "turn",
            prev=redact(prev_a[-2000:]), user=redact(text[:6000]), next=redact("\n\n".join(nxt)[:6000]),
        )
