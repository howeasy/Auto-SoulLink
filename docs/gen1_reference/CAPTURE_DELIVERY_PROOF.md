# Successful capture delivery proof

A source-qualified, read-only primitive that proves one wild capture was
delivered to the party or the current box on an admitted Red, Blue or Yellow
cartridge. It identifies the exact caught key, record bytes and physical
location from before/after evidence at the pinned delivery call. It creates no
identity member, capture record, link, ball credit, clause or history; the
root integrates it under its own frame authority.

Files: `tools/gen_gen1_capture_sites.py` (generator), `data/games/gen1_rby/capture_sites.json`
and `gen1_capture_sites.lua` (artifacts), `server/gen1_capture_receipt.py` (decoder),
`tests/unit/test_gen1_capture_receipt.py`.

## Source facts (pret pokered 405b624, pokeyellow 0a08515)

`ItemUseBall` in `engine/items/item_effects.asm` is the only ball-throw path. It
reaches one of two delivery calls only after a successful capture:

| Branch | Cartridge fact | Outcome |
| --- | --- | --- |
| Out of battle | `wIsInBattle == 0` → `ItemUseNotTime` | no throw |
| Trainer battle | `wIsInBattle == 2` → `ThrowBallAtTrainerMon` | no delivery |
| Party and box full | `BoxFullCannotThrowBall` | no throw |
| Unidentified ghost | `IsGhostBattle` → anim `$10` → `.printMessage` | no delivery |
| Ghost Marowak | `wEnemyMonSpecies2 == RESTLESS_SOUL` on Tower 6F → anim `$10` | no delivery |
| Missed / broke free | anim `$20/$61/$62/$63` → `.printMessage` | no delivery |
| Old man tutorial (Yellow: also Pikachu) | `wBattleType` → `.oldManCaughtMon` | no delivery, no ball consumed |
| Success, party has room | `call AddPartyMon` (`.skipShowingPokedexData`) | appended at slot `wPartyCount` |
| Success, party full | `call SendNewMonToBox` (`.sendToBox`) | inserted at box slot 0, existing box shifted down |

Just before the branch the engine writes `wCapturedMonSpecies = wCurPartySpecies =
wEnemyMonSpecies` (reset to 0 at `.canUseBall`), and `wCurEnemyLevel = wEnemyMonLevel`.
`wCurItem` aliases `wCurPartySpecies`, so the ball id is gone by delivery time; the
ball is removed from the bag only after `.done`, past both return sites.

Pinned sites (bank 3, `expected_hex` from the clean ROMs):

| Title | party call | party return | box call | box return |
| --- | --- | --- | --- | --- |
| Red/Blue | `$5902` `CD2739` | `$5905` `18 21 CD8200 CDA467` | `$590A` `CDA467` | `$590D` `215759 FAF1D7 CB47` |
| Yellow | `$5661` `CD1C39` | `$5664` `18 21 CD8200 CDE866` | `$5669` `CDE866` | `$566C` `21B756 FAF0D7 CB47` |

Each call is located by `instruction_site` inside its own local-label scope, and the
generator asserts the return bytes (`jr .done`, then `.sendToBox`'s two calls; or
`ld hl, ItemUseBallText07` then `CheckEvent`) plus the exact source lines of every
branch above, `_AddPartyMon`'s wild-copy semantics, `SendNewMonToBox`'s tail, the
`wIsInBattle` value comment and all party/box/enemy struct offsets from the symbol
files. Delivering `wBattleType` values are NORMAL and SAFARI: OLD_MAN (and Yellow
PIKACHU) branch away, and Yellow's RUN is never assigned anywhere in the tree.

## What the decoder proves

`decode_capture({'destination','begin','end'}, variant, save_identity)` takes two
witnesses shaped like engine signals (`kind/frame/pc/bank/sp/point`) at the call
and its return. Each point carries the full 404-byte party, 1122-byte current box,
29-byte `wEnemyMon` battle struct, `wPlayerName`, `wPlayerID`, `wCurMap`,
`wIsInBattle`, `wBattleType`, `wCurPartySpecies`, `wCapturedMonSpecies`,
`wCurEnemyLevel`, `wMonDataLocation` and `wCurrentBoxNum`.

