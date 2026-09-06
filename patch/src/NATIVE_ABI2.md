# RR native safety slice (ABI2, not release approval)

This slice retains the existing 64-byte mailbox and every existing EWRAM allocation.
`native_mailbox.h/.c` separate the mailbox layout, receipt publication and immutable ROM
descriptor from the remaining feature handlers. `rr_storage_guard.h` provides the shared
byte-wise PID/OTID and party-count preconditions used by native storage.

**The arena is still disputed.** The interval `0x0203F76C..0x0203FBAF` is also referenced by
RR's retained libc allocator, including `__malloc_av_`. Normal gameplay reachability has not
been demonstrated. No adjacent gap is newly allocated or declared free. The generated manifest
keeps this ownership issue unresolved; selected live instrumentation and a verified relocation
if a legitimate owner is observed remain mandatory release gates.

## Receipt and payload ownership

The mailbox status is IDLE=0, BUSY=1, OK=2, FAIL=3. C publishes a terminal receipt's status last.
Lua copies its sequence, reason and all 16 result bytes before explicitly retiring it to IDLE.
`MB.pump()` can therefore post a queued command before application code polls the previous
receipt without losing the result. Lua request tokens remain distinct across the 16-bit wire
sequence wrap. Queued argument arrays and text/menu/blob payloads are immutable snapshots.

`MB.poll(token)` consumes the retained application receipt and selects the result used by
`MB.read_result_u8`. The sound/ghost convenience helpers need no retained application receipt;
their most recent completion can still be polled immediately. Arbitrary `MB.send` calls retain
receipts by default. Queues and retained receipts are bounded; overflow stops dispatch and
surfaces `MB.session_error()` instead of evicting uncertain operations.

Receipt retirement does not retire a text lease. Existing UiState kind 4 tracks field-message
startup/open/close without expanding its 12 bytes. Its opened ACK is published only after the
script lock is observed. Text remains leased while native UI, field script, or battle notification
readers are active. Menu payloads wait for UI/script readers. Lua staging functions no longer
write these live buffers. A UI timeout does not release a still-owned engine scene. Pending
startup without a witnessed transition remains BUSY with reason 12; the coordinator must pause
and reconcile rather than overwrite it. This slice does not implement forced scene cancellation.

Native session/sequence loss is exposed as an error without replay. `MB.reset_after_reconcile()`
is an explicit coordinator seam, usable only after reconciliation and after any engine operation,
UI/script and battle-notification readers have actually finished. It does not interrupt them.

The info-panel's existing separate staged region and the ghost desired-state region are not
converted into the text/menu/blob queue by this slice. Their complete generation/resource
lifetime redesign remains separate work. Production Lua Explosion remains unchanged.

## Guarded storage contract

The convenience surfaces are:

```lua
MB.deposit_mon(party_slot, box_id, box_pos, guard)
MB.withdraw_mon(box_id, box_pos, party_slot, guard)
MB.memorialize_mon(party_slot, box_id, box_pos, guard)
MB.move_box_mon(src_box, src_pos, dst_box, dst_pos, guard)
-- guard = {pid = u32, otid = u32, count = expected_party_count}
```

All guards are required. Arguments use zero-based indices. Opcodes 24/25/26 retain their first
three location bytes; byte 3 is guard tag `0xA2`, bytes 4..7 PID, bytes 8..11 OTID (little endian),
and byte 12 expected party count. Opcode 28 is checked box-to-box transfer: bytes 0/1 are the
source box/position, byte 2 destination box, and byte 13 destination position; its remaining
guard bytes are identical. Compressed RR mons preserve PID/OTID in their first eight bytes;
the guard reads them byte-wise because 58-byte slots are not always word-aligned.

Storage requires the verified field callback, no script/UI and no borrowed-party window. It
checks count, source identity, index bounds and destination vacancy before writes. Withdrawal
must append at exactly the current party count into a vacant 100-byte slot. Party removal cannot
empty the party or remove its last usable non-egg mon. Party memorialization requires HP zero.
Box transfer rejects source=destination and empty sources, copies all 58 bytes, verifies the
destination, then clears the source; the party is untouched.

Successful storage receipts contain PID/OTID in result bytes 0..7. Bytes 8..15 are reserved
exclusively for the opaque native reservation ID, so location/count/survivor evidence comes from
complete client-side destination/source/party readback; a native ACK is not a durable
server action receipt. Failures do not authorize an unguarded Lua fallback.

New reasons: 20 context, 21 missing guard, 22 count, 23 identity, 24 occupied destination,
25 last usable/last party slot, 26 source not dead, 27 boxed copy readback mismatch. Legacy bounds
and empty-source reasons 2/3 remain. A readback failure is uncertain, never permission to resend.

## ROM descriptor and builds

PING returns the descriptor ROM pointer in result bytes 0..3. `MB.read_descriptor(token)` polls
and validates the ROM descriptor; ABI1 is not accepted. Descriptor layout is 156 bytes:

| Offset | Field |
|---|---|
| 0 | u32 magic `SLD2` |
| 4 / 6 | u16 descriptor version 1 / ABI 2 |
| 8 / 12 / 16 | u32 size / capability mask / mailbox address |
| 20 / 22 | u16 mailbox size 64 / storage guard tag 0xA2 |
| 24 | 64 lowercase hex build-id bytes plus NUL |
| 89 | 64 lowercase hex mailbox-layout SHA-256 bytes plus NUL |

