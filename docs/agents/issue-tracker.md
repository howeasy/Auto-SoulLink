# Issue tracker

**Issues live as local markdown in this repo, not in GitHub Issues.** Skills that create, read or
close issues (`to-tickets`, `triage`, `to-spec`, `implement`, `wayfinder`) operate on files here.

## Where

```
docs/<effort>/issues/NN-<slug>.md       one file per ticket, numbered
docs/<effort>/wayfinder/map.md          decision map, when an effort used /wayfinder
docs/<effort>/PLAN.md                   the spec the tickets were split from
```

`<effort>` is the workstream name, not a generation: `docs/gen2/`, `docs/gen3/`, `docs/purergb/`.
The worked example to copy is **`docs/gen2/issues/`** — 35 numbered tickets, each carrying a dated
status line with evidence, plus `docs/gen2/wayfinder/`.

## Rules

- **Tickets commit with the code.** A ticket and the change that closes it belong in the same
  history, so `git log -- docs/<effort>/issues/` is the record of what was decided and when.
- **No GitHub Issues, and no PR request surface.** External PRs are not a triage input here; this
  is a single-owner repo with agent lanes, and work arrives from the owner or from a lane's own
  sweep.
- **A ticket states its evidence.** "Done" means a commit sha, a receipt path, or a test name —
  not an assertion. The Gen 2 set does this well: each status line cites what proves it.
- **Status goes in the ticket, dated.** Do not rely on a separate index to say what is open; an
  index drifts from 35 tickets faster than the tickets drift from reality.
- **Open questions belong in the effort's `OPEN_QUESTIONS.md`**, closed with a citation when
  answered, rather than being deleted.

## Numbering and closure

Numbers are allocated once and never reused, so a citation to `12-…` stays meaningful after the
ticket closes. A ticket that turns out to be wrong is closed with a reason, not deleted.
