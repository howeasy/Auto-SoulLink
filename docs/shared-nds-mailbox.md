# Shared NDS mailbox reader and Gen 4 title binder

SOURCE/MODEL contract, 2026-10-04. Implementation: `lua/nds/mailbox.lua` (introduced by
`5edae113`) and `lua/gen4/companion.lua` (`4b776cd4`, corrected by the OMP review fix commit
`b1060c78`), on `claude/gen4-integration2`. Line anchors below are given as symbols, not
numbers, because they moved once already. The sibling
`docs/shared-nds-witness.md` owns revision-protected transaction witness reads;
this reader does not replace that protocol.

## Shared API

```lua
local Mailbox = supplied_mailbox_module
local reader, why = Mailbox.new(io, {base = title_arena_base, abi = 3})
if not reader then return nil, why end
local header, reason = reader:header()
local snapshot, reason = reader:snapshot()
local title_bytes, reason = reader:region(title_offset, 0x40)
local layout = Mailbox.layout()
```

Every address is caller supplied or derived from the compiled layout. API/source
citations below refer to the side branch: `lua/nds/mailbox.lua:61,89-187`.

| Entry | Result / scope |
|---|---|
| `new(io, config)` | reader or nil plus reason; explicit bounded u32 base and ABI exactly 3; optional layout must match every key/value in both directions (:89-104) |
| `layout()` | fresh copy of the compiled ABI constants/offsets (:61); modifying it does not retarget a reader |
| `reader:header()` | one six-scalar envelope sample; signature/ABI/phase checks; no payload copy or coherence claim (:159-167) |
| `reader:snapshot()` | `{abi, envelope, bytes}`: mailbox bytes plus the accepted after-envelope; double-sample rule below (:146-157,169-174) |
| `reader:region(offset, length)` | raw dense byte copy inside the arena; nonzero length and bounded range; no interpretation or coherence protocol (:177-185) |

`io` is a plain table of injected functions/userdata callables. Calls carry **NO domain
argument or implicit self**. The binder closes the functions over the actual shared
window; for Gen 4 use Instruction TCM, never an ARM9 mirror (§6 of C2_BEACON_SPEC).
A virtual/domain-relative address conversion, if needed, is the title/platform binder's
responsibility. The module cannot choose a memory domain.

- Supply `read_bytes(address,n)` returning exactly n bytes as a binary string or a
  dense 1-based byte table, or `read_u8(address)` (:64-80,109-129).
- Optional `read_u16/read_u32(address)` supply those widths. Missing widths are
  composed from bytes; u32 is never substituted for u16. Signed int32 u32 values
  normalize to unsigned (:119-128).
- Callback references and config/layout values are captured/copied. Throwing,
  sparse, short or malformed reads refuse with `read:error`, not fabricated zeros.
- Stable reasons include `config:base`, `abi:unsupported`, `config:layout`,
  `config:reader`, `mailbox:signature`, `abi:mismatch`, `mailbox:phase`,
  `mailbox:changed`, `region:range`, `read:error`. API calls return value/nil plus
  nil/reason consistently. There is no write, clock, emulator API or transaction state.

## Envelope consistency boundary

The six scalars are signature, ABI version, capabilities, session_epoch,
producer_phase (`phase`) and the +0x4C `reserved` word (:130-145). Snapshot reads
those scalars, copies 80 mailbox bytes, and samples those six again. Any difference
refuses as `mailbox:changed` (:146-156). Header alone does not do this comparison.

This proves only a software-visible equality check around a copy. It establishes
neither hardware memory ordering nor atomic publication and **does not rule out ABA**
(a word may change and change back). It does not prove stable opcode/sequence/status/
ack/reason/args/result or the copied payload: those bytes are outside the six-scalar
claim, and their transaction binding remains the caller/writer's protocol. There is
no mailbox revision counter. Use the separate native witness reader where a revision
and expected transaction identity are required.

Capabilities are informational. Bits 0..6 appear as `caps_shared`; unknown shared
bits 7..15 are reported non-fatally as `reserved_bits`; title bits 16..31 remain
opaque in the full word. A capability word of zero is valid. It is never a shared
liveness/acceptance gate. The +0x4C word is **title-private opaque data**, not a shared
generation interpretation. Shared `region()` may copy the title block without
interpreting any field.

MODEL anchors: `tests/unit/test_nds_mailbox.py:248-291` (compiled layout and I/O),
`:372-409` (changed envelope, payload outside claim, informational capabilities),
`:411-449` (raw regions/bounds), `:495-556` (named faults/config copying),
`:586-617` (revert controls). Reading tests is not a PHYSICAL qualification.

