# F2: Polished active-faint identity and native-consumption settlement

**Design for review, not implementation or release authority.** Source cut:
`b2da827c98e8e91c8706fa88cf57452c92cf4bd8` (contains F1). This document changes
no runtime, capability, protocol or receipt. References below are to that cut;
re-pin line numbers before dispatch. F1 is MODEL-tested; native settlement is OPEN.

**Recommendation:** add a Polished-only optional settlement interface to the existing
Gen 2 client. A successful writer call starts observation; it does not complete a
KO. The strongest unresolved issue is PARTIAL: the existing death protocol has no
uncertain-operation acknowledgement or server hold, so client-only quarantine is
not an end-to-end solution. Production enablement must wait for that decision.

## 1. What exists and what F2 must not reinterpret

- The shared Gen 2 client queues `force_faint` and `force_explode` with the original
  command key, nickname and arrival order (`lua/gen2/client.lua:545-578`). It serves
  Crystal/Gold/Silver as well as Polished; this is not the Gen 1 or Gen 3 client.
- `find_party_slot` resolves exact keys, aliases and the existing death-specific
  evolution-stable identity fallback (`client.lua:465-495`). F2 must retain those
  rules rather than match a cached slot or species alone.
- Current `at_battle_hold` builds one battle snapshot, resolves each queued key,
  chooses Explosion for an unspent active USEMOVE, otherwise plain faint, and on
  any successful writer call immediately sets `commanded`, calls `mark_dead`,
  shows KO and queues an overworld re-zero (`client.lua:1570-1639`). That success
  branch is the behavior F2 must bypass for the opted-in composition.
- F1 requires `snapshot.key`, a fresh unique keyed party record, effective battle
  species agreement, the exec token, actual PC/bank, USEMOVE, no switch/deferred
  switch/Transform, and its remaining safety predicates
  (`lua/gen2/polished_explode.lua:195-220`,
  `lua/gen2/polished_writes.lua:194-282`). It writes six HP/status bytes and conditionally
  first-faint order last. It does not cancel committed actions or implement a bench faint.
- F1 already-zero success requires both HP/status mirrors settled; it does not
  reset native order. A post-attempt failure reports `PARTIAL ACTIVE FAINT:` with
  before/observed bytes; this is not a zero-write refusal
  (`polished_writes.lua:244-279`).

## 2. Local transaction and routing contract

The proposed optional composition field is `active_faint_settlement`; this name
is an internal design, **not an existing wire capability or server feature flag**.
Only `compose_polished` supplies it. No presence inference from generic
`battle_hold`, `battle_release_poll` or method-name existence is permitted.

For each owed command retain: original logical key, resolved physical key,
arrival id, client epoch, observed battle visit, selected slot, writer kind,
pre-write party/battle identity, pre-write HP/status/order/FAINTED flag, and
attempt/observation state. Use immutable copies, not the shared loop snapshot.
No server battle-instance token exists in this command shape; the local visit
must not be presented as a server-issued transaction id.

1. Resolve the command using `find_party_slot(w.key, w.cmd)` immediately inside
   the qualified hold. Keep `w.key` for the obligation and aliases. Put
   `snapshot.key = mon_key(mon)` for **the currently resolved physical record**,
   not blindly the old logical key. F1 compares this with fresh `reads.read_party()`
   (`client.lua:548,1577-1600`; `polished_explode.lua:198-219`).
2. Copy the battle snapshot per target before adding the key; retain slot, mode,
   action and link mode. An identity mismatch or missing/ambiguous target is
   PENDING, not permission to faint another slot. Re-resolve on a later hold.
3. Active `force_faint`: invoke F1 at the existing 0F:416A hook through the existing
   facade arm/call/disarm discipline. Never call it at frame end.
4. Active `force_explode`: only an eligible unattempted USEMOVE may use the existing
   Explosion writer. A writer return means **attempt staged**, not death or proof
   that the Explosion move executed. Retain the obligation and await an observation
   after that action before choosing fallback. Do not inject Explosion every hold.
