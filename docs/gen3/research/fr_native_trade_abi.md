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

## T2-FR-CARRIER candidate extension

This adds the accepted RR carrier's existing opcodes and Pokemon-Center NPC
entry to the private FR composition. It does not add a new offer UX, a raw swap,
or another save path. The server still supplies menu/offer text and drives the
selection protocol; native PREPARE consent/save and SCENE remain as above.
The carrier's native UI/NPC lifecycle requires its own live check; the earlier
panel receipt does not qualify it. READY remains 0, candidate capability mask 3.

| Opcode | Staging/args | Native completion result[0] |
| --- | --- | --- |
| 13 ARM_PEER_INTERACT | args[0]=object-event slot 0..15, args[1]=armed | Immediate ACK; armed resets PI_COUNT to zero as RR does |
| 17 SHOW_MENU | bounded EOS text in first 256 bytes of TEXT | 1=YES, 0=NO/B |
| 20 CHOOSE_PARTY_MON | no payload | slot 0..5, 7=cancel |
| 22 SHOW_CHOICES | MENU: count 1..8 followed by EOS strings, total <=112 bytes; args[0]=with-text; optional TEXT | option index, 127=cancel |

13 requires CONTROL.session_epoch to match the nonzero mailbox epoch, and an
active target when arming. The target local ID and map identity are captured,
so a reused object-event slot cannot silently become a new interaction target.
17/20/22 validate before taking field/script ownership, copy their text/options
into private storage, set BUSY and clear opcode, and ACK only after native UI
return to the safe field. Their result meanings match RR. New requests cannot
replace an owned UI; a changed epoch/sequence cannot inherit its completion.
Host timeout/poison handling remains required; native ownership is not discarded
on a guessed UI deadline. Native allocation failure resumes/releases the field
script before reporting failure. These are carrier results, never trade witnesses.

For the presence-OFF PC-trade entry (PC means Pokemon Center here), stage
CONTROL.session_epoch at arena+0x800 and TN_ENABLE=1 at arena+0x808. The producer
spawns the same Oak graphic (0x47), wandering behavior (2), local ID 0xF1 and
current-coordinate tile (10,9), with range +/-1. The 19 eligible Center 1F map
IDs are checked against pinned vanilla FR `data/maps/map_groups.json`.
Presence mode switching remains the host's responsibility; setting TN_ENABLE=0
removes only this producer's still-matching NPC. Opcode 13 can arm an existing
peer object, but does not implement the separate ghost spawn/movement opcodes.

Read native PI_COUNT as **u32** at arena+0x804. It increments only for a newly
pressed A while idle, facing the bound active object on the safe field; the
producer consumes that A before the engine attempts a missing map-template
script. It does not display an unsolicited local message. The client converts
the counter edge into the existing server trade_request flow. No epoch/config
match, unsafe field, moving player, stale slot or active trade/UI means no edge.

Native calls use vanilla FR `SpawnSpecialObjectEventParameterized` 0x0805E830,
`RemoveObjectEvent` 0x0805E4B4, and `ChoosePartyMonByMenuType` 0x081283A8 with
type 3. The builder validates their entry bytes and emits `carrier_bindings`.
Unlike RR's internal-removal binding, FR's RemoveObjectEvent clears active
itself. The chooser preserves the engine's return/fade/script-resume callback.
The owned NPC is removed before party chooser/trade-scene takeover and can
respawn on safe field return. Private carrier state is arena+0xB40, NPC state
+0xCE0, runtime scratch +0x960; compile-time bounds keep panel and phone storage
separate. Consumers must retain HARNESS_ONLY selection labeling until the native
carrier is bound and independently exercised; enum IDs alone prove nothing.

### FR carrier live receipt, 2026-09-27

Producer `684ab4c8ec09c22c46f93c3c670e35026c6e895e` passed one single-cart
normal-input run from the existing FR town save, walking into Viridian Center.
Receipt: `patch/build/carrier-live-20260927/carrier_receipt.json`; native log,
script, config, input save and flushed native SaveRAM are alongside it.
Candidate ROM SHA256:
`ddc2803b270f1ecbd42aefb2a1bb45308b122fee2131943625b71ab5fc74056d`.
The private directory was `.cache/c`, with SLINK_STATE_DIR at its `states`
child. Only owned EmuHawk PID 45424 ran; it exited and the lane was released.

