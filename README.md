# Rejected Futures

A memory of the decisions your coding agent keeps forgetting, built from the agent
transcripts and git history already on your disk, and handed to whatever agent you use at
the moment it is about to repeat one. Nothing leaves the laptop. No API key. No repository
to connect.

Working name. Status: personal trial.

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
| `rf serve` | The MCP server over stdio: `recall`, `record`, `candidates`, `resolve`, `claims`, `retire`. |
| `rf --version` | Print the installed version. |
| `rf hook prompt|edit` | Claude Code hook entry points (installed by `rf setup claude-code --write`). |

## Configuration

`~/.rejected-futures/config.json`, all optional:

    {"threshold": 0.35, "recall_floor": 0.65, "anchor_weight": 0.3, "top_k": 3,
     "skip_projects": ["/Users/me/private"]}

`threshold` is the classifier score a turn needs to become a candidate; `recall_floor` is the
score a claim needs before the prompt hook mentions it.

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
