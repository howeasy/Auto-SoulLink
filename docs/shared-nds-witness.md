# Shared native trade witness reader (NDS-5)

`lua/nds/native_witness.lua` reads the common trade witness for **ABI 2 (Gen 3)**
and **ABI 3 (shared NDS)**. It has no emulator API, module loading, writes,
networking, clock, or retained transaction state. The binder supplies the mailbox
address, explicit ABI, reads, and expected transaction identity. No existing
Gen 3 reader or per-game binder is modified or automatically rebound by this card.

This is a SOURCE/MODEL contract. A native save milestone is a producer claim;
the reader cannot establish that flash was written, that an emulator flushed its
save file, or that the received record survives an independent cold reload.

## API and injected reads

```lua
local reader, why = NativeWitness.new(io, {
    base = profile.native.mailbox_base,
    abi = profile.native.abi, -- exactly 2 or 3; unknown versions refuse
    -- layout = generated_layout, -- optional; must match the compiled ABI
})
if not reader then return nil, why end

local expected = {
    epoch = session_epoch, visit = visit_id,
    pid = outgoing_pid, otid = outgoing_otid,
    opaque = token_bytes, -- exactly 16 bytes, dense 1-based table or binary string
    prepare_seq = prepare_seq, scene_seq = scene_seq,
    incoming = {pid = incoming_pid, otid = incoming_otid}, -- optional until post-save
    seen = previously_accepted_milestone_bits,
}
local snapshot, reason = reader.read(expected, expected_final_command_seq)
if snapshot then
    expected.seen = snapshot.bits -- caller, not the reader, owns monotonic state
else
    local risk = NativeWitness.classify(nil, expected.seen)
    -- Latch/report the reason. UNCERTAIN must not become UNCHANGED or a blind retry.
end
```

I/O uses plain functions (no implicit `self`) in a plain table:

- Readers must be Lua functions or userdata callables (EmuHawk `memory.*` are
  userdata); other types are refused at construction as `config:reader`.
- Read cost per `read()`: 11 calls with `read_bytes` (with or without
  `read_u16`/`read_u32`; `read_u8` is then never used) and 112 calls with
  `read_u8` only (28 mailbox bytes, 4 revision bytes, 80 witness bytes).
- `read_bytes(address, length)` returns a dense 1-based byte table or a binary Lua
  string of exactly that length; **or** `read_u8(address)` supplies each byte.
- Optional `read_u16(address)` and `read_u32(address)` provide scalar reads. When
  absent, the reader composes that width from bytes. It never substitutes a u32
  callback for a missing u16 callback.
- Bytes and u16 results are unsigned integers. u32 also accepts signed int32
  representations and normalizes them to unsigned values.

The mailbox base is explicit and bounded to a 32-bit address range. Callback
references and layout are captured/copied at construction; later changes to the
configuration table do not retarget an existing reader. A throwing/unreadable,
short, sparse or malformed read becomes `nil, "read:error"`. No read refusal is a
bare nil. The APIs return two values consistently: object/snapshot or nil, then
nil on success or a stable reason string on failure. No transaction context is
mutated, including on partial reads or failed validation.

`NativeWitness.layout()` returns a fresh plain table. Its offsets, sizes, enum
values and masks were emitted by a host-C `offsetof`/`sizeof` probe against
`patch/src/nds/common/abi.h`. The integration test recompiles that probe and
compares **every table entry**; a separate translation unit checks the Gen 3 ABI
layout too. This prevents a copied comment or a Lua constant from silently
becoming the layout oracle. An optional supplied layout must match the supported
ABI exactly; arbitrary geometry overrides are refused.

## Coherent snapshot and binding rules

The reader samples mailbox signature/ABI/epoch/producer phase, then reads:

1. Witness revision (u16).
2. All `sizeof(SlinkTradeWitnessV2)` bytes into a private byte snapshot.
3. Revision again (u16).
4. Mailbox signature/ABI/epoch/producer phase again.

Both revision reads and the revision in the copy must agree, be nonzero and even.
Exactly four mailbox scalars (signature, abi_version, session_epoch,
producer_phase) are sampled before and after and must be identical; nothing else
in the mailbox is compared. Its ABI must equal the binder's explicit ABI and its
epoch must match the expected transaction. **Capabilities (mailbox +0x40, flag
`SLINK_CAP_DURABLE_TRADE` = 1) are deliberately NOT checked by this reader**, so a
binder must keep its own capability/admission gate (Gen 3 gates on it at
`lua/gen3/native.lua` ~481-488); a test pins that a capabilities change does not
affect acceptance.
This extends the Gen 3 reader's revision check with an envelope-change refusal;
it does not establish hardware memory ordering or eliminate revision-counter ABA.
Binders must preserve the existing paused-CPU/read-window assumption.

