# Pre-starter initial save kernel

The pure kernel prepares and verifies the first complete save image. The
`gen1_initial_save_runtime` lifecycle now wires it to bootstrap enrollment and
the held client dispatcher. It grants no ordinary frames and clears no initial
or recovery blocker.

## Cartridge transform

The pinned `SaveGameData` routine (`pokered/engine/menus/save.asm:290`,
`pokeyellow/engine/menus/save.asm:274`) sets `wSaveFileStatus` to 2 and invokes
`SaveMainData`, `SaveCurrentBoxData`, and `SavePartyAndDexData`. The existing
`gen1_full_save.image` layout is the shared Gen 1 definition of these field
copies and their complemented byte checksum.

`server/gen1_initial_save.expected(before, identity=...)` requires an empty party
and current box, zero owned/seen dex, current box flag 0, and the exact enrolled
trainer identity. The complete WRAM field collection is unchanged. SRAM outside
`sGameData` and its one checksum byte is preserved, including inactive boxes and
Hall of Fame bytes. This deliberately does not initialize every stored box: the
cartridge's uninitialized-box flag remains authoritative. The output save status
is 2. Empty party structure is checked, not interpreted as gameplay provenance.

The controller must supply the previously verified normal new-game bootstrap,
the owned full preimage and a qualified held checkpoint before any write. A
structurally empty point alone does not prove a new game or ownership of a file.

## Reusable boundary

`server/gen1_save_delta` implements full-point digest binding, compact hex deltas
and reconstruction of an explained partially applied preimage. Memorial's public
`wire_payload` and `recover_point` functions delegate to it with their existing
schemas and behavior. This is generation-owned because it understands the RBY
save point and status; `hex_delta` remains the generation-neutral primitive.

`lua/gen1_held_save_image` contains the former memorial image executor. It keeps
the deterministic name/main/sprites/box/party/tiles/CartRAM order, full reconstructed
preimage validation before the first write, guards every 64 changed bytes, and
requires an unchanged frame. A partial write is retryable only when all modified
bytes match the prescribed old/new values and the entire reconstructed point has
the original digest. Foreign bytes cannot become repair authority.

The memorial wrapper preserves its command, intent, receipt and phase tags,
including its read-only observation operation. The initial-save wrapper accepts
only `initial_save`, `rby-initial-save-intent-v1`, `rby-initial-save-delta-v1`, and
`rby-initial-save-receipt-v1`. It additionally rejects WRAM deltas and any CartRAM
output that differs from saving the original preimage's fields. The phases are
`initial_save`, `initial_save_repair`, and `initial_save_flush`.

These phase names do not grant permission. The caller must durably persist the
intent, supply fresh command-scoped permission to each write/repair attempt,
request a separate fresh save permit after complete image readback, and atomically
record the receipt/ACK. The supplied `safe`, `owned`, and `permitted` callbacks
retain those responsibilities. `gen1_held_faint` dispatches `initial_save` through
the common image executor and requests a new phase-specific permit after partial
repair or complete image readback. The server requires the original enrollment
frame even when a later frame-accounting component exists.

## Durable lifecycle

Scheduling waits until both immutable initial observations exist and requires
the actor's validated bootstrap. Both initial-observation and bootstrap handlers
call the same scheduler. This preserves the global initial-enrollment refusal
against pending writes: an early actor bootstrap cannot block peer enrollment.
The compact entry retains separate bootstrap and scheduling origins; the latter
may be the peer's initial-observation event. The command and preparation record
are committed with that exact origin. The exact image/file ACK and completion
record are committed atomically. Audit checks the retained origin command and
completion event; same-core transport reconnection preserves the obligation,
while changed physical identity or context refuses. No synthetic bootstrap is
created for existing held-launcher fixture saves.

## File proof and evidence limits

The provider is qualified read-only before mutation. Flushing requires the
caller's consumed permission and complete image readback. Python receipt checking
re-derives the exact image and command body, checks command ID/sequence, body
digest, context, ROM, original preimage and postimage, then validates the complete
32 KiB file SHA-256 at the exact held frame using `verify_file_image`. That remote
verifier does not open a path or establish host directory isolation itself.

`tests/unit/test_gen1_initial_save.py` uses synthetic pre-starter points, actual
Lua memory/image code, and a modeled SaveRAM host. It covers all three receiver
variants, pre-starter refusals, SRAM/WRAM preservation, partial interruption and
repair, withheld save permission, foreign preimages, unrelated SRAM deltas, and
misbound file/command receipts. Existing memorial tests exercise compatibility.

The normal downloaded-launcher gate now passes Yellow/Yellow, Red/Blue and
Blue/Yellow cold boots using ordinary New Game inputs, one owned hold per
process, and distinct isolated SaveRAM files. It verifies exact on-disk image
bytes and SHA-256, unchanged enrolled WRAM fields, save status 2, preserved input
fixtures, and retained recovery holds. Post-save screenshots show the normal
bedroom for both endpoints. Two legacy fixture cases prove no bootstrap or
initial-save command is invented. The five-case report is
`.cache/initial-save-launcher-live.xml`; it does not qualify moving gameplay or
normal CONTINUE/reload of the resulting empty-party save.

The existing `test_gen1_full_save` original-engine differential uses an explicitly
injected CPU fixture; it remains separate transform evidence and was not rerun
or represented as visual startup qualification here.
