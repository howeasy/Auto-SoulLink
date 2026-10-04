# NDS shared companion stack (card NDS-2)

Platform-neutral lift of the Gen 3 native companion ABI and producer state
machines (`patch/src/trade_targets/`), with **record bindings** so the same
lifecycle serves Gen 3 PK3, Gen 4 PK4 and Gen 5 PK5. Header-only, plain C11,
host-falsifiable (`tests/unit/test_nds_common_producers.py`). Nothing here is an
admission or qualification claim; no title, address or pin lives in this
directory. The Gen 3 sources and `patch/tools/build.py` are untouched
(byte-identical, guarded by a test), so the Gen 3 payload sha cannot change.

Do not include these headers together with `trade_targets/abi.h` (an `#error`
enforces it). Per-title code goes in `patch/src/nds/gen4/` and `patch/src/nds/gen5/`.

## Files

| File | Role |
|---|---|
| `abi.h` | mailbox, witness, revision protocol, milestone model, success predicate, `SlinkRecordStageV1`, static asserts |
| `compat.h` | toolchain shim: fixed-width types and `SLINK_STATIC_ASSERT` (mwccarm 2.0/sp2p2), `<stdint.h>`/`_Static_assert` elsewhere |
| `record_binding.h` | `SlinkRecordBinding`, `SlinkDecoder`, text spec, PK3/PK4/PK5 reference bindings, bounded text copy |
| `trade_producer.h` | PREPARE / SCENE / WITHDRAW / STATUS state machine, async post-save with watchdog |
| `panel_producer.h` | owned info-panel lifecycle, terminator from the binding |
| `sound_producer.h` | SE / fanfare dispatch |

## Toolchains

* **Host gcc / clang — plain C11.** `abi.h` includes `compat.h`, which includes
  `<stdint.h>` and maps `SLINK_STATIC_ASSERT(cond, msg)` onto `_Static_assert`.
  Nothing else about the stack changes.
* **mwccarm 2.0/sp2p2 — the NDS titles.** This toolchain predates C99
  `<stdint.h>` and parses C11 `_Static_assert` as a declaration, so `abi.h` could
  not be compiled on target at all. `compat.h` supplies the fixed-width types
  itself, using the Nitro SDK spellings so `uint32_t` *is* `u32`, and maps
  `SLINK_STATIC_ASSERT` onto the C89 negative-array-size typedef. It is included
  with a quoted, relative `#include "compat.h"`, so it travels with `abi.h` and
  needs no include path of its own.
* **The per-title build still has to glue the include dir.** Its mwcc compile line
  needs `-I<dir containing patch/src/nds/common>` so `#include "abi.h"` resolves
  from the per-title sources, exactly as the host build passes `-I`.
* **Every header here is C89-style for mwcc** (no `_Static_assert`/`_Alignas`/`<stdint.h>`
  outside compat.h's C11 arm; declarations at block top, no for-loop-head
  declarations). The word alignment of the trade producer's two stage buffers is
  proved by `offsetof` asserts instead of `_Alignas`. `static inline` stays (the real
  mwccarm accepted it in the Gen 4 build); `tests/unit/test_nds_c89_scan.py` enforces
  the rest on host gcc with `-std=gnu89 -Wdeclaration-after-statement`.
* **Host seq discipline is part of the contract.** `tp_ack` (shared with the panel and sound
  producers) compares only `seq`, never the opcode, so a host must not reuse the seq of an
  outstanding trade command for another opcode (the inherited Gen 3 assumption); a foreign
  command that does collide can be consumed by a poll-side ack. Gating `tp_ack` on trade
  opcodes was tried and rejected: it breaks the panel/sound acks that reuse it.
* **No u32 divide in the producers.** The text helpers use shifts (width is 1 or 2), so the
  mwccarm link needs no `_u32_div_f` runtime helper (found by the Gen 4 real-compiler run).
* **Title dispatchers MUST route by opcode.** `slink_trade_service` ignores any opcode
  that is not a trade opcode (so sound/panel commands are never FAIL-acked), but it
  must still be called on every visit: the save and scene polls live inside it.

## ABI version 3 and the reader rule