5. A surviving blocked attempt may become a pending F1 plain faint at a subsequent
   qualified hold, within F1's existing restrictions. A missing observation is not
   evidence that an attempt failed or that it is safe to restage. Item/switch,
   Transform or other F1 refusals remain PENDING; F2 does not weaken F1 or fake USEMOVE.
6. Benched target: F1 does not apply. Preserve the current conservative handoff to
   the overworld path; immediate in-battle bench enforcement needs a separate
   writer/selection-race proof (`polished_explode.lua:193-194`;
   `client.lua:1607-1615,1643-1705`).
7. Out of battle: use the existing safe overworld faint, provided this obligation
   is still zero-write PENDING. Do not hand PARTIAL or awaiting-consumption work
   to ordinary `run_deferred` automatically (`client.lua:955-1024`).

### Outcomes and obligation ownership

| State | Required evidence | Client action | Existing server wire behavior |
|---|---|---|---|
| PENDING, not attempted | Named zero-write refusal or no qualified hold | Retain one obligation; retry at next eligible hold, or safe existing overworld route | No force-faint ACK/NACK exists; do not send one |
| PENDING, awaiting consumption | Writer returned success or an Explosion attempt was staged, without sufficient native witness | Freeze this obligation against repeated writes; collect bound observations | Normal truthful telemetry only; no invented success event |
| COMPLETE | Matching native-consumption evidence below, plus exact target readback | Retire local write obligation; emit KO once; install completed-death/revival protection once | Continue ordinary `tick`/`safe` party telemetry; **no new completion ACK** |
| PARTIAL | F1 attempted-write error, unreadable post-attempt state, or uncertain lifecycle loss after an attempt | Preserve evidence and obligation; no blind retry, overworld re-zero, conflicting memorial/box write, or completed KO claim | Existing protocol cannot declare/hold this uncertainty; shared-protocol decision required |

The distinction between PENDING sub-states is necessary: treating successful
F1 as a retryable refusal would repeatedly enter the writer while native code is
still processing it. Already-zero F1 success also awaits a bound native observation;
it must not fabricate a fresh animation or reset native order.

`commanded` currently suppresses an echo of a commanded faint
(`client.lua:1268-1275`), whereas `mark_dead` populates local revival protection
(`943-952`). Separate **echo suppression** from **completion** in the opted-in path:
record suppression for the exact owed physical identity/epoch before a possible
native callback, but only show KO and install completed-state re-zero policy after
COMPLETE. This does not make the server's already-DEAD link ALIVE again.
Keep unsolicited natural faint reporting unchanged. Clear only the bound
suppression at settlement/boundary, not a later unrelated faint of a reused key.

## 3. What the server already understands

`docs/protocol.md` section 5 command rows (`349-350`) specifies no ACK/NACK for
`force_faint`/`force_explode`: the server already marked the link dead. Section 9
assertion 25 (`666`) forbids a `faint{key}` echo for client-zeroed HP; assertions
33-34 (`680-681`) describe enforcement/fallback. Do not send a new natural
`faint` event as a command receipt. Do not reuse `sync_retrieve_done`,
`box_mon_failed`, `trade_done`, or `awaiting_save` for faint settlement.

The existing evidence message is an ordinary
`tick{party:[{key,hp,...}],in_battle:...}` or the existing qualified `safe` event,
using the real wire projection and cadence (`client.lua:1443-1472`; protocol
section 4 and assertion 14). Do not emit `safe` while still battling, synthesize
HP0 on the wire, send `party:[]` to represent uncertainty, or suppress truthful
HP merely to prevent the server observing an intermediate value.

`SoulLinkState._arm_inflight` records death delivery in `death_inflight`, separately
from sync commands (`server/state.py:3502-3508`). `_ack_inflight` removes sync
entries only (`3510-3514`); sending any keyed event is not death completion.
`_repair_lost_faints` uses actual party HP to clear incident budget/stalled state
at HP<=0 and otherwise reissues bounded plain `force_faint` for dead living party
members (`3549-3612`). Death inflight/cooldown ages only outside battle
(`3569-3583`). This is eventual repair, not confirmation that native faint
animation/copyback ran. It cannot repair a boxed absent key (`3555-3557`).

