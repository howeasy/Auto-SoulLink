# SoulLink RR release: implementation contract

## Approved outcome and scope

Make SoulLink's Radical Red 4.1 integration stable through a moderate rewrite of
orchestration and native ownership. Preserve verified readers, compressed storage
conversion, native engine entry points, and the existing Lua Explosion mechanism.
All current production features remain required.

| Contract | Required behavior |
| --- | --- |
| Cartridge | The exact admitted RR4.1 build on both players |
| Companion | Matching supported build/ABI/layout required on both players |
| Mode | Default; MGM off/off or on/on only |
| Rejection | Mixed MGM, other difficulties, internal randomizers, missing/stale patches |
| Interruptions | Pause gameplay on either disconnect or uncertain effect; paired reconciliation before resume |
| NPC exchange | Confirm identity migration, preserve the link half, recheck established clauses |
| Other generations | Compatibility regression checks only; do not expand their release scope |

This file records the approved implementation requirements. `rr_findings.md` is
the baseline defect ledger; `rr_release_verifier.md` and the executable inventory
define evidence accounting. Passing a helper or mocked-host test is not a live
runtime or release approval.

## Ownership and published dependencies

- Gen1 Readiness owns reusable transport, JSON, sessions, journals, checked local
  storage, staged rules and shared executor primitives. Published handoffs:
  `654c7c7fb55e9465a493850d19346fee1aabb9f6` and
  `e1105928246761abe4124535643ffd655be2a208`.
- UI owns the Jinja/htmx board, detached additive projections, overlay components,
  named Broadcast sources and compatibility URLs. Minimal consumer agreement and
  HTTP hardening are published at `064b57cb5befc83c94bec4fc75a36e8e6bcd3f6d`, with
  scalar-compatibility follow-up `965cc12664b1c9b5ee27d8fc4a97a5cf06a6b065`.
- UI explicitly cleared independent RR context/native-storage work. The actual
  Phase3 projection producer and authoritative provenance/recovery fields are still
  a separate dependency for RR presentation integration.
- RR owns its admission binding, observations, execution/readback, native
  transactions, resources, exact-ROM data and cartridge evidence.

Implementation lives only in the isolated `codex/rr-foundation` worktree. Preserve
the root/UI and Gen1 worktrees. Recheck findings after each relevant handoff; reuse
the published implementation rather than copy unfinished working files.

## Architecture and shared invariants

Shared code owns semantic acquisition bookkeeping, duplicate resolution, durable
death obligations, logical identity migration, command lifecycle, paired recovery
and common presentation semantics. RR supplies verified signals, per-operation
prerequisites, codecs, native execution and physical receipts. Shared code must not
know RR addresses, native opcodes or packed layouts.

RR modules own context/admission, coherent party/PC snapshots, semantic detection,
storage, battle effects, local trade participation and presentation. A small
bootstrap/control service composes them. Sample coherent inputs once; modules do
not mutate each other's tables or independently infer command success.

Native modules separate engine/layout facts, mailbox lifecycle, party operations,
presence/resources, native UI/scenes and battle hooks. Keep this a small
freestanding library. Do not create a universal `is_safe` predicate or import Game
Boy checkpoint/ABI assumptions into RR.

Stable logical link/member identities are distinct from current PID/OT keys and
slots. Keep `mon.key` compatibility. Migrations carry old/new evidence; pending
obligations follow identity and ownership. Ambiguity or duplicate identity requires
reconciliation.

Persist all observations from a coherent frame, their stable IDs and the next
detector baseline atomically. Unreadable/borrowed snapshots do not advance the
real-party baseline. Shared `append_many` supplies this local publication boundary;
it does not imply a server semantic batch.

The server stages the rule transition/native transaction, atomically commits
state/event/both outboxes, then publishes. Delivery IDs, persistent semantic IDs,
native sequence numbers and native correlation tags are distinct. Native records
are serializable identity/phase/precondition/digest documents, not `LinkEntry`
object references. Validate physical receipts before durable acknowledgement.

Ghost/display telemetry remains transient, epoch-bound, coalesced and expiring.
Any telemetry-driven discovery that changes rules becomes a durable semantic
transition. Rendering and source retargeting never mutate runtime authority.

## Implementation stages

### 0. Evidence and isolated harness

Maintain a finding/case inventory bound to source/shared commits, ROM/patch/client/
data hashes, emulator/core/settings, fixture/save/mode/location prerequisites and
run ID. Every instance gets private config, copied immutable inputs, SaveRAM,
states, screenshots, logs and results. No newest-save selection, shared result
names, global process termination or autoloaded personal scripts.

Assert the production chain: game action -> semantic observation -> committed
decision -> partner command -> verified game result. Remove unconditional visual
PASS, disappearance-as-death and inject-both-sides propagation substitutes.

### 1. RR contract and native memory

Generate one authoritative reference/build manifest from exact inputs. Validate
actual mode flags and exact table/structure/hook boundaries. Keep uncertainty in
catalog aliases explicit.

The retained libc allocator metadata overlaps the current SLink arena. Attribute
legitimate readers/writers and instrument supported paths before declaring that
layout owned; zero observed writes is insufficient. Any actual conflict blocks
retaining the layout and requires verified relocation/reset behavior. Do not
expand into an unproven gap. Add permanent region/size/offset/hook and mutable
section build checks.

### 2. Admission, durable integration and recovery

Bind the shared sessions, local inbox/outbox, staged rules and journal to RR. Check
save ownership before HELLO/seeding/snapshots; classify an already-active borrowed
state, not only its edge. Verify exact build/mode after reconnect/reset/load.