## Gen 4 title adapter

`lua/gen4/companion.lua` supplies title decoding and liveness:

```lua
local binder, why = Companion.new(io, {
    mailbox = Mailbox, base = title_arena_base,
    stable_polls = measured_K, stall_polls = measured_N,
})
local state, reason = binder:poll(previous)
-- Caller owns previous and any outstanding-request cancellation.
previous = state
-- Pure reducer alternative: Companion.step(previous, decoded_sample, options)
```

- `Companion.layout()` copies static title layout; `binder:layout()` adds the
  shared-derived title offset, masks and chosen thresholds.
- `new()` validates config; title offset is derived from the shared reader's
  `reserved_offset`, not a hard-coded address.
- `poll(previous)` takes the shared snapshot, two full 0x40-byte title copies around
  a fresh header read, compares the copies, validates magic/version/size, and checks
  title generation equals the Gen 4 interpretation of +0x4C. NOTE: `state.generation` IS the
  +0x4C word (Gen 4's session epoch, abi.h / beacon.h `generation`); `state.session_epoch`
  is the +0x44 envelope word, copied out and never gated -- bind a transaction to the former.
- `step(previous,sample,opts)` is a pure liveness transition: first sample
  WARMING; cookie/generation change or refused sample LOST; N unadvanced-delta polls
  LOST; LIVE requires stable pair and a delta advance on the current poll. K=1 still
  requires an observed advance, not first-attach LIVE. `stable` saturates at 0xFFFF. OPEN
  DESIGN CALL (ABI/owner): a stall shorter than N is TOLERATED -- `stable` is kept and only
  `stalled` moves, so a skipped service visit does not flap LIVE; the spec's "K consecutive
  polls" does not define that case. `producer_phase` is reported, not gated (spec 6.2 item 5).
- Refusal reasons returned by `poll` (state is LOST, `reason` set): `config`, `config:mailbox`,
  `config:polls`, `title:magic`, `title:version`, `title:size`, `title:coherence` (copies
  differ or generation mirror differs), the shared reader's `mailbox:*`/`abi:*`/`read:error`,
  and `sample:absent` / `sample:fields` from `step`.
- K/N are **per title**. Defaults 3/2 (`Companion.DEFAULTS`) are MODEL fallbacks, not measured shipping
  thresholds. Caller-supplied valid values win; neither value belongs in the shared
  mailbox reader. The module has no clock or internal transaction retention.
- Capability bits and title headroom are reported but never gate step/poll liveness.
  The reserved[36] tail has no invented private cells.

MODEL anchors (by test name, `tests/unit/test_gen4_companion.py`):
`test_layout_is_the_compiled_header_and_title_offset_is_derived`, `test_field_offsets_follow_beacon_h`,
`test_poll_decodes_every_published_field`, `test_first_poll_is_warming_and_live_lands_after_exactly_k_polls`,
`test_a_stalled_clock_for_n_polls_is_lost_and_resumes_from_warming`,
`test_a_refused_poll_drops_liveness_and_the_next_good_poll_rewarms`, `test_refusals_are_named`,
`test_a_torn_title_is_refused_rather_than_decoded`, `test_capabilities_never_gate_liveness`,
`test_step_is_pure_and_usable_without_a_binder`, `test_stable_saturates_instead_of_wrapping_and_dropping_live`,
and the publish-order / revert controls at the end of the file.

## ABI-owner rulings, 2026-10-04

Recorded from the coordinator's Gen 5 handoff; implementation responsibility stays
with the ABI owner (see the companion/G3a decision note):

1. Raw `region()` copy is allowed; shared code must not interpret title fields.
2. +0x4C stays a title-private opaque word; `live()` and K/N belong to each title.
3. Unknown shared capabilities 7..15 are non-fatal `reserved_bits` observations.
4. A writer is a separate `lua/nds/mailbox_writer.lua`, not a write method added to
   this reader. That name records the ownership decision, not a delivered writer.
5. NEW reader modules may precede Gen 4 live checks; edits to existing shared modules
   and the larger reviewed Gen 5 stack land in the batched window. These Lua files
   are inside the Gen 4 evidence surface even when outside the Gen 2 digest scope.

PHYSICAL remains OPEN: matching domain/window, actual service cadence/New Game K/N,
canary, native durability and cold reload. Coherent reads/caps cannot authorize writes.
