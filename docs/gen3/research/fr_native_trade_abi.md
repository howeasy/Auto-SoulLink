# FireRed native trade candidate: consumer contract

Producer source: **2133349d2ef359dad4a002441994267d3c762651** on
`claude/gen3-emerald-t2`. This immutable source commit precedes this contract
commit so the document can name an actual producer SHA. ABI header baseline:
`7660760045a4227b203d6a3d3a56ffa627ed5041`, amended by T2-R1 below. WIP checkpoint: `094eeb54`.

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

The candidate path selects ABI 2 independently of `--abi-version`: that option
is not read on this path. The frame service advertises only after observing the
heap size installed by the heap-clamp hook; a compiled payload alone is not a
runtime beacon.

The existing `--arena-probe trade` remains a separate TRP2 signature/capability-0
fault-injection build. Its deliberate post-save failure switch is not compiled
into the capability-enabled candidate. RR v1 is unchanged.

## Addresses and representation

FR arena base is `0x0201B000`, size `0x1000`, obtained by clamping the native
`0x02000000` heap from `0x1C000` to `0x1B000`. These are FR bindings, not LG/E
addresses. `SLINK_TARGET_ARENA_BASE == 0` is an unqualified placeholder, not the
runtime address: use `SLINK_TARGET_ARENA_CANDIDATE` for this private candidate.
The arena lies inside the original heap reservation. `validate_arena` would
reject it; the private builder does not run that static check. Its receipt says
`arena_static_check: "skipped: heap clamp unqualified"`. Detour/ROM checks and
a candidate build do not establish arena safety or physical qualification.

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
| native producer phase / reserved | `0x48` / `0x4C` | u32 each |
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
   with producer phase READY, before the client has posted SCENE/WITHDRAW, and while no terminal result is
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
FR entry points, from `data/gen3/pret/pokefirered.sym`, are SaveMapView
`0x080590D8`, SaveQuestLogData `0x08112450`, and TrySavingData `0x080DA364`.
The binding calls them in that order, with SAVE_NORMAL=0. At the pinned pret
source `src/save.c:650-720`, HandleSavingData serializes the game and writes the
full save slot; TrySavingData returns OK when flash is present and no damaged
save sectors are reported after that operation. This is the native engine's
success report, not independent evidence of host SaveRAM flush, disk durability,
a cold reload, peer-cartridge completion, or journal reconciliation.

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
All may be observed in a single stable snapshot. The canonical structural success predicate is
[`slink_trade_success_is_durable`](../../../patch/src/trade_targets/abi.h),
called with the PREPARE seq, SCENE seq and expected incoming PID/OTID. Its
received-identity comparison is part of that predicate; do not copy a weaker
local version. It assumes the caller has already checked coherent snapshot,
epoch, visit, token and outgoing identity as above. Save status 1 alone may describe the
**pre-save** and is never post-save proof. The host must still flush SaveRAM and
apply its journal rules; native save success alone does not retire that journal.

## Refusal, withdrawal, reset, and replay

Final results: pending=0, committed=1, unchanged=2, uncertain=3. Status: busy=1,
OK=2, FAIL=3. The witness carries transaction outcome; result scratch is not a
replacement. A successful unchanged cancellation is transport FAIL/reason 0,
so FAIL alone cannot distinguish it from a post-mutation failure.

Opcode 30 WITHDRAW repeats identity. Only the prepared READY state can become
UNCHANGED via WITHDRAW, with FINAL_RESULT seq equal to the WITHDRAW request.
During running native UI/scene it fails with reason 14
(`SLINK_REASON_WITHDRAW_TOO_LATE`) without proving cancellation or uncertainty
of the original transaction. That transaction can still commit successfully. Opcode
31 STATUS repeats identity and ACKs inspection; it does not advance or rebind
the witness. Exact successful PREPARE/SCENE retries may return cached results;
do not submit a new SCENE seq as recovery from an uncertain result.

Reason 11 denotes an UNCERTAIN terminal result; reason 14 rejects a too-late
WITHDRAW without changing the transaction outcome; reason 12 covers identity/phase refusal. Reason
13 is named CLIENT_TOO_OLD (zero epoch) in ABI but is not yet routed by this
producer; zero epoch currently falls through reason 12. Bad args may use 2.
There is **no reason-only pre-commit safe allow-list**. Missing COMMIT_ENTERED
is not proof of no mutation. Only the correctly bound stable terminal UNCHANGED
witness proves the producer's unchanged result. Late/wrong-identity requests
must not acquire the older operation's witness.