The native Center NPC produced counter edges 0->1 and 1->2 from ordinary facing
A presses. Replayed server-format `Trade / Say hey` and offer text then drove
22/20/17 to results 0/0/1. The party chooser entered CB2_InitPartyMenu
(`0x0811EBD1`). PREPARE consent/pre-save produced the bound witness, exactly one
native TrySavingData entry, and save counter 4->5; WITHDRAW returned UNCHANGED.
The B paths returned 127/7/0. Every UI ACK followed safe-field return and owned=0;
disabling TN removed the NPC. Python decoded the private text/options, party RAM
and flushed SaveRAM independently: roster/checksums were intact and the save
counter advanced once. Altered counter/result/epoch/callback/option receipts
are rejected by the recorded oracle controls.

This qualifies that bounded native carrier sequence only. It used replayed
server payloads, not a live server/T3 carrier adapter. It did not run SCENE, a
duo, cold save reload, every Center map, ghost interaction, or explicit opcode-13
arming (the PC NPC arms itself). No screenshot supplied game facts. The earlier
HARNESS_ONLY selection seam remains so labeled until replaced and independently
exercised in T5. READY remains 0.

## FR native sounds candidate extension

Opcodes 19 PLAY_SE and 9 PLAY_FANFARE take a u16 little-endian song ID in
args[0..1]. Candidate capability mask is now 7 (trade, panel, native sound).
FR bindings are PlaySE `0x080722CC` and PlayFanfare `0x08071C60`; the builder
pins both entry byte sequences in `sound_bindings`. The 347-entry native song
table admits IDs 0..346; larger IDs are refused before an engine call. Source
and symbol extent (`dummy_song_header - gSongTable`, eight bytes per entry)
independently establish the bound. Calls require a nonzero session epoch matching
CONTROL.session_epoch at arena+0x800. The consumer must stage that configuration
binding alongside its mailbox epoch before posting sound; writing only the
mailbox epoch is insufficient. A mismatch returns IDENTITY (12) without calling
either native routine; epoch zero returns CLIENT_TOO_OLD (13). Calls
refuse while a panel/carrier UI or PREPARE/SCENE owns the native lane.

An OK ACK means the native routine was invoked, not that the requested sound
was audible or finished. The engine's own PlaySE suppression during quest-log
playback remains intact. PlayFanfare retains its native fallback to the first
fanfare for in-range IDs absent from its fanfare list, and requires a free task
slot. No direct sound-player RAM poke or new game option is introduced.

The existing `native_sounds` client option suppresses posting when false and
posts opcode 19 when true. The shared Lua option/queue behavior is tested on its
established RR MODEL fixture; that is not separate FR/T3 client admission or
physical audio evidence. The initial checkpoint had SOURCE/MODEL/build coverage; the bounded leased
engine-playback evidence is recorded below. READY stays 0;
no production patch is published by this extension.

### FR native sound live receipt, 2026-09-27

Epoch-bound producer `4df26e0ebb0200fb006e406e35dcaacf3ee35d14` passed the
single-cart engine-state check. Receipt:
`patch/build/sound-live-20260927/sound_receipt.json`, with native log and run/build
identities alongside. ROM SHA256:
`dc7841cacc36316ecc24611d3a292e7a25c56a093c1899964aa1c434bfc5d5ae`.
Only owned PID 11748 ran under private `.cache/s` / `.cache/s/states`; it exited
and the lane was released.

Hooks witnessed PlaySE(25)->m4aSongNumStart(25) and
PlayFanfare(257)->m4aSongNumStart(257). Python independently read the ROM song/
player tables and matched live player/header pairs `03007340/086B5BB0` and
`03007380/086BCD98`, active track masks and advancing clocks. The fanfare counter
77->0, task removal and BGM pause 1->0 established native completion/resumption.
IDs 347/65535, epoch zero, and request epoch 8 against configured epoch 7 were
refused without extra sound calls (reasons 2/2/13/12). Altered call/header/clock/
pause/refusal receipts are rejected by the oracle controls.