Refused unless all hold: exact site PC/bank per witness; same stack pointer and
non-decreasing frame; unchanged identity/map/battle/species/level/box context;
wild battle flag 1 and a delivering battle type; captured = current = enemy species
with canonical types; enemy HP ≥ 1; save identity matches; every party member
codec-valid and every box record well formed with no duplicate physical key.

Party path: `wMonDataLocation == 0`, count 0..5 → count+1, box unchanged, first
N members byte-identical, and the new slot equals what `_AddPartyMon` copies from
the enemy struct: species, HP, box level 0, status, player ID, exact level
experience, zero stat exp, enemy DVs, no PP Ups, level, the five enemy stats, and
the 11-byte `wPlayerName` as OT. The nickname is any codec-valid name.

Box path: party full and unchanged, box count 0..19 → count+1, species/records/OT/
nicknames all shifted down by one, and slot 0 equals what `SendNewMonToBox`
copies: the first 12 enemy bytes with the level as box level (catch rate byte 7
excluded for Yellow's Kadabra override), player ID, exact experience, zero stat
exp, enemy DVs and the enemy's current PP, with `wPlayerName` as OT.

Result: `{kind:'capture', destination, key, blob_hex (66 party / 55 box bytes),
location {kind, slot, box}, species_index, level, map_id, battle_type,
call_frame, return_frame}`. Species come from the cartridge struct and codec
profile only; randomized encounters and Yellow/Yellow need no species table.
`validate_receipt(payload, metadata)` additionally binds schema, artifact
`source_sha256`, variant, `context_generation` and `final_sha1` to admission.

## Tests

`tests/unit/test_gen1_capture_receipt.py`: 54 cases. Exact delivery on all three
titles at party slots 0 and 5 and box slots 0 and 19 (with a full 20-mon box on the
party path); a species sweep across the codec profile on both paths; Safari type
and status preservation; 28 hostile party variants (no delivery with the success
flag set, a different mon, a disturbed member, box changed, trainer/old-man/
Pikachu/unassigned battle types, PC/bank/kind/stack/frame, foreign save, reset
capture flag, key collision, wrong data location, zero HP, PP Ups, inexact
experience, wrong OT bytes, enemy struct drift, level/type mismatch, context drift,
extra/missing fields, bad destination); 7 hostile box variants (party not full, box
full, appended instead of inserted, wrong PP, stale box level, wrong OT, party
disturbed); admission binding faults; generator `--check` against pinned
source/ROMs; and the Lua artifact mirroring the JSON. Three initial hostile cases
were no-op mutations (a byte set to its existing value) and were corrected; the
decoder was not changed.

## Limits and the integration seam

- No live-engine run. The sites, bytes and copy semantics are source/ROM
  verified, but no BizHawk hook has yet fired at these PCs. A live gate should
  throw a ball in a wild battle on each title with 5 and 6 party members and
  compare the two witnesses to the decoder's expectations.
- The enemy-struct equality across the naming screen (all bytes except box
  level) is derived from source reading, not observed.
- Ball consumption is not proved here: it happens at `.done` after both
  return sites. A later bag witness must settle it; Safari throws consume
  `wNumSafariBalls` before the throw and never touch the bag.
- The box witness is the WRAM working copy of the current box. SRAM persistence
  and other boxes are the full-save path's concern.
- The `end` witness only arrives after the naming prompt; a reset during naming
  leaves an unpaired `begin`, which the root must treat as recovery, not delivery.
- Root wiring still needed: a Lua observer using `gen1_capture_sites.lua` (same
  shape as `gen1_engine_signal_data.lua`: `titles[variant].sites/addresses`
  plus `lengths` for the reads), launcher file inventory, journal pairing of
  begin/end across batches, and rule settlement (identity member, ball rule,
  encounter/area clauses) that this primitive deliberately does not perform.