The snapshot must match epoch, visit, old PID/OTID and all 16 opaque token bytes.
The token must be nonzero and must come from the caller's server-token/visit
mapping; the reader does not derive it from a Pokémon identity. Mon identity
interpretation/decoding belongs to the binder, not this module.

Rules carried from `lua/gen3/native.lua:613-654`:

- Milestones use only bits 0–4; visit flags only bits 0–1; result is 0–3.
- Previously observed milestone bits cannot disappear.
- COMMIT_ENTERED requires PRE_SAVE_OK, scene/evolution requires commit, and
  POST_SAVE_OK requires scene/evolution.
- FINAL_RESULT is present exactly when the result is nonzero.
- PRE_SAVE_OK requires both visit acceptance and pre-save consent.
- Each set milestone has the caller's expected sequence: prepare for milestone
  0, scene for milestones 1–3, and the explicit final-command sequence for
  milestone 4. An unchanged withdrawal can therefore have a different final
  sequence. Missing expectations fail closed. Unset milestone slots are not proof.
- A COMMITTED witness is accepted only when the caller's `final_seq` equals
  `scene_seq`: milestone 4 is bound to `final_seq` while `success` binds milestones
  2-5 to `scene_seq` (same as the C `slink_trade_success_is_durable`). A differing
  or nil `final_seq` is refused as `sequence:milestone` (the milestone binding fires
  first; `success:sequence` is defence in depth). UNCHANGED/UNCERTAIN rows may carry
  another final sequence.
- COMMITTED/UNCHANGED requires native DONE; UNCERTAIN requires native UNCERTAIN.
- POST_SAVE_OK requires SAVE_OK and the expected received PID/OTID.
- COMMITTED requires all five milestones, both flags, SAVE_OK and received
  identity. The shared reader additionally applies the C success predicate's
  scene-sequence requirement to a claimed COMMITTED outcome.
- UNCHANGED cannot carry commit/evolution/post-save bits.
- Milestone frame values are diagnostic only; they are never used as timeouts.

Prepare/scene/final sequences can be absent before their milestone is needed.
Epoch and visit must be nonzero; expected identities are unsigned u32 (zero PID
is not silently treated as invalid). Input/shape errors have `context:*` reasons.

## ABI-gated save status

| Witness condition | ABI 2 | ABI 3 |
|---|---|---|
| Before PRE_SAVE_OK | Legacy Gen 3 save-field acceptance retained | Only 0, OK=1, PENDING=2, FAILED=255 |
| PRE_SAVE_OK set | Save status must be OK=1 or FAILED=255 | Also accepts PENDING=2 subject to the next rule |
| PENDING with POST_SAVE_OK (bit 8) or FINAL_RESULT (bit 16) | PRE_SAVE_OK already rejects PENDING; other pre-save behavior stays legacy-compatible | Always refused: `abi:pending_final` |
| POST_SAVE_OK or a claimed COMMITTED result | Requires OK=1 and the bound received identity | Same |
| Unsupported or mismatched ABI | Refused | Refused; no speculative ABI-4/“all future versions” acceptance |

`snapshot.pending` means the trade RESULT is PENDING (`SLINK_TRADE_PENDING`, result
0), not that a save is in flight; the ABI-3 `saved == 2` state has no dedicated
snapshot field (read `snapshot.saved`).

ABI-3 pending is an ordinary readable state, not read corruption. In particular,
real producer polls with bits=7, result=0, saved=2 return a complete snapshot with
`pending=true` and `durable_success=false`. They cannot publish success merely
because `post_save_begin()` ran. A PENDING value with a final-result bit is
corrupt even when PRE_SAVE_OK is absent: this is checked independently.

## Success and reconciliation classification

```lua
local ok, why = NativeWitness.success(snapshot, prepare_seq, scene_seq,
                                     expected_received_pid, expected_received_otid)
local classification, why = NativeWitness.classify(snapshot, previously_seen_bits)
```

`success` mirrors `slink_trade_success_is_durable`: prepare sequence on the first
milestone, scene sequence on the other four, COMMITTED, both consent flags, all
five bits, SAVE_OK and matching received identity. It recomputes these conditions;
it does not trust the snapshot's convenience `durable_success` field. False
results include a nonempty `success:*` reason. A successful result is a structural
native receipt, not independently established physical durability.

