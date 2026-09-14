# C1-RB whiteout collateral force-faint — IMPLEMENTED

`settle_whiteout` (`server/gen1_whiteout.py`) previously discarded the entire engine-signal batch
with `JournalError("whiteout found a linked party member its faint settlement left alive")`
whenever `_handle_whiteout` (`server/state.py:2013`) legitimately force-faulted a *second*
still-ALIVE linked pair during a full-party wipe (CLAUDE.md "Whiteout": every partner of a
remaining linked party mon gets force-fainted). That guard was written to catch a genuine
duplicate — the triggering mon's own link being re-killed — but it fired on any force_faint the
whiteout produced, collateral or not, and a raised `JournalError` there discards the whole staged
transaction (`server/gen1_engine_signal_runtime.py:34`: "Discard both detached values if
validation fails"), so B received *nothing*, not even the already-settled triggering death. This
lands the fix: collateral deaths are now recorded as real, ack-able obligations instead of
silently dropped, while the genuine-duplicate case still refuses.

Owner: this worker (C1 implementation, dispatched by the coordinator after C1-CLAIM). Canonical
checkout `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`.
Base named by the coordinator: `6ae72a9`. HEAD at report time: `c868282c4f27b927c1276fff38fef588337464e4`
(this worktree is actively shared; other agents' concurrent commits — FT-2/FT-2b/FT-2c/FT-3/N3/UI-2 —
landed during this work and are excluded from this report's diff). Writes touched exactly the four
files the card named: `server/gen1_whiteout.py`, `server/gen1_faint_runtime.py`,
`tests/unit/test_gen1_whiteout.py`, and this report. No git commit/stash/checkout was run.

This corroborates and closes the gap the prior successor reports modeled: [C1-repro-successor.md](C1-repro-successor.md)
reproduced the exact `JournalError` through the real public runtime with two source-qualified
linked pairs, and flagged the hard part — "A collateral Lapras record cannot truthfully reuse the
Eevee's decoded key" (persisted-death verification expects a decoded `faint` signal whose key
matches). [C1-reachability-successor.md](C1-reachability-successor.md) found a **source-supported
natural route** to the collateral-ALIVE condition (a pre-activation faint observed while rules are
inactive, so that link is never individually settled before a later whiteout). This report is the
first to actually change behavior rather than model it.

## Diff

```
git diff --stat -- server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py
 server/gen1_faint_runtime.py     | 148 ++++++++++++++++++++++++++-------------
 server/gen1_whiteout.py          |  54 +++++++++++---
 tests/unit/test_gen1_whiteout.py | 146 +++++++++++++++++++++++++++++++++++++-
 3 files changed, 287 insertions(+), 61 deletions(-)
```

SHA256 of `git diff -- server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py`
(computed via `hashlib.sha256`, not the coreutils tool):

```
3d16014954fcde2cc3556bcd4d32c24772e6c7a7763d9257735497544b342b5e
```

## Behaviour change

1. **`identifier(player, operation, index, discriminant=None)`** (`server/gen1_faint_runtime.py`)
   gained an optional `discriminant`. Omitted, it hashes exactly as before (every existing call
   site is unaffected); passed, it disambiguates a collateral death from its trigger, which shares
   the same `(player, operation, index)`.
2. **`_link_identity(stage, initials, link)`** and **`record_death_obligation(stage, document,
   component, commands, *, player, partner, entry, index, key, link, command, at,
   collateral_of=None)`** are new, extracted from the inline block `settle()` used to build a
   death record (death_id, `component["deaths"][death_id]`, deferred-storage handling, the
   outbound command, and the recovery blocker). `settle()`'s own call site is behaviourally
   unchanged — same death_id, same record shape, same 37/37 `test_gen1_faint_runtime.py` tests
   green.
3. **`settle_whiteout(..., *, trigger_death_id, trigger_key)`** (`server/gen1_whiteout.py`) now
   takes the triggering death's id/key. For each `force_faint`/`force_explode` the shared engine's
   `_handle_whiteout` queues: resolve its link via `stage.rules.find_link(partner, command["key"])`;
   if that link's own-player key equals `trigger_key`, it is a genuine duplicate and still raises
   `JournalError("whiteout found a linked party member its faint settlement left alive")`;
   otherwise it is collateral — no faint signal ever fired for it — and is recorded via
   `record_death_obligation(..., collateral_of=trigger_death_id)`, plus a `log.warning`. B now
   receives that force_faint command with its own `death_id`, its own recovery blocker, and
   `phase: "pending_faint"` — ack-able through the existing `acknowledge()` path unchanged (it only
   looks up `component["deaths"][body["death_id"]]`, agnostic to `collateral_of`).
4. **`verify_state`** (`server/gen1_faint_runtime.py`) accepts the new optional `collateral_of`
   field in the death-record shape check, and branches: a collateral record is anchored to its
   trigger (same `engine_record`/`index`, trigger itself not collateral) and its decoded signal
   must be `battle_faint`/`poison_faint` (the whiteout cause), not `faint`; the identifier check
   uses the same `discriminant`. Every other invariant (phase, deferred storage, enforcement,
   `link.status`, paired memorial completion, the `stage.barrier` blocker-set cross-check) is
   unchanged and applies identically to collateral and primary records, since both live in the
   same `component["deaths"]` dict.

## Tests

`tests/unit/test_gen1_whiteout.py` gained two tests exercising `record_death_obligation` and
`settle_whiteout` directly (a real `StagedGen1State`/rules engine via a paired runtime for L1's
identity/initials, plus minimal `_FakeBlockers`/`_FakeIdentities` doubles standing in for
`stage.barrier`/`stage.identities` — `_link_identity`'s own correctness is exercised through the
real `IdentityRegistry` elsewhere, e.g. `gen1_starter_settlement.py`):

- `test_two_alive_links_whiteout_produces_collateral_force_faint`: two ALIVE links, L1's faint
  settles first (mirrors `settle()`'s real ordering), L2 stays ALIVE and reads 0 HP in the same
  party capture. Asserts: no `JournalError`; `l2.status == DEAD`; `component["deaths"]` gains a
  second record with `collateral_of == trigger_death_id`, correct `key`/`peer_key`/`peer`; B's
  feedback contains exactly one `force_faint` for L2's peer key carrying the new `death_id`; both
  death_ids hold a `stage.barrier` blocker.
- `test_whiteout_still_refuses_a_genuine_duplicate_of_the_triggering_mon`: the trigger's own link
  left ALIVE (no prior faint settlement) still raises the original `JournalError` message.

Exit-criteria run, this worktree, `PYTHONDONTWRITEBYTECODE=1` (writing `.pyc` into the shared
worktree is blocked by the sandbox as a shared-resource modification):

```
python -m pytest tests/unit/test_gen1_whiteout.py tests/unit/test_gen1_faint_runtime.py tests/unit/test_gen1_memorial_runtime.py -q -o addopts= -p no:cacheprovider
........................................................................ [ 80%]
..................                                                       [100%]
90 passed in 138.43s (0:02:18)
```

(18 whiteout + 37 faint_runtime + 35 memorial_runtime = 90; all pre-existing tests in those three
files pass unchanged, including the full-runtime persistence/restore round trips in
`test_whiteout_settles_once_behind_its_faint_and_survives_restore` and the tampered-record refusal
matrix in `test_tampered_whiteout_records_are_refused_by_the_state_aggregate`.)

`ruff check server/gen1_whiteout.py server/gen1_faint_runtime.py tests/unit/test_gen1_whiteout.py`
→ `All checks passed!` (no findings, new or pre-existing, on the three touched files).

## What remains MODEL-only

- **No live/duo proof of this exact scenario.** Every check above runs the real shared rules
  engine (`state.py`) and, for the collateral test, a real enrolled `StagedGen1State` with real
  `initials`, but `stage.identities` is a minimal double, not the production `IdentityRegistry`,
  and the collateral link (`key_a2`/`key_b2`) is injected directly onto `rules.links` rather than
  reached through a real second wild capture. `_link_identity`'s interaction with the *real*
  registry for a genuine second capture is covered by other suites (`gen1_starter_settlement`,
  `gen1_acquisition_runtime`), not exercised end-to-end here.
- **No full-runtime persistence/restore round trip for a collateral death.** The existing
  `test_whiteout_settles_once_behind_its_faint_and_survives_restore`-style coverage (real
  `create_runtime` → `deliver` → `runtime.close()` → `open_runtime` → `wo.verify_state`/
  `Gen1RuntimeState.restore`) was not extended to a two-link collateral batch. `verify_state`'s new
  `collateral_of` branch is exercised only by construction in the unit test above, not by a real
  restore of a persisted collateral record through the full journal.
- **`C1-reachability-successor.md`'s natural route (pre-activation faint) is still only
  source-modeled**, not driven through a real engine signal batch shaped that way end-to-end
  against this fix.
- **No emulator/cartridge evidence.** This is source + unit-level only, consistent with
  `docs/gen1_reference/README.md`'s release-proof tiers (registration/collection/component test are
  distinct from a frozen RC verdict, let alone live verification).
- **`log.warning` collateral message is unverified by any log-content assertion** — a behavioural
  nicety, not covered by a test.

READY/merge decision is left to the coordinator, per the card.