**Protocol blocker for PARTIAL:** local duplicate suppression can prevent this
client retrying blindly, but cannot inform State that its repair/rebuild/memorial
commands must be held. F1 can have partially zeroed party HP, so server telemetry
may already look successful. A server-visible uncertainty/hold/disposition
contract would be a **new shared-protocol change**, needing owner GO, operation
identity/replay semantics, State handling and Gen 3-first regression. Its event
name/schema is **UNVERIFIED / deliberately not invented by F2-DESIGN**. The proposed
box-write contract does not currently authorize reusing its events for faints.
Until approved, F2 can be MODEL-tested but cannot claim end-to-end partial recovery
or justify enabling a production capability.

## 4. Settlement observation: before is not after

The actual generated `battle_faint` anchor is **0F:44C8**, instruction `E0 D1`,
phase `before_party_copyback`, source-candidate/physical OPEN
(`data/games/polished_crystal/engine_signals.json:127-146`). **0F:44CA** is the
following `CALL UpdateBattleMonInParty`, the separate `battle_faint_copyback_call`
entry (`149-173`). Neither is a post-copy witness. The site fires on ordinary
ResolveFaints passes too; firing alone is never faint evidence.

Current Polished binding records `{battle={slot,hp,max_hp,mode,link_mode}}` at the
pre-copy boundary (`lua/gen2/signals.lua:1467-1476`), as `kind="observation"`.
It does **not** emit the vanilla `kind="faint"` consumed by `settle_faints`.
The event lacks a target key, sample frame, native FAINTED bit and per-attempt
sequence (`signals.lua:1438-1443`); batch generation/operation metadata exists
outside it (`1432-1435`). `client.on_observation` currently has no settlement
branch for it (`client.lua:1193-1255`).

F1 itself writes both HP mirrors. Therefore pre-copy battle HP0 plus a later
party HP0 does **not** prove the copy instruction executed. F0's tests prove
native instruction behavior, not a live observation of its execution
(`tests/unit/test_polished_plain_faint_engine.py`, branch/copyback groups).

Proposed strong COMPLETE witness, all bound to the same epoch/visit/physical key:

1. Save the attempt baseline before mutation; record native player FAINTED bit
   (SUBSTATUS2 bit2), active slot and first-faint order. F1 never sets FAINTED.
2. Observe the pre-copy boundary after this attempt with battle HP/status zero
   and matching active physical identity. Record a monotonically increasing
   capture sequence, not only frame number (callbacks can share a frame).
3. Observe return from the native player copyback: candidate 0F:44CD, immediately
   after the call at 44CA and before enemy copyback. Derive this from the pinned
   three-byte CALL and verify next instruction/ROM binding; do not silently
   hardcode a new production-authorized site. At this point require native player
   FAINTED bit set, actual battle HP/status zero and exact target party HP/status
   zero, matching slot/key and fresh readback. For an already-fainted idempotent
   case, require this new bound execution witness without demanding a new flag edge.
4. A last-mon LostBattle/battle-end/whiteout observation may corroborate the path,
   but does not authorize a whole-party wipe or bypass the identity requirement.
   Loss and simultaneous-faint semantics stay native.

These observations support **native faint handling and copyback reached**, not
proof of visible animation, exact screen/audio completion, durable save, or
that Explosion itself executed. A nonzero native FAINTED bit could predate this
attempt; the paired execution/identity witness is still required.

**UNVERIFIED:** the new after-call observer, callback PC semantics, same-frame
batch propagation and maximum delay before the witness. A deadline diagnoses
missing evidence; it never converts it into COMPLETE or safe-to-retry.
If this observer cannot fit the bounded file contract, dispatch its source/pin
card first rather than weaken COMPLETE to pre-copy HP0.