This is native dispatch/m4a-state evidence, not audible-output, speaker/device,
or physical FR client-toggle qualification. No screenshots supplied facts.
The nonzero mismatch check requires CONTROL epoch staging described above;
the old mailbox-only handshake does not supply that configuration. READY is 0.

## FR Rival Team Swap W1 candidate extension

Opcode 28 retains the RR request shape: args[0]=count 1..6, args[1..2]=trainer
ID u16 little-endian, and count*100 party-record bytes staged at BLOB. Mailbox
epoch must be nonzero and match CONTROL.session_epoch. Candidate mask becomes
23 (trade, panel, sound, rival); no Explode bit is added by this producer.

The native consumption gate is bound to **vanilla FR**:

| Evidence | Required value |
| --- | --- |
| gMain.callback2 at `0x030030F4` | CB2_HandleStartBattle `0x08010509` |
| gBattleMainFunc at `0x03004F84` | BeginBattleIntroDummy `0x080123BD` |
| gBattleCommunication[0] at `0x02023E82` | less than 15 |
| gBattleTypeFlags at `0x02022B4C` | TRAINER mask 0x08 set, LINK mask 0x02 clear |
| gTrainerBattleOpponent_A at `0x020386AE` | requested trainer ID |
| gMain.inBattle at `0x03003529` | mask 0x02 set |

Source: pinned `battle_main.c:648-716,934-1066` creates the trainer party before
returning with this callback/state; case 15 invokes InitBattleControllers, whose
single-player path changes the dummy function and then calls SetBattlePartyIds
(`battle_controllers.c`). Non-link FR normally passes states 0,1,15: this is a
short early window, so the existing client pre-announcement/staging discipline
is still required. RR's callback address is not reused. W2 is not implemented.

All records are copied to aligned private stack storage before validation. The
native wrapper is explicitly out-of-line so its 600-byte snapshot is released
before the original game callbacks execute.
Native GetMonData checks species/checksum-bad-egg state on the copy; eligibility
uses HP (field 57), SPECIES_OR_EGG (65, egg=412), and IS_EGG (45), matching the
engine selection predicate. Singles require at least one selectable slot;
doubles (flag 1) require two distinct selectable slots. A fainted lead with a
later live slot is valid in W1. The gate is read again before the first enemy
write. Success replaces gEnemyParty records, zeroes unused slots, then publishes
gEnemyPartyCount; it never writes gBattleMons or performs a late refresh.

Refusal leaves the enemy party untouched: BAD_ARGS=2 for count/record refusal,
WINDOW_CLOSED=8 for a closed/mismatched context, SLOTS_UNVIABLE=15 for insufficient
selectable slots, IDENTITY=12 for a configuration epoch mismatch, and
CLIENT_TOO_OLD=13 for zero epoch. There is no raw fallback.

The client still owns server session/battle_id equality, queued-payload freshness
and response correlation from `rival_swap_refresh_window.md`. Native W1+trainer
matching is not proof of that per-battle request identity. No new battle_id ABI
field is invented here. The initial extension had SOURCE/MODEL/build evidence;
the bounded natural trainer-battle check is recorded below. READY stays 0.

### FR Rival W1 live receipt, 2026-09-27

Producer `c7c6bd46675320ea362c3320458e8608264068b4` passed the bounded real-trainer
check. Receipt: `patch/build/rival-live-20260927/rival_receipt.json`; native log,
script, config, input save and replacement/late payloads are alongside it.
ROM SHA256: `421f72aa88f3eda47bbf316cde7a1aac8369aaabae3188987123f1bb7a990007`.
One owned PID 42860 ran under `.cache/r` / `.cache/r/states`, exited, and the lane
was released. An earlier driver trial never triggered a battle and is retained
under `rival-live-20260927-failed-trigger`; the native handler was not exercised
there. Waiting for a quiet field and completing a normal Right step reached
Rick102's sight line from the existing FR trainer fixture.

