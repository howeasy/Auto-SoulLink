# OMP adversarial review — Gen 2 BOX writer (card gen2-O-box), 2026-09-23

Peer review for task `cx-53f4f61a` (peer omp, orchestrator claude). READ-ONLY: this file is the only
thing written; not committed. Mode: ADVERSARIAL — the writer was assumed wrong; what survives is
stated with the conditions under which it would fail.

Reviewed at HEAD `6a181a36`: `0bd77db6` (lua/gen2/boxes.lua + writes.write_party_block),
`dbb849a3` (composition: lua/gen2/client.lua, entry.lua, lua/gen2_write_safety.lua,
lua/tests/gen2_write_windows.lua), and the receipt files. Pins: pokecrystal `7a7881d`,
pokegold `656583c`. No emulator run here; the decomp comparison below is byte-level source reading.

---

## SUMMARY

The executor's model of the cartridge is correct in every place I could check it against the pins:
the active-box/backing-slot split, the 1102-byte save copyback and the untouched 2-byte padding, the
deposit/withdraw orders, the four-array party compaction (including the odd `ld [hl], -1` on the last
OT slot), the deposit append, the withdraw's stat/HP/status computation and the PP restore formula all
match pokecrystal/pokegold exactly, and no unproven write kind can reach a byte (the kinds are a
positive list checked before planning, and the gate re-checks the live window per derived kind). What
does not survive is the *durability* claim: the ops are settled on the emulator's memory, the
active-box half of a deposit is only persisted by the engine's own `SaveBox` (a save or a box switch),
and a backing-box withdraw has a real (if narrow) reset window in which the mon exists nowhere and no
re-issue can recover it.

## FINDINGS

### F1 — MEDIUM: a backing-box withdraw can lose the mon, with no recovery path

Order: party write (WRAM, volatile) then box write (CartRAM, durable for a backing box)
(`lua/gen2/boxes.lua:471-490`; the native mirror `TryWithdrawPokemon`, `engine/pokemon/bills_pc.asm:1820-1837`).
A reset after the box write and before any save: `Init` clears WRAM (`home/init.asm:66-75`), `LoadBox`
restores only the *active* `sBox` (`engine/menus/save.asm:975+`, `:900-973`), and the backing slot keeps
the removal → the mon is in neither the reloaded party nor the box. The client never acked
(`run_box` sends `sync_retrieve_done` only on success, `lua/gen2/client.lua:504-511`), so the server
re-issues, and the executor refuses with "key not boxed" (`boxes.lua:483`) — nothing can recover it.
Deposits are safe by contrast (the box write is to the active copy, which `LoadBox` reverts) and the
receipts' reset control covers exactly that deposit/memorial case, not this one
(`lua/gen2_write_safety.lua:69-77`). The native PC has the same hazard (no auto-save after a
withdraw), but SLink automates it and the server's model has no compensating witness. Confidence: high
on the mechanism; the practical window is one callback (both writes are synchronous inside `run_box`,
`lua/gen2/client.lua:489-535`), so a *soft reset between frames* cannot hit it — only a reset/power
event that lands inside or immediately after the callback and before the next flush/save.

### F2 — MEDIUM: the active-box half of a deposit is settled before the engine persists it

`copyback.mode = ENGINE_SAVEBOX_DEFERRED` (`boxes.lua:145-152`) is honest, and the obligation
`reassert_after_full_save` is recorded (`:139-143`), but the client acks/settles the op on the
in-memory state: `box_mon` sets `pending_rescan` and sends nothing (`client.lua:493-502`), so until the
next full save or box switch (`ChangeBoxSaveGame` is itself a save, `engine/menus/save.asm:39-62`) the
only copy of the deposit is `sBox`, which `LoadBox` overwrites on any reset. A reset therefore reverts
a "completed" deposit; the divergence self-heals only through the reconnect reconcile (the receipt's
reset/reload controls, `tests/fixtures/gen2/receipts/crystal.write_window.json`). Worth an explicit
save-witness requirement (or a recorded limit) before a deposit is treated as durable.

### F3 — LOW: the withdraw takes the level from the record instead of recomputing it