The mailbox native-only `producer_phase` at +0x48 is an aligned atomic u32:
IDLE=0, PRE_SAVE=1, READY=2, SCENE=3, DONE=4, UNCERTAIN=5. PRE_SAVE/READY/SCENE/
UNCERTAIN are owned states even when the witness epoch differs from the mailbox
host epoch. The service publishes phase before and after processing every frame,
including rejection paths. It does not retag the old witness when epoch changes.
Sample with the emulator CPU paused at the service boundary; phase is not part
of the witness revision and cannot replace coherent outcome checks. Unknown
phase, stale binding, or unreadable data is not proof of an idle producer.

To test no owned transaction: require a fresh admitted binding, empty local
queue/no in-flight job, mailbox opcode 0 and status not BUSY, plus phase IDLE;
phase DONE is reusable only after the client has consumed and reconciled its
coherent terminal result. A phase read while a command is queued is insufficient.
If an epoch write races PREPARE, the native phase remains PRE_SAVE/READY even
though identities differ. Stop posting and recover; do not reinterpret that as
an idle producer or overwrite its epoch to force reuse.

Exact uncertain/epoch-race recovery:

1. Stop staging/posting; retain the transaction journal and old witness identity.
2. Perform a real game reset, allowing native UI teardown and volatile state
   clearing. Do not clear producer_phase or controller memory from the host.
3. Reload the native save and independently reconcile party/save evidence against
   the retained transaction journal. Unresolved evidence keeps the client closed.
4. After reconciliation, require a fresh cartridge binding and a serviced IDLE
   phase with no pending mailbox job. Write a fresh nonzero session epoch through
   the serialized queue, then allocate a new visit/token and PREPARE normally.

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

## Private panel checkpoint extension

The subsequent panel composition adds capability bit 1 to the private candidate
(combined mask 3); the immutable trade-core SHA above remains its baseline.
READY remains 0 and the receipt remains non-production. This extension is
SOURCE/MODEL/build plus the bounded native UI run recorded below. Allocator
failure recovery, pagination, live trade/panel coexistence and server/T3 adapter
integration are not yet qualified.

Opcode 27 binds INFO.request_seq to the mailbox seq and INFO.session_epoch to
the mailbox epoch. It validates enabled, 1..6 rows and bounded EOS (including
the page slot), privately copies the full INFO record, and ACKs acceptance.
ACK is not DRAWN. Native publishes state 1 while opening, state 2 plus drawn_seq
after drawing, then state 0 plus closed_seq/result after releasing field controls.
Result 0 means A/next; 0x7F means B/close; 0xFF denotes allocation failure before
drawing. Host staging changes cannot mutate the owned display snapshot; an epoch
or request mismatch suppresses publication into a newer host record.

The normal-field menu gains action 9, SOULLINK, before EXIT only when valid data
is staged and trade ownership is IDLE/DONE. The builder relocates the two ROM
tables, preserving all nine original entries (including link-room PLAYER), and
pins five table references plus the normal-field setup entry. Link/Union Room/
Safari builders are unchanged. Menu selection opens the current staged request
without consuming a mailbox job; consumers must observe INFO state transitions,
including reopenings of the same staged request. The menu's fade is restored
before starting the field panel.

Private panel state occupies arena+0xA00 through its compile-time checked extent;
native runtime scratch is +0x940. Text stays owned through native UI closure.
The renderer retains the existing six-row, 27x13-tile panel layout with paired
rows, status labels and HP bars. Engine addresses and normal-menu behavior are
pinned to vanilla FR source/symbols; RR v1 code and published UPS are unchanged.

### FR panel live receipt, 2026-09-27

Producer composition `280445a85563cda8d7ea562c7dbd439983fd656a` passed one
single-cartridge run using the existing town save and the five-row payload
replayed from the accepted RR receipt
`docs/gen3/probes/rr_infopanel_gen3_gen3_rr_as_a_f78b533a_r2.txt`.
This is a disclosed input fixture, not evidence that a current server sent it.
Only host-owned ABI staging was written; game navigation used normal inputs.

Receipt: `patch/build/panel-live-20260927/panel_receipt.json`, with native log
`result.txt`, input rows, ROM/build/run identities and Lua driver alongside.
Candidate ROM SHA256:
`88a656a7d890832add2d9566fb173acd81f2b32bd4e3d31dea99c59df1d297d4`.
The private run directory was `.cache/p`; SLINK_STATE_DIR was its `states`
child. The single owned PID 2148 exited, and the emulator lane was released.

START produced count 8/order `0,1,2,3,4,5,9,6`. Normal cursor presses selected
SOULLINK. On both openings, Python independently decoded every row and the
PAGE 1/1 header from the native private snapshot; epoch/request/drawn matched,
field controls were locked, VRAM changed, and palette RAM was nonblack. A then
B closed with results 0/127 and released controls. A deliberately corrupted
readback was rejected by the oracle. No screenshot supplied game facts. Each
opening used a distinct host request seq (1, then 2); this does not qualify
same-request reopening or automatic pagination. No server/T3 adapter, duo,
save-persistence or general heap safety claim follows from this run. READY is 0.
