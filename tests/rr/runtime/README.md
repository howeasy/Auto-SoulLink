# RR production-client runtime checks

This lane loads the production RR client and its real Lua dependencies against
synthetic BizHawk host APIs. It asserts desired behavior; unresolved product cases
fail normally, with no xfail or skip. Python 3.11+ is supported; this run used
Python 3.12 and Lupa Lua 5.5.

From the repository root, supply the source worktree explicitly:

```powershell
python -m pytest tests/rr/runtime --rr-repo 'E:\Google Drive\SLink\.claude\worktrees\rr-foundation' -q --tb=short
python -m tests.rr.runtime.probe --rr-repo 'E:\Google Drive\SLink\.claude\worktrees\rr-foundation'
```

These synthetic tests do not need `--rr-rom`; the separate RR reference/native
lanes use the `rr_rom_path` fixture for binary evidence. Missing selected-lane
inputs or dependencies are failures. The probe emits JSON with expected/observed
values and source hashes; exit 1 means product failures and exit 2 means a harness
error. `--case NAME` is repeatable. Optional `--output` is restricted to this
runtime evidence directory. Hashes include `lua/rr/*.lua`; a source change during
a scenario invalidates the result.

## Scope of the context, storage and temporal slices

The initial staging baseline failed all eight original regressions. Those eight
now pass, together with the additional guarded boxed-source memorialization case.
No regression is hidden by xfail or deselection.

`test_storage_context.py` additionally covers read-only preparation, unrelated
party changes, verified native deposit/withdraw boundaries, memorial readback,
script/menu/post-battle-writer/borrowed owners, restoration after borrowed reload,
and preservation of a manual-deposit baseline while a menu owns RAM.

`test_temporal_observations.py` covers delayed/duplicate counter and native-ring
evidence, prolonged transient zero HP, external and engine-caused suppressed deaths,
prior-battle/borrowed isolation, doubles and settled LOSS, retained pending deaths,
chained and ambiguous acquisition contexts, and checkpoint continuation.

`lua/rr/context.lua` classifies current ownership before RR HELLO and snapshots.
`lua/rr/storage.lua` implements the RR-specific `prepare/classify/apply/receipt`
shape. Receipts prove the six party records plus the affected source/destination
box records and are explicitly **live RAM only**. The current client uses those
helpers around its existing pending-native records and retains uncertainty.

`lua/rr/observations.lua` owns temporal detector state without host side effects.
It merges counter polls and native events as reports of one cumulative counter.
Elapsed zero-HP frames never prove a battle death: confirmation requires an
unambiguous native ordinal, settled LOSS, or a zero party record at the verified
post-battle field checkpoint. Outside-battle poison remains immediate on an owned
field; script-owned zero HP waits for a stable party readback. An external HP
write consumes no unrelated future native ordinal.
Pending candidates retain their original area across battle/borrowed transitions;
fresh battle counters cannot certify prior-battle candidates. Ended acquisitions
retain immutable origin/outcome/foe/box evidence until resolved.

The versioned detector checkpoint/restore seam is pure and validates before
replacing state. It supports later atomic frame-event/baseline publication; it
does not connect `append_many`, authorize a game rewind, or prove physical state.
`lua/rr/battle_snapshot.lua` routes an outgoing battler by its matching PID/OT
when the index has already advanced to an incoming mon. An unattributed zero
with settled counter evidence disables counter-only conclusions for that battle
and retains the diagnostic in the checkpoint.

Future frame publication can preserve execution order by collecting semantic
events at the existing `send` sites, then appending them together with the complete
post-frame detector baseline before transport delivery. That baseline must also
include the client's existing party/map/known-key/resolved-area, migration/freeze
and gift/box-buffer state; this observer checkpoint alone is insufficient. Native
receipts belong to command completion, while presentation traffic stays volatile.
Failed publication must pause, retain the candidate batch and pre/post baselines,
and resolve the store's actual commit before retrying observations. It must not
rerun physical-command phases as an observation retry.

This is **not activation of the shared durable dispatcher**. The native lease in
the adapter is volatile; persistent native reservation/generation, admitted command
IDs, paired pause/recovery, save/rewind policy and independent server validation
remain coordinator integration requirements. An armed operation cannot classify
as a reapplicable before-state in the same runtime, but this does not establish
restart-safe ownership. No local or distributed persistence claim is inferred
from the existing client events.

## Evidence boundaries

- Production client, game detection, profile/area tables, memory helpers, mailbox,
  and RR modules load as written. No source-string rewrites, private-upvalue
  injection or replacement of their functions is used. Harness tests verify
  loaded function paths.
- The connector is an in-memory FIFO; HUD, drawing, input and peer-ghost rendering
  are no-ops. No network or emulator is opened. Synthetic header/save/signature
  bytes pass the actual RR detection and validation; no ROM/save file is loaded.
- Production-origin writes are logged and restricted to GBA EWRAM/IWRAM. Storage
  regression fixtures place canaries immediately outside affected records.
- Native ARM handlers are not executed. Tests enqueue real server commands,
  inspect real mailbox requests, and supply explicit game-state/ACK boundaries.
  Successful withdrawal fixtures supply a recomputed party record; they do not
  verify RR's stat-calculation code. A contradictory ST_OK tests rejection of
  inconsistent readback, not a claim that native handlers ordinarily lie.
- Faint scenarios include empty, delayed and duplicated native event rings.
  Long zero-HP intervals without settled evidence must not trigger death.
  Overlapping battles use adversarial frame ordering; real timing and source-kind
  reachability still require cartridge evidence.
- These tests do not prove performance, audio, graphics, game-save persistence,
  distributed recovery or release readiness. Real native and two-player gates
  remain necessary.

## Loaded-name source evidence

The pinned RR4.1 base (SHA-256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`)
contains `SaveInputText` at `0x0809F7EC`. Its comparisons at `0x0809F814` and
`0x0809F818` skip `00` (space) and `FF` (EOS) while looking for any nonblank
character. At `0x0809F82E` it passes the original buffer base to `StringCopyN`
(`0x08008DBC`), preserving leading spaces. This matches the actual operations in
pret/pokefirered commit `e060ab955b5dc9ac1c4904c2cd141683615cf477`,
`src/naming_screen.c:1851-1863`, and its `charmap.txt` (`' ' = 00`).
The runtime tests therefore accept leading-space names followed by letters,
while rejecting all-blank and unterminated eight-byte records. Transient
`save_fingerprint` still includes RAM pointers and is not durable SaveIdentity.

The same pinned base's `DestroyTask` at `0x08077508` computes a 40-byte stride and
clears only `Task.isActive` at `+4` (`strb r0,[r2,#4]` at `0x08077520`). Function
pointers can remain after destruction. Context and post-battle proof tests set an
authentic active flag and verify that clearing it, without clearing the function,
unblocks storage and settled readback.
