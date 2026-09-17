# Worker card

The standing contract for any isolated worker (Claude subagent, OMP, Codex) on a SLink card.
A card brief points here instead of restating it; the brief itself carries only what is
specific to that card.

## Where you work

- Work in the worktree the brief names. Every command and edit runs there; `cd` there first.
- The root checkout and every other worktree are someone else's tree.

## What is yours

- The brief names your **lease**: the exact files you may create or edit. A file outside the
  lease that seems to need a change goes in your report as a finding with file:line, and the
  coordinator routes it.
- Commits and the emulator lane are the coordinator's. Your cut lands as edited files in the
  tree; a live run happens after your report, on the coordinator's lane.
- Reuse before writing: a helper, probe or convention that already lives in a sibling module is
  reached by `dofile`/import the way that module's neighbours reach it.

## How a cut is proven

- Every non-trivial change carries a **falsifier**: a test that is red before the change and
  green after. The report names each red test and its failure message.
- Facts about the game come from pret (`E:/Google Drive/SLink/.cache/pret/`) with file:line,
  from the generated profile, or from a committed receipt. A fact you could not pin is marked
  `†UNVERIFIED` in the code and listed in the report.
- Checks that must be green before the report: the pytest files the brief names,
  `ruff check` on edited Python, `python tools/lua_syntax_check.py` on edited Lua.

## The report

Your final message is the only thing the coordinator reads. It carries, in this order:

1. what you built (interface, phases or functions, one line each);
2. findings outside your lease, with file:line;
3. the verbatim check output;
4. `git status --short` restricted to your lease.

Drivers log phase transitions and named markers; the per-frame log stays silent.
