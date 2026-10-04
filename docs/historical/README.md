# Historical records

Documents in this folder describe work that is **finished, superseded or abandoned**. They are
kept because they hold reasoning the shipped code does not explain — why a design was chosen,
what a measurement showed, what an effort was trying to do. They are **not** descriptions of
current infrastructure and must not be read as instructions.

Each file opens with a dated header saying what it records and where the current facts live.
The bodies are preserved as written, including their stale branch names, worktree paths and
counts: editing a record to look current is how you lose the record.

| File | Records | Current facts live in |
|---|---|---|
| `gen1_resume.md` | The Gen 1 master-release effort, its worker assignments and the native-sound design. The named worktree and branch are gone; Gen 1 is merged to master. | `docs/gen1_requirements.md`, `docs/gen1_gen2_runtime_checks.md` |
| `gen1_rebase_plan.md` | The plan for rebasing Gen 1 onto master. It happened. | git history |
| `gen1_catch_loop_finding.md` | A catch-loop investigation. Its probe script was deleted, so the commands are illustrative only. | `lua/gen1/`, `tests/live/test_gen1_new_gates.py` |
| `release_notes.md` | A verification snapshot from one point in the Gen 1 effort. **Nothing has been released** — master is local and unpushed. | `tools/verify_gen1_release.py --list`, `docs/gen1_gen2_runtime_checks.md` |
| `ui_migration_plan.md` | The two-apps-to-one-board migration. Done and shipped. | `server/templates/`, `server/static/`, `docs/REFERENCE.md` |
| `ui_mockup_brief.md` | The design brief for the Track A / Track B mockup bake-off. Track A (Jinja + Alpine + htmx) won and shipped. | the shipped UI |
| `reference_removed_2026-10-03.md` | Sections cut from `docs/REFERENCE.md` in the 2026-10-03 docs sweep: per-generation proof notes, Gen 1 HUD/sound cue notes, and the old Gen 3 client's ability display, Radical Red support, ROM profiles and sync timing. | `docs/REFERENCE.md`, `lua/gen3/`, `data/games/gen3_*` |

## What belongs here

A document belongs here once it describes something that no longer exists or an effort that has
concluded, AND it still carries reasoning worth keeping. If it carries no such reasoning, delete
it instead — a record nobody needs is just another thing to keep accurate.

Dated evidence trails that already scope themselves by commit stay where they are:
`docs/purergb/research/`, `docs/gen2/research/`, `docs/gen2/reviews/`, `docs/gen3/research/`.
They are cited by path from commit messages and other documents, and moving them would break
those citations for no gain.