Capabilities are bit 0 `receipts_v2`, 1 `payload_leases`, 2 `storage_guard_v2`, 3 `descriptor_v1`,
and 4 `reservation_echo_v2`.
They describe this slice, not an assertion that the RAM arena or all native gameplay is validated.
The build ID binds actual native source/header/linker/build-tool/mailbox-Lua input hashes,
compiler executable hash and flags. The layout hash fingerprints `native_mailbox.h`; the full
native-input manifest separately binds other engine/feature layouts. Root admission must also
bind complete client/data packages and the actual loaded ROM externally.

`build.py --output-dir <owned directory>` keeps objects, ELF, ROM, UPS and `native_manifest.json`
together without touching the default distributed patch. `--check --output-dir <same directory>`
rebuilds in unique scratch and compares its UPS to that candidate. The linker rejects mutable
`.data`, `.bss` and COMMON sections. Structural assertions pin mailbox, descriptor, ghost and UI
sizes; those checks prove layout consistency, not external RAM ownership.

The confirmed non-field sprite write was removed. Context now uses the verified callback directly,
instead of learning one from retained player-OE bits. The next resource slice is documented in
`NATIVE_PRESENCE.md`; its engine lifetimes and remaining effects still require live validation.

Native storage also rejects active postbattle writer tasks `0x09094295` and `0x0909411D` in the
16-entry table at `0x03005090`, stride 40. The active byte at `+4` is required: RR's `DestroyTask`
clears it and leaves the old function pointer, which must not falsely block settled storage.

Build manifests expose `rom_sha1` for comparison with BizHawk `gameinfo.getromhash()` and retain
SHA-256 artifact bindings. Embedded native identity hashes canonicalize CRLF to LF. Raw
`native_inputs` hashes remain provenance; `native_inputs_canonical` feed the build identity.
The mailbox-header layout fingerprint uses the same normalization. This pins the compiler and
flags while permitting equivalent Git text checkouts under `core.autocrlf`.

## Durable preparation and correlation seam (activation remains gated)

`MB.set_context_generation(generation_string)` supplies the authoritative coordinator's current
save/context generation. `MB.prepare(opcode, args, native_id)` freezes operation, bytes, payload,
and an RR context stamp without any EWRAM write, including no receipt retirement. The opaque
native ID is exactly 16 lowercase hexadecimal characters, never a JSON 64-bit number. The full
128-bit durable command ID remains authoritative in the shared executor.

The storage wrappers have matching `prepare_` methods, for example
`MB.prepare_move_box_mon(src_box, src_pos, dst_box, dst_pos, guard)` with `guard.native_id`.
Persist the exact serializable preparation in the immutable intent, then call `MB.submit`.
Submission rejects changed preparation bytes and a changed generation or RR context. Queued
preparations recheck context immediately before their later post. C storage checks the structural
context stamp again on the actual apply frame. A serialized preparation cannot be blindly submitted
into a fresh Lua process: absent private ownership must be reconciled first.

Only the first 14 args bytes are operation-specific. Args 14/15 contain expected map group/number,
16..19 expected callback2 (LE), 20 script lock, 21 borrowed-party active, 22 player OE ID, 23 marker
`0xC2` for durable preparations. Args 24..31 hold the native ID's eight octets in hexadecimal-string
order. C echoes them into result 8..15 before publishing status. Lua verifies both the live args ID
and receipt echo as well as the wire sequence, including for asynchronous completions.

Conflicting reuse of an outstanding/retained durable ID is rejected. Registry/queue/receipt sizes
are bounded. After durable receipt publication **and full game-state readback**, the coordinator
may call `MB.release_reservation(native_id)` to retire the in-memory registry entry. Historical
reuse rejection and ID allocation remain the durable actor's responsibility; a 64-bit echo alone
is not a proof of global uniqueness. `MB.send` and existing convenience calls without an explicit
native ID remain a **volatile compatibility lane**, not a durable execution protocol.

These seams do not by themselves make savestate loading safe: loading a saved BUSY opcode can
restore native work before a subsequent C hook. The host must intercept load/reset and pause before
frame advancement, invalidate the generation and reconcile. EWRAM alone cannot provide an
unsaved generation because savestates restore it. An old same-action receipt never substitutes
for current poststate. Durable runtime activation remains blocked until the shared coordinator,
reservation allocation, current-context proof and host reset/load interlock are all connected and
validated. Other legacy native feature operations still need their own prepared-context/identity
contracts; the actual-frame structural context guard in this slice is for storage.

Receipt capture checks the prepared context generation before consuming a matching sequence
and reservation ACK. A generation change leaves pending or terminal native state unretired for
reconciliation. Saved receipts retain `context_generation`; `MB.poll` will not present an old
generation as a current success. `MB.get_saved_receipt(token)` returns detached historical
evidence without capture or retirement. Expected native scene callback changes do not themselves
invalidate this receipt correlation.

Every public EWRAM-writing helper checks the ABI2 beacon before accessing its shadow region.
Absent/ABI1 writers return false without writes; event draining preserves its empty-list API.
Payload-only Lua staging remains available without a patch. `events_init()` deliberately retains
its legacy drop-to-writer behavior when present; durable bootstrap must reconcile pending event
evidence before calling it. This guard is necessary isolation, not full build/admission authority.
