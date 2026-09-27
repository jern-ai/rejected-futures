# Rejected Futures

A memory of the decisions your coding agent keeps forgetting, built from the agent
transcripts and git history already on your disk, and handed to whatever agent you use at
the moment it is about to repeat one. rf itself sends nothing anywhere. No API key. No
repository to connect.

Status: early release (0.1.0), Claude Code transcripts only. Built by the makers of [Jern](https://jern.ai).

## What it reads, keeps, and sends

rf reads your agent transcripts, so this comes first.

**Reads.** Every Claude Code transcript under `~/.claude/projects`, for every project, but
only the text you typed and the text the assistant wrote back. Tool calls, tool results (the
files, command output and web pages the agent read), subagent turns and injected system text
are dropped as the file is parsed and never reach the classifier. To anchor claims to code it
runs `git log`, `git show` and `git diff` in your local repositories; it never fetches or
pushes.

**Redacts.** Before anything is stored, every string passes through pattern redaction:
assignments to names containing KEY, TOKEN, SECRET or PASSWORD; token formats with known
prefixes (OpenAI and Anthropic `sk-`, GitHub, GitLab, Slack, AWS, Google, npm, PyPI, Fly,
Jern); `Bearer` and `Authorization` values; and PEM private keys. It is pattern-based: a
password written in plain prose, or a customer's data pasted into a chat, is not caught. Keep
a project out entirely with `skip_projects` (see Configuration).

**Keeps,** all in `~/.rejected-futures/`, as plain files you can read and delete:

| File | What is in it |
|---|---|
| `candidates.jsonl` | Only the turns the classifier flags (a fifth to a third): your turn cut to 2,000 characters, the assistant's reply before it to 600 and after it to 1,500, redacted, with the session id, timestamp, project path and branch. |
| `claims/*.md` | The claims you or your agent recorded, each with a short evidence quote and its date. |
| `state.json` | Which transcript files and turn ids have been read; no text. |
| `index.json` | Embeddings of claim statements, for recall. |
| `models/` | The embedding model (64 MB). |
| `rf.log` | Scan counts; no text. |

A turn that is not flagged leaves nothing behind but its id.

**Sends.** rf makes one network request of its own: on first use it downloads the embedding
model (`qdrant/bge-small-en-v1.5-onnx-q`) from Hugging Face. Your text is not part of that
request, and after it rf runs offline (`HF_HUB_OFFLINE=1` enforces it). The classifier and
recall run on your CPU.

What rf hands your agent does travel, though, to whichever model provider your agent already
uses, as part of your prompts:

- `/rf-mine` gives your agent the flagged candidates to turn into claims, so those redacted
  turns go to your agent's provider a second time; the provider saw them the first time,
  when you wrote them.
- The prompt and edit hooks and the MCP `recall` tool add up to three claims (`top_k`) to the agent's
  context each time.

Nothing goes to Jern or to anyone else.

**Writes outside its folder** only when you ask: `rf setup claude-code --write` copies the
`/rf-mine` command to `~/.claude/commands/` and adds two hooks to `~/.claude/settings.json`.

**Removing it:** delete `~/.rejected-futures/` and `~/.claude/commands/rf-mine.md`, remove
the two hook entries that run `rf hook` from `~/.claude/settings.json`, and run
`claude mcp remove rejected-futures`.

## What it does

1. **Watches** your Claude Code transcripts (`~/.claude/projects`). Every human turn is paired
   with the assistant's resolution; secrets are redacted before anything is stored.
2. **Flags** the pairs that carry a claim with a local classifier (a 33M-parameter embedding
   model on the CPU plus a logistic regression trained on 314 hand-labelled turns: precision
   about 0.5, recall about 0.9). Flagged pairs wait as *candidates*.
3. **Distils** candidates into claims using the host agent's own model: `/rf-mine` in Claude
   Code reads the queue and records claims through the MCP server. A claim is a decision, an
   invariant, a preference, a rejected approach, or a fact the agent lacked, in your terms,
   with the evidence turn and its date.
4. **Anchors** each repository claim to code: the definitions changed by the commits made in
   the window after the turn that formed it, filtered to the ones whose changed text resembles
   the claim.
5. **Recalls** the three most relevant claims for a task or a diff, before the first edit
   (a `UserPromptSubmit` hook), before editing an anchored file (a `PreToolUse` hook), before a
   commit (`rf check`), or whenever the agent calls `recall`. Claims are context, never a
   gate: the agent judges whether each applies and says so when it departs from one.

Claims are plain Markdown files with YAML front matter in `~/.rejected-futures/claims/`,
yours to edit.

## Install

rf is not on PyPI yet; install it from GitHub with one command. It needs Python 3.10 or newer.

    pipx install git+https://github.com/jern-ai/rejected-futures

or, with uv:

    uv tool install git+https://github.com/jern-ai/rejected-futures

Then run the first pass and wire up your agent:

    rf scan                 # first pass over every transcript (a few minutes)
    rf status
    rf setup claude-code    # prints the three integration steps; --write installs two of them

### From a checkout

To work on rf itself, use a virtual environment and an editable install:

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -e '.[test]'
    python -m pytest

## Commands

| Command | What it does |
|---|---|
| `rf scan` | Read new turns, flag candidates. `--all` re-reads every file. |
| `rf watch` | `scan` on an interval (default 120 s). |
| `rf candidates` | Flagged turns waiting for a read, for this repository (`--all` for every one). |
| `rf claims` | Claims for this repository plus personal ones. `--all`, `--status all`. |
| `rf record "..."` | Record a claim by hand (`--kind`, `--scope personal`). |
| `rf recall "task"` | The claims most relevant to a task; `--diff` adds the working tree diff. |
| `rf check` | Claims relevant to the working tree diff, for a pre-commit hook. |
| `rf anchor [id]` | Derive code anchors from origin commits (every unanchored claim when no id). |
| `rf retire id` | Mark a claim retired or `--status contradicted`. |
| `rf duplicates` | Held claim pairs that may be the same decision (cosine ≥ 0.80), so a person can retire one; it merges nothing. |
| `rf serve` | The MCP server over stdio: `recall`, `record`, `candidates`, `resolve`, `claims`, `retire`. |
| `rf --version` | Print the installed version. |
| `rf hook prompt|edit` | Claude Code hook entry points (installed by `rf setup claude-code --write`). |

## Configuration

`~/.rejected-futures/config.json`, all optional:

    {"threshold": 0.35, "recall_floor": 0.65, "anchor_weight": 0.3, "top_k": 3,
     "skip_projects": ["/Users/me/private"]}

`threshold` is the classifier score a turn needs to become a candidate; `recall_floor` is the
score a claim needs before the prompt hook mentions it. Left unset, the floor follows the size
of the store, `0.61 + 0.015 × ln(claims)`: about 0.61 for one claim and 0.68 for a hundred,
because the best score among unrelated claims rises with their number by chance alone. Set it
to fix the floor instead.

## A claim, as stored

    ---
    id: prices-are-stored-as-integer-cents-never-as
    kind: invariant
    scope: repository
    status: held
    since: '2026-09-07'
    project: /Users/me/work/shop
    anchors:
    - src/shop/pricing.py::apply_discount
    evidence:
    - {source: claude-code, session: 3f9a1c2e, at: '2026-09-07', quote: "No floats for money..."}
    ---
    Prices are stored as integer cents, never as floats; rounding happens once, at display...

## Retraining the classifier

`tools/train.py` needs scikit-learn and the labelled turns (kept privately under
`~/.rejected-futures/training/`). It writes `src/rejected_futures/model.json`.

## Evidence

Four experiments on 2026-09-14 over 1,447 human turns in 20 repositories: 73 mined claims,
all confirmed held by the developer; seven had been restated after the agent violated them
a second time. On 244 commits of one repository the right claim was in the top three for
every held-out post-claim commit and first for 11 of 13. A hard gate would still interrupt
one commit in three for nothing, which is why this never blocks.