The native withdraw calls `CalcLevel` from the experience and writes the recomputed level
(`engine/pokemon/move_mon.asm:649-655`); the executor uses the record's level byte
(`boxes.lua:410-413`, `:432-435`). They agree for a consistent record and differ only for a glitched
exp/level pair. Same for the pad byte after `MON_STATUS`: the native zeroes only the status
(`move_mon.asm:674-676`), the executor zeroes status + pad (`boxes.lua:427`) — harmless, but a
byte-wise oracle that compares against a native withdraw would see it.

### F4 — LOW: the "both places" recovery refuses when the box copy is not in the active box

`ops.deposit`'s interrupted-deposit path requires `hit.active` and a full-record match
(`boxes.lua:452-460`); if the player switched boxes between the crash and the retry, the completion
refuses ("key exists in both party and box") and the command stalls (NACKed, needing manual
intervention). Safe, but a dead-end the plan does not name. Same shape in `ops.memorialize`
(`:492-517`) and `ops.withdraw` (`:471-478`).

### F5 — LOW: mail policy is stricter than the native PC, and its comment overstates

`no_mail_from` refuses when the removed mon *or any later slot* holds mail (`boxes.lua:370-375`)
because SLink never writes `sPartyMail` — correct and safe. The comment "(the native PC refuses mail
too)" is only true for the *selected* mon (`engine/pokemon/bills_pc.asm:1595-1616` refuses with
`PCString_RemoveMail`); the native also *shifts* `sPartyMail` in `RemoveMonFromPartyOrBox`
(`move_mon.asm:1336-1370`). Doc nit, not a defect.

### F6 — LOW: durability of the CartRAM writes is not witnessed by the receipts

The receipt's controls are `{idle reacquisition, warp/Continue}`
(`tests/fixtures/gen2/receipts/crystal.write_window.json`), and the plan's own obligation says
`durability="UNQUALIFIED"` (`boxes.lua:139-143`). A crash between the op and BizHawk's next SaveRAM
flush can revert CartRAM writes while the server believes them done (S-7's save-witness discipline
applies to the game's saves, not to SLink's own SRAM writes). The `boxes_reload` gate mode proves a
*clean* reload only.

### V — VERIFIED (no action): the decomp comparison

- Active/backing model: `BoxAddresses` is in `sBox1..sBox14` order
  (`engine/menus/save.asm:1079-1085`); `GetBoxAddress` = `BoxAddresses[wCurBox]` with a 0..13 sanitizer
  (`:874-898`); `SaveBoxAddress` copies exactly `sBox..sBoxEnd` = 1102 bytes into the target slot
  (`:900-973`), leaving the 2 padding bytes (`macros/ram.asm:121-122`; `BOX_LENGTH = 1104`,
  `constants/pokemon_data_constants.asm:141`) untouched — matching `boxes.lua:145-153` and the
  1102-byte spans. `boxes.lua:96-100`'s asserted field partition (22/662/882) matches the `box` macro.
- Orders: `DepositPokemon` = box then party (`bills_pc.asm:1768-1782`); `TryWithdrawPokemon` = party
  then box (`:1820-1837`) — matching `ops.deposit` (`boxes.lua:465-468`) and `ops.withdraw`
  (`:486-489`).
- Party compaction: species shift + `0xFF` terminator (`move_mon.asm:1233-1244`), full-array shifts
  through `CopyDataUntil` ("copy [hl..bc) to de", `home/print_text.asm:83-99`), and the last-slot
  `ld [hl], -1` on the *OT* array (`move_mon.asm:1255-1260`) — matching `removed()`/`plan_withdraw`
  (`boxes.lua:377-395`, `:171-190`) exactly, including the OT byte.
- Deposit append: `SendGetMonIntoFromBox`'s PC branch (count+1, species at the new slot, `$ff` next,
  the 32-byte struct copy; `move_mon.asm:508-540`) — matching `insert()` (`boxes.lua:157-167`). The
  capture *prepend* (`SendMonIntoBox`, `:942-965`) is deliberately not mirrored.