The struct layouts, constants and milestone order are the Gen 3 v2 contract, but
the **witness semantics diverge**, so the NDS ABI is **version 3** and a Gen 3
reader must not be pointed at an NDS arena (`lua/gen3/native.lua:631` rejects a
witness with PRE_SAVE_OK set unless `save_status` is 1 or 255; NDS publishes 2
while an asynchronous save is in flight). The NDS reader is `lua/nds/native_witness.lua` (ABI 2 keeps the Gen 3 rule, ABI 3 accepts SAVE_PENDING); see `docs/shared-nds-witness.md`.

**READER RULE** for the future shared witness reader: under ABI >= 3,
`save_status == 2` (PENDING) is legal only while milestone bits 8 (POST_SAVE_OK)
and 16 (FINAL_RESULT) are both clear. Success still needs `save_status == 1`
and all five milestone bits.

Tests split the comparison with Gen 3 in two. The *identical subset* is every
struct layout plus **every `SLINK_*` name defined by both headers**, collected
automatically (not a curated list); it must match exactly except the explicit
`DIVERGED` set (`SLINK_ABI_VERSION` 2 vs 3). Names present in only one header are
pinned sets (`GEN3_ONLY`, `NDS_ONLY`). The *deliberately diverged subset* prints
`SLINK_ABI_VERSION`, `SLINK_SAVE_PENDING`, `SLINK_SAVE_FAILED` and
`SlinkSavePoll`, so a later semantic change cannot hide behind the curated list.

## Lifted unchanged

Mailbox (0x50 B), trade witness (0x50 B), info panel (0x120 B) and control
prefix layouts and offsets; signature `SLNK`; capability bits; opcode ids; status
and failure reasons 2/8/11..15; producer phases; milestone order (pre-save,
commit-entered, scene/evolution, post-save, final-result); visit flags; trade
results; `SLINK_SUCCESS_MILESTONES`; the witness odd/even revision protocol;
`slink_trade_success_is_durable`; arena offsets. Lifecycle logic (identity
binding, epoch/visit/token checks, sticky UNCERTAIN, withdraw rules,
duplicate/idempotent ACKs, clobbered-mailbox protection) is the Gen 3 code
re-expressed; all Gen 3 producer, panel and sound scenarios are re-run unmodified
against the **reference Gen 3 binding** (no substituted validator). The sound
producer is functionally identical. `tp_ack` still compares only the sequence,
not the opcode (an inherited Gen 3 assumption; the async save widens the window).

## Changed, and why

1. **Record handling moved into `SlinkRecordBinding`** (id, generation, flags,
   stored/party/max length, `trade_stage_len`, `extra_len_per_slot`, OT logical
   offset, text spec, `validate`, `identity`, `same_identity`). Gen 3 hard-coded
   `incoming[100]`, a 100-byte copy and PID at +0 / OT at +4.
2. **Versioned staging layout `SlinkRecordStageV1`** (16 B header + 256 B record
   in the blob region). The producer accepts a stage only if layout version,
   binding id, generation and raw flag match, **no unknown flag bits are set**,
   `stage_len` equals the binding's declared length for the op
   (`slink_binding_stage_len`: TRADE = `trade_stage_len`, default `party_len`;
   BOX = `stored_len`, so a deposit arm can stage 0x88 from the same binding),
   `validate` passes and the binding's identity equals the host claim. Then it
   copies exactly `stage_len` bytes into a `SLINK_MAX_RECORD` buffer, tail zeroed.
   `validate` therefore adds only the optional engine `verify` and an
   allowed-forms check: the exact arm length is checked first.
3. **Fail closed**: PK4/PK5 `validate` returns 0 without a decoder or without its
   `verify` callback; identity returns 0 without `read_u32`.
