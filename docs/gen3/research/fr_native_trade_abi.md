# FireRed native trade candidate: consumer contract

Producer source: **b6481dae8453266e8bccefc58ef169373cefbf7f** on
`claude/gen3-emerald-t2`. This immutable source commit precedes this contract
commit so the document can name an actual producer SHA. ABI header baseline:
`7660760045a4227b203d6a3d3a56ffa627ed5041`. WIP checkpoint: `094eeb54`.

This is a **MODEL/build milestone**, not live duo qualification. FR target
`SLINK_TARGET_READY` remains 0. Existing production Lua admission must remain
closed. Amend this document when the producer or consumer contract changes.

## Admission and build identity

Coordinator ruling: the durable-trade capability bit is the runtime readiness
signal for an admitted **production** cartridge. There is no separate READY
mailbox/witness field. The native composition sets the bit in a production
build only when `SLINK_TARGET_READY == 1` at build time. The normal builder also
rejects unqualified targets. Consumers must not read an invented READY offset.

The private `--target firered --abi-version 2 --trade-candidate` build is the
explicit test exception: SLNK signature, ABI 2, capability bit 0 set (numeric
mask 1), but READY 0. Its `patch/build/candidate-firered-trade/receipt.json`
contains `production: false`, `status: UNQUALIFIED_TRADE_CANDIDATE`, the base and
output SHA1, payload SHA256, compiler, and detour receipts. It emits no UPS.
Production cartridge admission must reject this identity; capability alone
cannot distinguish it from production. Importing this receipt into a pinned
production cartridge manifest is **not implemented by this milestone**. A test
harness may explicitly admit it for a model/private run only.

The existing `--arena-probe trade` remains a separate TRP2 signature/capability-0
fault-injection build. Its deliberate post-save failure switch is not compiled
into the capability-enabled candidate. RR v1 is unchanged.

## Addresses and representation

FR arena base is `0x0201B000`, size `0x1000`, obtained by clamping the native
`0x02000000` heap from `0x1C000` to `0x1B000`. These are FR bindings, not LG/E
addresses. `SLINK_TARGET_ARENA_BASE == 0` is an unqualified placeholder, not the
runtime address: use `SLINK_TARGET_ARENA_CANDIDATE` for this private candidate.

All multibyte integers are little-endian. PID/OTID are unsigned 32-bit values;
do not serialize their printed hex string directly as byte order. The token is
16 opaque bytes, distinct from PID/OTID and visit ID. The consumer owns a stable
mapping from its server token; this producer does not define a text-token codec.

| Region/field | Offset from arena | Width |
| --- | --- | --- |
| signature / ABI | `0x00` / `0x04` | u32 / u16 |
| opcode / request seq / status | `0x06` / `0x08` / `0x0A` | u16 each |
| ACK seq / reason | `0x0C` / `0x0E` | u16 each |
| args / result scratch | `0x10` / `0x30` | 32 / 16 bytes |
| capability mask / session epoch | `0x40` / `0x44` | u32 each |
| trade witness | `0x50` | `0x50` bytes |
| staged incoming record | `0x100` | first 100 bytes of 600-byte blob region |

Witness offsets below are relative to arena+`0x50`:

| Field | Offset | Width |
| --- | --- | --- |
| epoch / visit ID / token | `0x00` / `0x04` / `0x08` | u32 / u32 / 16 bytes |
| revision / visit flags / milestone bits | `0x18` / `0x1A` / `0x1C` | u16 / u16 / u32 |
| milestone sequences | `0x20` | five u16 |
| final result / save status | `0x2A` / `0x2B` | u8 each |
| milestone frames | `0x2C` | five u32 |
| old PID / old OTID | `0x40` / `0x44` | u32 each |
| received PID / received OTID | `0x48` / `0x4C` | u32 each |

## Epoch, authorization, eligibility, and preparation

1. Admit the exact cartridge identity and ABI/capability first. Through the
   serialized mailbox queue, write a fresh nonzero session epoch at `BASE+0x44`
   while there is no owned transaction. This is a field write, **not an ACKed
   handshake**. Readback establishes the write only. It cannot reconcile a
   pending/uncertain transaction or confer authorization. Never change it to
   escape an uncertain outcome; a new epoch does not clear native ownership.
2. The client must validate server authorization and local outgoing eligibility
   before `prepare_trade`. Native does not validate server credentials or expose
   a separate eligibility opcode. Locate exactly one outgoing PID/OTID; reject
   invalid checksum, egg/bad egg, mail, invalid species, and unsafe field state.
   The candidate's native outgoing lookup currently checks unique identity/slot;
   full native outgoing eligibility remains a qualification gap. Do not treat
   the incoming validator as proof of outgoing eligibility.
3. Allocate a nonzero visit ID and nonzero 16-byte token for this preparation.
   Publish opcode 29 (`TRADE_PREPARE`) **last**, after args, epoch and a fresh
   request sequence. Args: slot u8 at 0; role u8 at 1; zero reserved bytes 2..3;
   old PID u32 at 4; old OTID u32 at 8; visit ID u32 at 12; token at 16..31.
   Slots are zero-based 0..5. Native accepts roles 0/1 but currently does not
   assign them different behavior; do not infer role-specific consent from it.
