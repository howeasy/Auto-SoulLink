# Memorial storage and save proof

September 8: the independent memorial transform and receipt verifier are implemented
in `server/gen1_memorial.py`. They are not yet connected to the durable command
router. The existing `pending_memorial` death blockers stay in force.

The verifier consumes a caller-owned complete save preimage, admitted trainer,
exact dead party key and, for a nonempty grave, its owned reservation digest. It
validates the authoritative party and all initialized boxes through the existing
inventory/party codecs. The result removes only the selected party entry, preserves
remaining order, copies all 33 boxed bytes and both names, corrects BoxLevel,
initializes box banks when necessary and recomputes affected checksums. It then
uses `gen1_full_save.image` for the full original SaveGameData copy.

The receipt binds command ID/sequence/body, context, ROM and preimage. Every field
and all 32 KiB of SRAM must equal the prepared poststate. The shared
`save_file_receipt.verify_file_image` separately checks complete file hash,
length, host and fixed held frame. A matching image is not an atomic physical
commit or permission to write; host ownership and prepared execution remain
external requirements.

Yellow recognizes starter Pikachu using species, OTID and the first five OT-name
bytes. Following-disabled bit 1 refuses deposit; normal following allows it.
The deposit happiness bands and mood cap are checked against the original
`ModifyPikachuHappiness` routine, including threshold/clamp boundaries.

The legacy `memory_gb.depositMemorialMon` now rejects party/storage identity
collisions before initialization or any write. It does not turn a duplicate key
into successful completion. The durable executor must distinguish an exact
prepared poststate from a partial write or foreign state.

## Evidence and limits

- 108 new unit cases: independent Python/Lua 5.4 comparison across R/B/Y,
  initialization, current boxes and compaction positions; Yellow thresholds;
  repeated reservations; malformed inventory; unrelated-byte changes;
  stale/foreign/unflushed receipts; twelve legacy collision refusal cases.
- Six live cases pass: three new cartridge image comparisons and three existing
  original-loader/core-reset persistence gates. The new cases contain 17 complete
  image comparisons (3 Red, 3 Blue, 11 Yellow), with Yellow's original happiness
  routine checked before each Yellow deposit. CPU entry and fixture memories are
  test setup. This does not exercise a new production memorial executor.
- The first live run failed because the runner could not recognize a chained
  `G.start` expression. The gate now uses the established named entry point;
  the final run passed all six cases in 33.25 seconds.
- Broad unit/integration verification passed 5,200 tests with two existing
  Windows symlink skips in 471.86 seconds (`.cache/memorial-full.xml`). Final
  focused verification passed 108 tests (`.cache/memorial-kernel.xml`), including
  the later full-grave case and codec-error normalization. The broad run had
  collected before that final test was added. These do not substitute for full
  release/duo qualification. All 266 Lua files parse under Lua 5.4; new Python
  paths pass Ruff. Release/portable inventory validation also passes.

## Claude review reconciliation

Read-only headless task `cx-923e85ce` completed using the new default timeout.
Its snapshot preceded this turn's final fixes; it is not a review verdict on the
final files. The full response is retained in `.cache/memorial-peer-review.md`.

- Confirmed: the Lua reservation is session-local, and the new verifier still
  needs a durable owner. Retained an explicit reservation input and repeated-use
  tests. Persistence is required in the command integration below.
- Confirmed: legacy deposit lacked identity uniqueness preflight. Fixed and
  verified no writes for party/current/inactive/grave collisions in all titles.
- Rejected: missing Python level, grave terminator/species, party-list and
  current-box validation. These checks already run through `inventory` and
  `PartyCodec`; explicit malformed cases now exercise that call chain. Codec
  errors are normalized to `JournalError` at this new boundary.
- Retained: separate prepare/apply must recheck the exact current preimage,
  including Yellow effects. Partial physical writes must hold for recovery.
  Computing a complete image does not make a series of memory writes atomic.
- Rejected: dropping ownership just because current grave bytes are structurally
  dead. Structure alone cannot establish that a nonempty box belongs to this run.
  A changed reservation requires reconciliation, not silent adoption.
- Geometry is deliberately pinned to the admitted US English RBY profile.
  Relocated or non-last memorial boxes require separate verified profiles.
- Yellow happiness/mood oracle coverage was added. Ordinary faint-to-overworld
  follower lifecycle remains part of gameplay qualification; the direct deposited
  dead-Pikachu fixture does not prove that lifecycle.
- UI reads, memorial withdrawal recovery and host latency tuning remain separate
  work. None of this verifier's evidence is drawn from the legacy display helpers.

## Production integration completed September 8

The five steps below are now implemented in `gen1_memorial_runtime.py`,
`gen1_held_faint.lua`, and `gen1_held_memorial.lua`. Compact image deltas keep
complete preimages out of permit-scoped commands. Deterministic chunked writes,
full-preimage reconstruction, and separate fresh repair/save permits handle
explained interruption. Foreign changes still refuse. Prepared observations
are renewed behind intervening commands, and faint ACKs obey the same queue
order. The complete saved/live initialization flag must agree.

Completed evidence is atomically archived in journal records; active snapshots
retain checked references and reservation digests. A ten-paired-death test proves
bounded active-state growth and rejects archive tampering. Seven final live
memorial/factory cases pass, including both partial-write phases, same-core
reconnect, and Yellow/Yellow. These are fixed-frame owned lifecycle tests;
**they do not qualify moving gameplay or a replaced emulator core**.

The full unit/integration suite needs a fresh final run after subsequent launch,
archive, and source-observer changes. Terminal party, active box 12, full/unowned
grave, and changed reservation policies remain explicit release work.

### Implemented integration checklist

The additional `test_gen1_memorial_interleaving.py` regression exercises the
specific opposing-player two-death ordering: first faint ACK, first observation
queued, second independent faint, first observation ACK, real intervening
force-faint ACK, renewed observation, and both deaths' four saved memorial ACKs.
Second-pair acquisition and physical cartridge snapshots are explicit unit
fixtures; death publication, FIFO refusal/renewal, typed faint receipts,
memorial permission verification, paired closure, and reopen audit use the
production handlers. The test requires both death blockers to clear and runs
Yellow/Yellow, Red/Blue, and Blue/Yellow.

The Lua executor also has a direct `apply` negative control for each title:
change an unchanged WRAM byte or an SRAM byte outside the delta after prepare,
then call `apply` without a classify wrapper. Complete preimage verification
must refuse before any memory or file write. This specifically protects the
pre-write boundary rather than relying on the later flushed-image hash.

1. Obtain command-bound complete actor and peer preimages at qualified held
   checkpoints; the actor's engine-entry faint witness is insufficient.
2. Journal each prepared intent and per-player grave reservation, with exact
   before/after classification and restart audit.
3. Extend command-scoped held authority and the staged client executor to the
   memorial/full-save/file-flush phases. Recheck preimage and Yellow flags before
   writes, and refuse partial/foreign poststates without replaying deposit.
4. Verify each ACK against the journaled preimage; clear each pending memorial
   only after its exact file receipt. Close the death blocker only after both
   participants finish. Keep unrelated gameplay/recovery blockers.
5. Run real paired launcher, lost-ACK, partial-write and restart cases, including
   Yellow/Yellow and last-party-member/active-box12/full-grave refusal paths.

Last-party-member, active box12 and full/unowned grave states are explicit
refusals today. They require recovery policy; this component does not declare
those scenarios or Gen 1 release-ready.