The replayed peer-fixture team deliberately had a fainted lead and live second
slot. Native dispatch was observed at W1 stage 0 with the exact FR callback,
dummy function, trainer102 and TRAINER flag. ACK preceded the engine's
SetBattlePartyIds at stage15; its entry readback exactly matched the replacement
and zeroed unused records. Native selection chose slot1, and Python independently
matched BattlePokemon species/HP/level/maxHP/PID/OT to that live second record.
The late request was consumed at callback `08011101`, main function `08014041`,
stage1 (still less than15), and refused with reason8. All600 enemy-party bytes
and count remained unchanged. Altered selection/ACK/window/late-write receipts
are rejected by oracle controls.

This is a real Rick trainer battle with replayed team data, not a live-server,
duo, automatic story-rival, battle-finish or save-persistence qualification.
Only normal inputs triggered/advanced gameplay; writes were confined to the
owned request/config/staging ABI. No screenshots supplied facts. READY stays 0.

## LeafGreen candidate binding extension

The same producer composition now builds privately for LeafGreen using its own
`patch/src/trade_targets/leafgreen.h` and linker script. Base identity is BPGE
revision0, SHA1 `574fa542ffebb14be69902d1d36f1ec0a4afd71e`, as pinned in
`data/gen3_sources.lock.json`. Payload candidate is `0x08EB0E14`; arena candidate
is the same computed heap carve-out `0x0201B000`, still unqualified.

`leafgreen_bindings.json` records 75 symbol+offset derivations and five menu-table
references against the independently hashed `pokeleafgreen.sym`. Shared layout
constants come from the same locked pret source, not an assumed address delta.
Fourteen pointer values differ from FR. Examples:

| Binding | FR | LG |
| --- | --- | --- |
| RunSaveFailedScreen | `080F5118` | `080F50F0` |
| RunHelpSystemCallback | `0813B870` | `0813B848` |
| TrySavingData | `080DA364` | `080DA338` |
| SaveQuestLogData | `08112450` | `08112428` |
| ChoosePartyMonByMenuType | `081283A8` | `08128380` |
| Menu_InitCursor | `0810F7D8` | `0810F7B0` |
| Start-menu action table | `083A7344` | `083A7324` |

Every byte anchor is read from the exact LG ROM; replayed trade/evolution
prologues are additionally required to match the audited instruction shape.
The private builder verifies original detours, call anchors, relocated table
references, linked entry and FF payload range, and emits its own receipt at
`patch/build/candidate-leafgreen-trade/receipt.json`. It does not publish UPS.
FR-only allocator probe modes remain FR-only; permitting an LG private candidate
does not admit the heap carve-out or inherit FR physical receipts. LG READY=0,
production=false, capability mask23 for the test composition. The initial native
LG lifecycle checks were unrun; the bounded receipts follow below.

### LG single-cart live receipts, 2026-09-27

Producer `3583502459778bab4d61635e42cd3ec900112111` passed five sequential private
LG runs. Aggregate: `patch/build/lg-live-20260927.json`; per-mode records:
`patch/build/lg-{carrier,panel,sound,rival,trade}-live-20260927/leafgreen_receipt.json`.
All share candidate SHA256
`a0e5fe73b888f86abf8d9722703334a3afd1ee5f68d56ed7f8e6ef08eec48db0`.
Each used a distinct `.cache/lg-<mode>` run/state directory and its LG fixture.
Owned PIDs 27256/43796/29156/42760/15248 exited; the lane was released for T5.

- Carrier: native NPC counter edges, choices/chooser/offer A/B results, LG chooser
  callback `0811EBA9`, PREPARE save counter3->4 and unchanged withdrawal; independent
  text/options/party/SaveRAM decode passed.
- Panel: normal START/action9, decoded five rows plus PAGE1/1, VRAM/palette and
  locked-field witnesses, A/B closure. One inherited raw PANEL_SCOPE line says
  FR; the structured receipt annotates this label and retains the original log.
  ROM/title/config/symbol identities establish that this was LG.