## 5. Exact implementation touch list and isolation argument

All following edits are proposals for a later code lease; none are made here.

| File / current lines | Required change | Legacy isolation |
|---|---|---|
| `lua/gen2/client.lua:117-138` | Optional settlement state, outstanding obligations and sample sequence | Allocate/use only when `p.active_faint_settlement` exists |
| `client.lua:545-578` | Deduplicate owed physical/logical identity; suppress obsolete “no active faint” HUD only for capable path | Existing receipt/queue branch remains default |
| `client.lua:1497-1506,1570-1639` | Preserve hook entry/leave and disarm; copy snapshot per command with resolved physical key; route opted-in attempt/settlement instead of generic `landed` KO branch | No alteration to vanilla writer APIs, action selection or byte order |
| `client.lua:1193-1255,1258-1302,1855-1861` | Route validated observations and bound sequence to optional settlement handler; preserve natural events | No Polished interpretation of vanilla event batches |
| `client.lua:943-1024,1234-1239,1696-1705` | Exclude awaiting-consumption/PARTIAL from generic deferred re-zero and battle-exit handoff; allow ordinary zero-write pending handoff | Legacy queues/settle logic unchanged when capability absent |
| `client.lua:1064-1160` | Refuse to execute a conflicting box/retrieve/memorial operation on a locally unresolved target; retain intent rather than emitting a misleading completion/failure | Guard only the opted-in unresolved identity; do not change ordinary box return contracts |
| `client.lua:383-418,1917-1921` | Invalidate witness epochs/remove hooks; retain uncertainty across boundary rather than silently retrying attempted work | Existing reset/rebaseline behavior remains default |
| `lua/gen2/entry.lua:824-846,919-947` | Compose optional Polished observer/settlement object and pass it to Client.new, using admitted ROM/data and existing authority/registry | Only `compose_polished`; vanilla composition at `633-677` untouched |
| `lua/gen2/polished_explode.lua:98-149,195-220,232-240` | Expose optional F1 result classification/read-only identity evidence and observer lifecycle without a second writer; keep strict F1 guards | Polished-specific facade; do not change vanilla `writes.lua` |

The existing Polished facade can expose the read-only observer with the same
registry/authority primitives used by composition; it must pin the copyback call
and proposed after-call site and preserve observation provenance. Do not register
an unbound raw callback simply to stay under three files.

If using the existing signal batch rather than a facade-owned observer, additional
owned edits to `lua/gen2/signals.lua:1432-1443,1467-1476` are needed to preserve
capture sequence/key/native-flag/epoch evidence; adding a generated site also
requires `tools/gen_polished_engine_sites.py` and its generated pack. Those are
**separate explicitly leased cards**, not implicit authority in a client/entry
card. The precise final observer file split is UNVERIFIED pending source review.

“Legacy unchanged” means equal observable event/write/queue behavior, not that
edited shared files have identical bytes. Never branch on game name inside the
shared client: branch on the optional facade interface supplied only by Polished.
The three Lua runtime files above stale Gen 2 CODE_DIGEST
(`tools/gen2_code_digest.py:26-47`); this Markdown file does not.
If a State/protocol extension is approved, verify Gen 3 first and then other
generations, and run the full affected suites; `-k` subsets alone are not a
complete shared regression. The existing contract records that shared-code
requirement (`docs/polished/BOX_WRITE_CONTRACT.md:4-6`).

## 6. MODEL tests and red controls

Use the composed Polished Rig/facade with the real overlay image and existing
SM83 engine oracles; do not mock a writer into returning desired completion.

1. Physical key propagation, including an authorized death alias: command logical
   key retained, F1 receives fresh physical key/slot. Red: pass old command key or
   reuse one loop snapshot for two targets; require wrong-key zero-write refusal.
2. Successful F1 -> awaiting consumption, no KO/no generic re-zero. Red: reuse
   current `landed` branch at `1618`; fail the early-completion assertion.