4. **Asynchronous post-save with a watchdog**: `post_save_begin()` only initiates;
   `post_save_poll()` returns PENDING / OK / FAIL (anything else is FAIL). The
   witness shows `SAVE_PENDING` (2) while in flight. `POST_SAVE_OK` is published
   only on a polled OK, then the final-result milestone. The producer stamps
   `save_start_frame` at begin; PENDING for more than the engine's
   `save_timeout_frames` (REQUIRED nonzero, else PREPARE is refused with
   BAD_ARGS) is FAIL, so UNCERTAIN stays reachable after COMMIT_ENTERED. The
   bound is a shared invariant, the number is the adapter's: the host's own
   TRADE_SCENE budget is 6000 frames (`lua/gen3/native.lua:177-181`), so an
   adapter bound that is longer would let the host poison the module before the
   native side reaches UNCERTAIN. A synchronous engine still finishes in one
   service call (begin, then one immediate poll).
   The pre-trade save leg has the same kind of bound, optional: the engine field
   `pre_save_timeout_frames` (0 = off, the pre-existing unbounded behaviour; an
   adapter that drives the pre-save through the game's save scene should set it
   below the host's 6000-frame budget). The producer stamps `pre_save_start_frame`
   when it starts the pre-save; a poll still waiting (0) or consented-but-unsaved
   (2) past the bound finishes the visit UNCHANGED (nothing is mutated before the
   save). A poll that returns saved (1) wins over the timeout, even on the first
   frame past the bound. Zero-fill existing `SlinkTradeEngine` initialisers.
5. **Observed identity**: `received_pid/otid` in the witness are the identity the
   engine returned at the same_identity check, not the host-staged claim.
6. **Must-not-alias**: bindings flagged `SLINK_RB_COMMIT_MUTATES_INPUT` (PK4 box
   path: `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` calls `RestoreBoxMonPP` on
   its input) receive a scratch COPY from the producer; the staged buffer and the
   host stage stay pristine and a retry sees identical bytes. Both PK4 and PK5
   reference bindings set it (PK5 conservatively, unverified).
7. **Panel text**: the 0xFF scan became a `SlinkTextSpec` terminator (width 1 or 2
   bytes, value, charset). Rows stay 32 bytes. `SlinkInfoV2.lines` counts ROWS
   (not characters); a 16-bit binding row holds 16 units, terminator on a unit
   boundary. `slink_copy_text_bounded` (capacity includes the terminator)
   replaces `slink_copy_name_bounded`, which is **intentionally not lifted**; it
   is consumed by the later per-title native adapter cards (Gen 4 / Gen 5 name and
   message copies), not by any producer here.
8. **Engine struct**: `validate_incoming` is gone (binding), `start_scene` also
   takes the length, `post_save` split in two, and the engine carries `binding`,
   `decoder` and `save_timeout_frames`.
9. **Not lifted**: Emerald-only call/Match Call records and reasons 16..18, and
   rival/carrier/call producers. Opcode 32 keeps its id, never advertised.

## Title-private space

The arena tail is split so a title can own state that shared code never touches.
`SLINK_TITLE_OFFSET 0xE00` / `SLINK_TITLE_SIZE 0x40` are the first 64 bytes of the
former reserved region — asserted to start exactly at `SLINK_RESERVED_OFFSET` and
to fit inside `SLINK_ARENA_SIZE` — and `0xE40..0x1000` stays free for a future
shared region.

* **Ownership.** The per-title ROM writes the region, the host reads it. Its
  layout and its version number are owned per title and documented there: version
  the field yourself, then publish it **last**, so a reader can never meet a new
  layout under an old version.
* **What it is not.** Never a rules channel and never a write permission. Shared
  code — producers, bindings, `abi.h` — never reads or writes it. It is state, not
  authority.
* **Capability bits.** 0..6 are the shared set defined in `abi.h`. 7..15 are
  reserved for future *shared* capabilities and read 0 until a shared id is added
  there. 16..31 are *title-private*: ROM-owned, documented per title, never read by
  shared code.
* **Failure reasons.** 2..15 are the shared set. 16..31 are reserved for future
  *shared* reasons and read 0 until a shared id is added there. 32..63 are
  *title-private* and decoded through the title adapter only.

A title dispatcher **must route by opcode**: a producer acks only an opcode it
owns, and an opcode it does not own is not a command to reject — it is not its
command. A dispatcher that acks everything it is handed turns an unimplemented
title opcode into a false OK.

## Reference bindings

| binding | stored | party | raw-staged | OT access | extra/slot | text |
|---|---|---|---|---|---|---|
| Gen 3 PK3 | 80 | 100 | yes | plaintext +4 | 0 | 8-bit, 0xFF |
| Gen 4 PK4 | 0x88 | 0xEC | yes | decoded logical +0x0C | 5 | 16-bit, 0xFFFF |
| Gen 5 PK5 | 0x88 | 0xDC | yes (assumed) | decoded logical +0x0C | 0 (unconfirmed) | 16-bit, 0xFFFF |

**Raw-encrypted staging.** Gen 4 coordinator, HGSS only:
`Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (pret `src/party.c:97`) raw-copies
the full 0xEC record and the box primitive takes the first 0x88 bytes (a
self-contained prefix), so the host stages at-rest bytes and the ROM does no
crypto or checksum work. Because the OT id is in the encrypted body,
`identity`/`validate` for PK4/PK5 call an adapter-supplied `SlinkDecoder`
(`read_u32` at a logical offset, `verify` for the checksum). The shared layer
contains no cipher.

**`extra_len_per_slot` is INFORMATIONAL.** PartyExtra is 5 bytes per slot
(pret `include/constants/pokemon.h:132`). It is never staged and never read by a
producer; adapters and hosts use it to shift the per-slot extras array on
remove/compact. The party commit primitive resets the slot's extra itself.

## Could not verify

- `record_binding.h`'s PK4 binding carries no inline "UNVERIFIED independent-implementation" comment like
  the PK5 binding does (~line 168); it should get one (coordinator: comment-only edit at the `SLINK_BIND_GEN4_PK4`
  initialiser, ~line 162). Its raw staging, 0x0C OT offset and MUTATES_INPUT flag are likewise not checked against
  an independent implementation or a ROM.
- The producer harness identity chain is only independent where `received_key` is: the
  `received-key-from-staging-decoder` mutant (decodes the staged record via the same `dec_read` instead of an
  independent value) must stay RED. The real `received_key` hook must read the game's received party slot, never
  the staging decoder.
- No Gen 4/5 ROM or emulator was touched; Gen 4/5 offsets (OT at logical +0x0C,
  party 0xEC / 0xDC, plaintext PID at +0) come from the brief and prior notes.
- **Whether the actual TRADE commit (pret `src/trade.c`) is a raw party-form copy
  is UNVERIFIED for HGSS, and everything about BW / B2W2 is unverified**: the PK5
  raw-staging flag, its MUTATES_INPUT flag and `extra_len_per_slot = 0` are
  assumptions.
- The pret citations (`party.c:97`, `pokemon.h:132`) are the Gen 4 coordinator's;
  they were not re-read here.
- Gen 5's real save completion semantics are unestablished; the contract only
  guarantees initiation is never success and PENDING is bounded. Choosing the
  timeout number belongs to the adapter.
- Host-C tests prove state-machine behaviour against fake engines, not flash
  durability, ARM codegen, volatile access widths, or ARM9/ARM7 cache coherence.
- The shared Lua witness reader (NDS-3) has not been shown to implement the
  reader rule above.
- **`abi.h` has never been through a real mwccarm 2.0/sp2p2.** The MWERKS path is
  walked on host gcc with `-D__MWERKS__` (`tests/unit/test_nds_abi_compat.py`),
  which proves no `<stdint.h>` include, that the asserts still evaluate and that
  the layouts survive. It cannot prove that compiler accepts the
  negative-array-size typedef, nor that `<stddef.h>` (for `offsetof`) exists in
  the pret lib/include — `<stdint.h>`'s absence is the ruling, `<stddef.h>`'s
  presence is inferred. If the first on-target build rejects `<stddef.h>`,
  `compat.h` is where `size_t`/`offsetof` must be provided.
- **Real-compiler evidence is the Gen 4 coordinator's run, not ours:** all six headers, an
  all-includes TU, instantiations of every `static inline` and Gen 4's own beacon/dispatch
  compiled clean on pret mwccarm 2.0/sp2p2 (`-W error`, no shim) at 78c2a0a0, with no undefined
  symbols and the negative `SLINK_STATIC_ASSERT` control failing as intended. Re-run it after any
  header change; this repo still vendors no mwccarm.
- **The title-private region's layout is undefined.** Only its extent is pinned;
  a title card owns the 64 bytes and must document them.