Pause immediately on explicit disconnect/rejection/uncertain effect; default
wall-clock liveness deadline is two seconds. Networking, persistence and read-only
reconciliation must run while emulation is paused, preserving user-owned pauses.
Only both reconciled players may resume ordinary gameplay.

Reset/rewind revokes execution before restored native commands can run. Never
silently rewind durable rules. A known in-flight scene may use a bounded,
input-blocked, coordinator-authorized recovery procedure; otherwise remain paused
with an actionable reason. EWRAM tokens alone cannot implement the host reset/load
interlock because savestates restore those tokens too.

### 3. Native operations and storage

Version the bounded single-owner mailbox; expose immutable ROM build/capability/
layout evidence. Retain completion until consumed; retain each buffer lease until
its last reader ends. Prepare immutable native data without effects, persist the
intent, then submit. Recheck identity, context, count, bounds and vacancy at the
actual native apply point.

Deposit/memorial/withdraw success requires intended identity, source removal,
destination content, uniqueness, count and unchanged unrelated records. RR
withdrawal reconstructs fields according to its engine; raw100-byte equality is
not the storage oracle. Include guarded box-to-memorial transfers.

Timeout, contradictory readback or failure retains uncertainty. No blind second
mutation mechanism. Fresh execution requires proof the old attempt did not apply
and current prerequisites still hold.

### 4. Observations, rules and data

Use independent battle/acquisition contexts until resolution. Consume authoritative
faint evidence once across polling/ring/timer paths; retain unresolved deaths and
the living-state edge across cleanup/debounce; reconcile event-ring overflow and
borrowed-party transitions. A new battle cannot overwrite an earlier result.

Death has scheduling priority but cannot interrupt an armed native critical
section. Cancel conflicting trades before either party changes; after mutation
begins, verified forward recovery completes before death enforcement follows the
migrated identity.

Generate RR gender/types/permanent evolution families with explicit form aliases.
Preserve verified shiny classification. Separate logical rule areas from physical
map/floor/time/method/progression encounter tables; reject NONE entries and check
each probability table. Recognize walking/fishing/Surf/DexNav/raid/roaming/static,
gift/egg/fossil/daycare/NPC and identity/stat service sources explicitly. Keep the
approved rules; unresolved policy conflicts block that source rather than invent
automatic death/reroll behavior.

### 5. Trade, battles and native features

Use fresh paired preparation/reservation and actual native scene/evolution proof.
Remove watchdog-completed ownership and arbitrary same-token readback acceptance.
Keep Explosion's proven Lua mechanism with identity/context guards. Rival writes
belong to their originating battle and fresh verified partner snapshot.

Test every production native feature under contention and scene changes. Reserved
dormant opcodes need inertness/compatibility checks, not invented user flows.

### 6. Ghost/resources

Use initialized gfx16 templates and verified geometry/frame/animation/tile bounds.
Transfer/release palettes through RR's reference-counted allocator. Track OE,
sprite, tile, palette, callback, effect and collision ownership; C is the sole
render/resource writer. Publish complete desired snapshots, apply after spawn,
and handle palette/animation-only changes. Rebuild on scene return; never write
through stale non-field slots. Expire stale presence. Implement full run/bike/
surf/fishing transitions and effects. Exhaustion leaves no partial resources and
must never borrow another owner's palette.

### 7. Presentation and distribution

Consume the UI-owned frozen projection and preserve API/TCP/legacy URLs. Capability
dimensions `{supported,requested,ready,effective,reason}` are independent per player;
unknown is distinct from false and settings survive temporary unavailability.
Operation/recovery status remains separate.

Distinguish persistent identity from battle projection and observed data from
preparation estimates. Fix calculator execution/input/freshness, memorial styling,
encounter guidance and generated fingerprints. Named OBS sources independently
select runs/games, including scene rules; retargeting does not affect admission.

## Validation, migration and release

Both MGM pairings pass independently. Configuration tests cover all supported
toggle combinations; gameplay covers each feature, pairwise and high-risk combined
states. Required groups are foundation, admission/recovery, all25 boxes, battles,
every acquisition source, native features, ghost, presentation and distribution.

Timing cases vary documented frame/latency/batching/interrupt boundaries with at
least20 meaningful repetitions each; retain failures/seeds. Each MGM pairing needs
7200 active wall-clock seconds at normal speed with required action/resource
coverage. Accelerated tests supplement it. Complete paired campaigns through
credits and accessible RR postgame (Sevii, Cerulean Cave, rematches, scripted
acquisitions) on exact candidate artifacts. Visual ghost proof includes recordings
and resource assertions; missing captures fail.

Back up coherent run metadata, rules/memorial, journals, staged payloads, identities
and paired game checkpoints before atomic migration. Preserve history/keys and
refuse partial imports. Track live-RAM application separately from battery-save
persistence; test interruption before the next game save. Explicit rollback needs
coordinated game/server checkpoints, never a one-sided silent rewind.

Release requires all expected cases with no required skip/xfail/deselection/missing
assertion, all functional findings/policy gaps closed, no unexplained loss,
duplication, false death, divergence or corruption, proven native ownership and
paired recovery, shared compatibility, complete campaign/feature proof, reproducible
UPS and fingerprints, and a package-only startup test. Ship required runtime files,
LuaSocket, setup guide, manifest and UPS plus separate UPS asset; no ROMs.

Final deliverables: findings ledger, shared/RR contracts, generated reference/build
manifest, executable release verifier, immutable fixtures/replays/visual evidence,
migration/recovery guide and exact supported-runtime documentation.