3. Ordered pre/after-copy witnesses -> one COMPLETE and one KO; duplicate samples
   and duplicate commands do not repeat writes. Red: accept site firing/party HP0
   alone, wrong slot/key, old epoch, out-of-order sequence, missing native flag.
4. Zero-write F1 refusal remains one pending obligation; later valid hold can
   retry. Red: drop it, show KO, or broaden USEITEM/switch/Transform guards.
5. Fault after each F1 emitted byte: PARTIAL preserves exact observations; no
   second write on repeated hold, duplicate server repair, battle exit, reset,
   or generic revival/deferred loop. Red: fall through into `keep` retry or
   checkpoint handoff. Reset disposition itself remains an explicit OPEN policy.
6. Explosion attempt can survive (Damp/status/target absent); no completed death
   until a bound faint witness. Red: writer-return-as-KO; missing witness never
   authorizes a fresh attempt. Test allowed plain-faint fallback separately.
7. Commanded echo suppressed without losing unrelated natural `faint`; natural
   `whiteout` behavior unchanged. Red: use one unscoped suppression flag, or emit
   `faint` as the command ACK. Never invent a forced whiteout event.
8. Real State round-trip of emitted tick/safe data: existing death repair/inflight
   semantics and partner queues observed after each event, not only final state.
   For PARTIAL, demonstrate the current protocol gap; an unimplemented hold
   must not be mocked and reported as solved.
9. Vanilla Crystal/Gold/Silver compositions omit the optional field. Replay
   force_faint/force_explode, item/switch, bench, echo, reset and overworld paths;
   compare write logs, messages and queue state to the baseline. Red: enable the
   new branch without capability. No edits to vanilla executor required.

## 7. F3 live matrix and decisions

F3 requires a granted emulator lane, pinned ROM/profile/fixture and normal
scripted inputs. A historical SYNTH fixture is not fresh authorization to stage
trainer/story/battle data. Trainer fixture/route readiness is OPEN in
`docs/polished/EXPLODE_RIVAL.md` (implemented/review and landing-swap discussion).

Required cases: ordinary wild and trainer free-action active faint; both move
orders; status-bearing active; first-faint orders 0/1/2; already-zero replay;
opponent simultaneous faint; last living mon and native loss; Explosion succeeds
versus Damp/sleep/freeze/paralysis/Disable/obedience/absent-target survival;
committed item/switch (must remain pending under current F1); Transform including
same-species (must refuse); bench/switch-selection race (no unsupported F1 write);
party/battle copyback and callback ordering; repeated server command; disconnect,
battle end, reset/reload before/after writer/observer; partial-write fault only
under a separately approved fault-injection lane. Record actual native FAINTED
transition, copyback return, slot identity and movement/whiteout outcome.

Owner decisions blocking production:

- Explode scope: attempted eligible active Explosion plus guaranteed fallback,
  versus universal visible Explosion; current F1 cannot enforce every action.
  `EXPLODE_SCOPE.md:6-31` keeps these claims separate and requires a ruling.
- PARTIAL server-visible hold/disposition and reset behavior; no event currently
  expresses it. Owner GO precedes any shared-protocol implementation.
- `supports_explode_mode()` flip is separate, evidence-gated authority; it remains
  false (`server/adapters/gen2_polished.py:751-754`). Internal settlement
  capability is not that release/support flag. No decision is taken here.

## 8. Three most dangerous open questions

1. Can the frozen after-copy/native-FAINTED witness distinguish native consumption
   from F1's own zero writes and stale same-frame/previous-visit events?
2. What approved server/client lifecycle holds a PARTIAL target across repair,
   memorial, reconnect and reset without blindly retrying or faking telemetry?
3. Which unsupported switch/item/Transform/bench outcomes must be covered before
   the owner considers the death-enforcement/Explode capability truthful?

No runtime implementation, test execution, physical proof, or independent approval
is supplied by this document. Next action: coordinator review and explicit observer
and protocol scope decisions, then bounded implementation leases and F3 evidence.
