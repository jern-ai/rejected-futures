---
description: Distil flagged past turns into claims for rejected-futures (decision memory)
---
Read the open candidates from the rejected-futures MCP server and turn the ones that carry a
storable claim into claims. Work through them one by one.

1. Call `candidates` (limit 10, current repository). If the user passed `all`, pass project="*".
2. For each candidate, read the user's turn together with the assistant's resolution. It carries
   a claim when it states one of: a correction of the agent with a reason, a decision with an
   alternative that lost, an invariant ("never", "always", "must"), a portable preference of the
   developer, a rejected approach, or a fact the agent lacked. Go-aheads, questions, bug reports
   with logs, pasted external text, and task notifications carry nothing.
3. When it carries a claim, call `resolve` with action "claim", a one- or two-sentence statement
   in the developer's own terms (what holds and why, no hedging), kind (decision | invariant |
   preference | rejected | fact) and scope ("personal" when it would hold in any repository,
   otherwise "repository"). Otherwise call `resolve` with action "skip".
4. Repeat from step 1 until `candidates` returns none, or the user asked for a number.
5. Finish with a short list: each claim recorded with its id, and how many were skipped.
Do not edit any file in the repository. Do not invent claims that the turns do not state.