- Withdraw stats: `CalcMonStats`/`CalcMonStatC` (`move_mon.asm:1402-1605`): DV nibbles, the HP DV
  formula, `GetSquareRoot` = "the first b with b² ≥ de" (`engine/math/get_square_root.asm:3-25`),
  ×2, root÷4, ×level/100, +5/+10, the 999 cap — matching `party_record()` (`boxes.lua:410-435`).
  Sp.Atk/Sp.Def share the Special DV and exp (`move_mon.asm:1446-1451`) as the executor does.
- PP restore: `RestorePPOfDepositedPokemon` keeps the PP-Up bits and adds the max PP
  (`move_mon.asm:740-773`); `ComputeMaxPP` clamps the *per-up* bonus at 7
  (`engine/items/item_effects.asm:2777-2799`) — matching `payload()`'s
  `ups*min(floor(base/5), 7)` (`boxes.lua:397-408`); the `move` macro asserts PP ≤ 40
  (`data/moves/moves.asm:11`), so the 6-bit PP field cannot overflow.
- Composition: kinds are a positive list (`lua/gen2_write_safety.lua:25,363-372`), `need()` refuses
  any kind without `covers()` (`boxes.lua:292-296`), the derived kind is always in the need list, the
  gate re-checks the live window per kind (`boxes.lua:241-246`, `lua/gen2/entry.lua:347`), and the
  NACK carries the kind name (`lua/gen2/client.lua:36-37,500-501`). No unproven kind can slip through.

## DISAGREEMENTS

1. If "the box writer is crash-consistent" is the coordinator's summary, F1 (backing-box withdraw)
   and F2 (deferred copyback) contradict it: only the *active*-box and *memorial* cases are
   reset-safe by construction.
2. "Current box = backing slot" must not be read as "the active box *is* the backing slot": `sBox` is
   a working copy; the backing slot is synced only by `SaveBox` (`save.asm:900-973`) — the executor's
   model gets this right, but a reader of the card's fact list could take it the wrong way.
3. The receipt's `covered_controls` is a two-entry list; if the box kinds are presented as "proven"
   without that qualifier, the *coverage* (not the predicate correctness) is overstated.

## UNKNOWN / UNVERIFIED

- No live/emulator verification here: the receipts are the coordinator's evidence; I verified their
  structure and the claims they encode, not their physical provenance.
- Whether BizHawk flushes CartRAM to disk at any point other than a clean exit (F6) — an emulator fact
  the U2 lane should witness.
- The worst-case timing of the two writes inside one `run_box` callback (F1) — source reading says
  same-callback, so a between-frames reset cannot interleave.
- The server-side re-issue/reconcile behaviour after a box NACK was not traced (out of this card).

## RECOMMENDATION

1. For a *backing-box* withdraw, require a save witness before the op is treated as durable (or
   record the loss window as a limit with a status-page witness). The current order (party first) is
   already the safer one — do not reverse it.
2. Make the deposit's durability explicit: either require the next full save (or box switch) before
   acking, or surface "pending box save" the way the U2 pending sync is surfaced.
3. Close F4's dead-end: when the duplicate box copy is not active, allow completion by *removing the
   party copy only* after a full-record match (the box copy is the durable one), or NACK with a named
   reason the debug page can resolve.
4. Fix the F5 comment; align the pad-byte behaviour (F3) with the native or document the difference.
5. Add a crash-durability control to the gate: kill the emulator after an op and before a save, then
   reload and assert the mon exists exactly once (party or box), for both the active and backing
   cases.

## TESTS / VERIFICATION

- Existing, should stay green: `pytest tests/unit/test_gen2_boxes.py tests/unit/test_gen2_writes.py
  tests/unit/test_gen2_write_safety.py -q` (the plan/gate/refusal/idempotence coverage, including
  `test_generated_flat_facts_match_independent_pinned_symbol_oracle`), plus the write-window gate's
  box modes (`lua/tests/gen2_write_windows.lua:386-455`).
- Add: the crash control from recommendation 5; a test that a backing-box withdraw with a reset
  between the two writes is either refused or completed (never silent); a test that the level/pad
  bytes (F3) match a native withdraw byte-for-byte, so the oracle can compare full structs.
