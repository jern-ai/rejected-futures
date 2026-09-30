# rf graduate: moving claims into the repository

Status: draft, 2026-09-29. `rf graduate --suggest` and the `graduation_candidates` MCP tool
are implemented (read-only); everything else here is not.

## Why

A claim is context, never a gate. The agent can read "prices are integer cents" and still write
a float. The README's own evidence says a hard gate built on recall would interrupt one commit
in three for nothing, so recall must stay advisory. But a test that encodes the invariant does
not misfire that way, and it works for every agent, every tool and every person, with or without
rf installed.

rf is the right tool for discovering those constraints after the fact. It should not be the
place they live forever. `rf graduate` moves a held claim into the repository, as a test, a
policy entry, or a line in the docs agents already read. It then records where the claim went
and stops recalling it.

Success metric: the share of held repository claims that end up graduated, and how long that
takes.

## Principles

1. **rf proposes, a person approves.** rf never writes into a repository on its own. The same
   split as `/rf-mine` applies: rf does the deterministic parts (choosing claims, recording
   links, checking them), and the host agent's model drafts the test or text.
2. **Strongest target that fits.** Use a test where the rule can be checked, a policy entry
   where it is about what the agent may run or touch, and a doc line only when neither works.
3. **No new configuration files.** Write into files the repository already has: the test tree,
   the existing policy baseline, CLAUDE.md or AGENTS.md. Never add a new root file only for rf.
   (This follows the held claim `do-not-litter-a-repository-with-configuration`.)
4. **Provenance is kept.** A graduated claim stays on disk with its evidence and a pointer to
   what now enforces it. The test or doc line cites the claim id, so either can be traced to
   the other.
5. **Enforcement can rot; rf notices.** If the test or line disappears, the claim goes back
   to `held` and is recalled again.

## Targets

| Target | Suits | Written to | What rf records |
|---|---|---|---|
| `test` | `invariant`, checkable `rejected` ("never call X from Y") | A new or existing test file in the repo's own framework (pytest, xUnit, jest, ...) | path, test name, commit |
| `policy` | Rules about commands, paths or hosts ("never touch migrations/", "no network in tests") | The repository's existing policy file (for example the Jern baseline), if it has one | path, key |
| `doc` | `decision`, `fact`, `rejected` that cannot be checked mechanically | Existing CLAUDE.md or AGENTS.md; an ADR only if the repo already keeps ADRs | path, heading or line |

Personal-scope claims (preferences that apply in every repository) graduate only to `doc`,
written to the user-level `~/.claude/CLAUDE.md`, never into a repository.

Which language and framework a test uses comes from the repository, not from rf. The drafting
is done by the host agent, so a .NET repository gets an xUnit test without rf knowing anything
about .NET.

## Data model

`store.STATUSES` gains `graduated`. A graduated claim adds:

```yaml
status: graduated
graduated:
  - to: test
    path: tests/test_pricing.py
    symbol: test_prices_are_integer_cents
    commit: 3f9a1c2
    at: '2026-10-02'
    fails_on_violation: true   # the agent showed the test fails on a violating edit
```

- `list_claims(status="held")` already leaves out every other status, so recall, the hooks and
  duplicate detection need no change to stop showing graduated claims.
- `find_duplicate` should also compare against `graduated` claims. That way, re-mining the same
  decision adds evidence to the graduated claim instead of creating a new held one that brings
  the rule back into recall.
- If a graduated claim is superseded, its enforcement is out of date. `supersede` keeps the
  `graduated` entries on the old claim, and `rf graduations --check` reports it for review.

## Surface

CLI:

| Command | What it does |
|---|---|
| `rf graduate --suggest` | Held repository claims ranked for graduation, with a proposed target for each |
| `rf graduate ID --to test\|policy\|doc --path P [--symbol S]` | Record that the claim now lives at P; checks that P (and S) exist at HEAD, then marks it graduated |
| `rf graduations [--check]` | List graduated claims; `--check` confirms each target still exists, returns lapsed ones to `held`, and flags superseded ones |
| `rf retire ID --status held` | Undo a graduation by hand (already supported) |

MCP: `graduation_candidates(project, limit)` and `graduate(claim_id, to, path, symbol,
fails_on_violation)`, mirroring `candidates` and `resolve`.

A slash command `commands/rf-graduate.md`, installed by `rf setup claude-code --write` next to
`rf-mine.md`, drives the loop:

1. Call `graduation_candidates` and pick one claim with the developer.
2. Draft the test, policy entry or doc line in the repository's own conventions, citing the
   claim id in a comment.
3. For a test: make a throwaway edit that violates the claim, show that the test fails, then
   revert it. Report `fails_on_violation` truthfully. A test that passes on the violation does
   not graduate the claim.
4. The developer reviews the diff and commits.
5. Call `graduate` with the path and symbol; rf checks they exist at HEAD.

## Ranking for --suggest

Deterministic, no model at all. Sorted by, in order:

1. Scope: every repository-scope claim before every personal-scope claim, so the repository's
   own claims cannot be pushed off the list by personal ones.
2. Restated: more than one evidence entry not marked `superseded` means the agent broke the rule
   again after it was recorded. That is the strongest sign recall alone is not enough.
3. Kind: `invariant`, then `rejected`, `decision`, `fact`, `preference`.
4. Anchored before unanchored: claims with code anchors have a clear place for a test to point at.
5. Older `since` first, then id.

One list and one `--limit`; the limit applies after the whole ranking, so the top of the list is
the top repository claims, then the top personal ones.

Proposed targets: repository `invariant` goes to `test`; repository `rejected` goes to `test`
when anchored, otherwise to doc; other repository kinds go to doc, naming an existing CLAUDE.md
or AGENTS.md, or saying neither exists. Personal claims go to `~/.claude/CLAUDE.md` when that
file exists, and otherwise to `doc (no ~/.claude/CLAUDE.md)`; rf never proposes a file that does
not exist.

Recall hit counts would help too ("recalled 40 times"), but rf does not track them today.
Adding them means storing claim ids per recall, and ids are slugs of the claim text, so it
needs a privacy note in the README. Leave it out of the first version.

## What it does not do

- Write, commit or open a pull request by itself. (A later step could send the graduation as
  a task to a cloud agent session, with the claim and its evidence as the task text.)
- Enforce anything. The test or policy does the enforcing, run by whatever CI and agent
  policy the repository already has.
- Check that a doc line is actually followed. `doc` is the weakest target, and the listing says
  so.

## Tests

- `graduate` refuses a path or symbol that does not exist at HEAD, and refuses personal claims
  with a repository target.
- A graduated claim is absent from `rank`, both hooks and `duplicate_pairs`, and present in
  `rf claims --status graduated`.
- `find_duplicate` matches a new claim against a graduated one.
- `--check` returns a claim to `held` when its test file or symbol is deleted, and flags it
  when the claim is superseded.
- `--suggest` ordering on a fixture store.

## Open questions

- **Policy target.** The current Jern baseline has `edits_within`, `shell_allow` and
  `protected_paths`: allow lists and protected paths, but no deny rules for content. Which
  claims can it actually express? Possibly only "never edit X". Is that worth a target in
  version one, or should it wait?
- **Checking a symbol at HEAD** is easy for Python and TypeScript with the existing `DEFS`
  patterns in `anchors.py`. For languages without patterns, `--check` would fall back to
  checking the file exists and the claim id appears in it.
- **Priority.** This is a new feature. It answers the strongest outside criticism directly, but
  if the question is whether rf converts at all, `--suggest` alone (no writing, just the
  ranked list with proposed targets) may be enough to test demand.