`classify` is a **reconciliation-risk classification**, not a command to stop an
in-flight save or a replacement for the numeric native phase/result. Supply an
accepted, unmodified snapshot (or nil after a refused read), and retain `seen`
from the same transaction only:

| Evidence | Classification |
|---|---|
| Accepted snapshot with proven structural success | `COMMITTED` |
| COMMIT_ENTERED already observed, without proven success | `UNCERTAIN` |
| Native terminal UNCERTAIN, even when the commit marker is missing | `UNCERTAIN` |
| Accepted native UNCHANGED, with no prior commit | `UNCHANGED` |
| Accepted pre-commit nonterminal snapshot | `PENDING` |
| No readable snapshot and no known commit | `UNKNOWN` |

Thus a legitimate asynchronous save can have `pending=true`, numeric SCENE
phase, and reconciliation classification UNCERTAIN simultaneously: continue
normal polling, but an interruption cannot be reported as an unchanged trade.
The classification helper consumes the accepted snapshot's structural-success
annotation; it is not a validator for fabricated/mutated tables. Never replay an
irreversible operation based on a read failure. This reader owns no watchdog;
the C producer and the caller's host transaction controller own their bounds.

Snapshot fields include `abi`, `revision`, `phase`, `epoch`, `visit`, `old_pid`,
`old_otid`, `bits`, `flags`, `result`, `saved`, `received_pid`, `received_otid`,
`token`, `milestone_seq` and `milestone_frame` (both 1-based five-element arrays),
plus `pending`, `durable_success` and `classification`.

Reason categories are `config:*`, `context:*`, `abi:*`, `mailbox:*`,
`snapshot:*`, `identity:*`, `witness:*` (e.g. `witness:range`), `milestones:*`,
`sequence:*`, `phase:*`, `result:*`, `success:*` and `read:*`. Binding code must surface and retain these failures;
it must not silently reinterpret nil as an idle/nonexistent transaction.

## Tests and limits

```text
python -m pytest tests/unit/test_nds_native_witness.py -q -rs -p no:cacheprovider
```

The test compiles a host harness including the actual committed NDS-2
`trade_producer.h`, reference PK4/PK5 record bindings and C success predicate. A
simulated engine drives prepare, consent, scene/commit, multiple asynchronous
PENDING polls, success, save failure, watchdog timeout, stale epoch, pre-save
refusal and withdrawal. Every service call dumps the actual mailbox/witness
bytes. Lupa runs the Lua reader against each dump and compares structural success
with C. The fake record decoder is deliberately not a PK4/PK5 crypto oracle.

Two in-memory reader mutations are required to fail the behavioral assertions:
removing PENDING acceptance rejects legitimate producer snapshots; removing the
bit-8/16 restriction accepts a corrupted final refusal. The mutation tests count
behavioral assertion failures, not syntax errors or a missing compiler. Tests
also execute the actual Gen 3 reader function in isolation with injected boundary
dependencies to compare ABI-2 save-status acceptance/refusal.

The harness also drives producer states the main trace does not reach: mode 6 (scene
poll fails before COMMIT_ENTERED: bits 17, result 3, accepted, UNCERTAIN decided by
the result clause), mode 7 (`slink_trade_commit_entered` refused for a different
slot -> `cancel_scene`: bits 17, result 2, accepted, UNCHANGED, which keeps the
`(bits & 14) == 0` gate non-vacuous) and mode 8 (foreign `received_key` after the
commit marker: bits 19, UNCERTAIN). A `received_key` refusal cannot produce bits 17
because the producer only calls it once COMMIT_ENTERED is set.

Compiler discovery matches the NDS-2 test contract: `SLINK_HOST_GCC`, PATH gcc,
then `.cache/build-tools` in this worktree and the git-common-dir checkout.
Absence reports `NDS_WITNESS_HOST_CC_ABSENT`; `SLINK_REQUIRE_HOST_CC=1` turns it
into a failure. Compiler errors never skip. Lupa is required, not auto-installed.

Unverified: ARM code generation, volatile access ordering/cache coherence,
real-time pause/read atomicity, game-specific native save completion, flash/save
file durability, real epoch/visit/token issuance, runtime capability/admission
gates and per-game binder integration. This card neither edits Gen 3's existing
reader nor repairs older README statements claiming that no shared reader exists.