4. Native accepts only its idle/done state and safe field context. It publishes
   accepted flag 1, then invokes the native save-consent UI. Acceptance is not
   consent or readiness. Consent is flag 2. Successful native pre-save publishes
   milestone 0 with the PREPARE seq, then ACKs PREPARE OK. A declined/failed
   pre-save publishes terminal UNCHANGED, bound to PREPARE seq.
5. `trade_visit` is a projection of that coherent witness and local ownership,
   not a new opcode or a beacon-derived invented visit. Return the same visit
   ID/old key, accepted, pre_saved, apply_open only after consent+pre-save,
   before the client has posted SCENE/WITHDRAW, and while no terminal result is
   present. The producer has no standalone visit-discovery/NPC-selection API.

PREPARE drives consent and pre-save; there is no separate pre-save command.
The currently missing native READY lease expiry/reconciliation controls remain
review obligations before whole-FR qualification. Keep the client's bounded
preparation deadline; do not advertise indefinite apply eligibility.

## Apply and publication order

Revalidate authorization, outgoing identity/slot, deadline and incoming record.
Stage one **100-byte party record**, not an 80-byte boxed record, at BASE+0x100
through the serialized queue. Do not issue legacy opcode 16 or 18: the v2
candidate does not implement those transports. A consumer facade named
`transfer("enemy")` must become staging-only for v2; only opcode 21 starts the
native transaction. Bind the staged record to the same queued SCENE job.

Publish opcode 21 (`TRADE_SCENE`) with a fresh seq and the same args identity.
Native copies staging into aligned private storage and checks incoming species,
checksum/bad-egg/egg/mail and duplicate party identity before starting the real
native trade scene. At the actual TradeMons entry, the guarded hook rechecks the
original party slot and publishes COMMIT_ENTERED immediately before mutation.
Scene/evolution completion is observed on return to the safe field. Native then
calls the native save path and publishes success only after its successful return.

| Index / bit | Meaning | Required command seq |
| --- | --- | --- |
| 0 / `0x01` | PRE_SAVE_OK | PREPARE |
| 1 / `0x02` | COMMIT_ENTERED | SCENE |
| 2 / `0x04` | SCENE_EVOLUTION_DONE | SCENE |
| 3 / `0x08` | POST_SAVE_OK | SCENE |
| 4 / `0x10` | FINAL_RESULT | SCENE for apply outcomes |

The native writer brackets updates with odd/even revision publication. Read
revision, copy, reread; accept only equal nonzero even values. Require matching
epoch, visit, all token bytes, old PID/OTID and each milestone's command seq.
Status probes never retag milestone sequences. Frames are native counters for
diagnostics; multiple milestones can occur in one emulator frame. Do not require
strictly increasing frame values or compare them to a different host clock.

Deliver cumulative progress to `trade.lua` in this logical order:
`commit_entered`, then `scene_done`, then `save_success`, then `final_result`.
All may be observed in a single stable snapshot. Final committed=1 requires
all bits `0x1F`, both visit flags, save_status=1, correct sequences, and received
PID/OTID matching the incoming record. Save status 1 alone may describe the
**pre-save** and is never post-save proof. The host must still flush SaveRAM and
apply its journal rules; native save success alone does not retire that journal.

## Refusal, withdrawal, reset, and replay

Final results: pending=0, committed=1, unchanged=2, uncertain=3. Status: busy=1,
OK=2, FAIL=3. The witness carries transaction outcome; result scratch is not a
replacement. A successful unchanged cancellation is transport FAIL/reason 0,
so FAIL alone cannot distinguish it from a post-mutation failure.

Opcode 30 WITHDRAW repeats identity. Only the prepared READY state can become
UNCHANGED via WITHDRAW, with FINAL_RESULT seq equal to the WITHDRAW request.
During running native UI/scene it fails without proving cancellation. Opcode
31 STATUS repeats identity and ACKs inspection; it does not advance or rebind
the witness. Exact successful PREPARE/SCENE retries may return cached results;
do not submit a new SCENE seq as recovery from an uncertain result.

Reason 11 includes uncertainty; reason 12 covers identity/phase refusal. Reason
13 is named CLIENT_TOO_OLD (zero epoch) in ABI but is not yet routed by this
producer; zero epoch currently falls through reason 12. Bad args may use 2.
There is **no reason-only pre-commit safe allow-list**. Missing COMMIT_ENTERED
is not proof of no mutation. Only the correctly bound stable terminal UNCHANGED
witness proves the producer's unchanged result. Late/wrong-identity requests
must not acquire the older operation's witness.

UNCERTAIN is sticky in this candidate. Epoch writes do not reset it. No explicit
reconciliation opcode is implemented. A real game reset clears volatile state;
the client must retain its journal and reconcile independently reloaded save
evidence before reuse. An emulator savestate load is not evidence of durable
save reconciliation. Native READY expiry, explicit reconciliation, outgoing
eligibility completion, chooser lifecycle census and the remaining independent
review items are still open. This document does not claim those gates passed.

## Verification boundary

`test_patch_trade_producer.py` compiles the real portable controller against
deterministic engine callbacks. It checks advertisement, accepted/pre-save,
commit-before-scene-before-save, durable final identity/sequences, declined
pre-save, wrong epoch/token, explicit guarded abort, missing commit marker and
post-save failure. These are MODEL controls. The private FR ARM composition
build verifies exact clean-ROM and detour anchors. Neither proves a live duo,
native party chooser behavior, or production admission. READY stays 0 and no
UPS is published by this milestone.