- Sound: LG tables selected headers `086B548C` and `086BC674`; native clocks and
  fanfare task/BGM release passed, as did invalid-ID/unarmed/stale-epoch refusals.
  No audible-output or physical client-toggle claim.
- Rival: a real Rick102 battle consumed W1 at stage0, selected the live second
  slot (Rattata) from the replayed peer fixture with deliberately fainted lead,
  and refused the late request without changing the enemy party.
- Trade: the existing single-cart driver used a disclosed full-party/full420-box
  SYNTH setup derived from the LG town fixture. Native PREPARE/commit/scene/
  evolution/post-save completed, counter3->5, then a reset without an extra manual
  SAVE retained Machamp68 / PID13572468 / OT78563412. Independent flash and
  reloaded-party decoding passed.

The harness translates only symbol-verified addresses (or explicit shared GBA
palette/VRAM/private-arena locations) and records its translation audit per run.
LG-specific sound-table oracle controls reject using the FR tables. These are
bounded native single-cart checks with replayed payloads and the disclosed trade
setup, not live server/T3 integration, duo, all-scene heap, or production admission.
No screenshots supplied game facts. READY stays 0; no UPS is published.

## Emerald source and Match Call MODEL checkpoint

This is not an Emerald native composition or admission. The builder still
rejects Emerald candidate builds and its READY remains0. Source pin:
`pret/pokeemerald c65e93f20a5275ab03b07d6f6411096a82a60ffd`; exact BPEE revision0
ROM SHA1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7` was checked. Entry addresses
and short ROM anchors are recorded in `trade_targets/emerald_lifecycle.json`.

Emerald CallCallbacks at `0800051C` has no FR save/help guards. Its first eight
bytes include `ldr r4,[pc,#0x1C]`, reading gMain `030022C0` from literal `0800053C`.
The header explicitly requires replay/relocation and continuation at `08000525`:
save r4/LR, load the relocated gMain pointer, load callback1 and preserve its CMP
flags into the original tail. That tail invokes both callbacks. A plain reuse
of the FR body/guards is not an implementation of this contract.

Native save consent is `SaveGame 0809FF80` and its SaveGameTask publishes result
1 on success, 0 on cancel/error before resuming the script. Normal post-save
entry points include SaveMapView `080883C4` and TrySavingData `08153338`; no FR
quest-log call is assumed. Native integration and lifecycle tests are still open.

For Match Call, `ShowPokenavFieldMessage 08098238` first checks the field message
owner, expands its text into gStringVar4, creates a completion watcher and calls
`StartMatchCallFromScript 08196080`. The latter ignores its message argument:
calling it alone does not stage text. The native task progresses through graphics,
window creation, slide-in, intro/message, slide-out and cleanup. A native adapter
must prove visible entry and eventual release, including allocation-failure and
script unlock paths; timer guesses or task creation alone are insufficient.

`call_producer.h` is a standalone controller tested with engine callbacks, not
yet connected to that native UI. It accepts the agreed event in args[0] with
remaining args zero, validates/copies the 36-byte record, publishes coherent
nonzero-even ARMED/REFUSED before ACK, and marks DELIVERED only from the engine's
visible signal. COMPLETE retains event/delivered_frame until a subsequent job.
Name fields require bounded EOS and reject text command bytes F7..FE; missing
or out-of-range species remain generic-call metadata rather than rejection.
Native rendering/contact/text parity with the Gen2 phone strings remains open.

The model preserves an open UI's old-epoch record/witness. A fresh request while
occupied receives prompt CALL_BUSY=16 without replacing the old witness. An
epoch change drops only pending work that has not entered native UI. Cooldown
10800 uses the native frame at actual delivery and survives host epoch changes.
CALL_UNAVAILABLE=17 denotes refusal/unobserved delivery after UI release;
CALL_COOLDOWN=18 denotes the native gap. Epoch/seq replay with a different event
is refused as IDENTITY. These are v2 reason names; none changes the trade
pre-commit refusal allow-list. No Match Call capability is published by this
MODEL checkpoint.
