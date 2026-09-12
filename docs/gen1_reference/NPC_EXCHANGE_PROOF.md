# NPC in-game exchange receipts (Red / Blue / Yellow)

Source-qualified evidence that one NPC trade (`engine/events/in_game_trades.asm`) replaced
exactly one party mon with the engine's own construction for that table row, so the rule
coordinator can migrate the outgoing mon's logical identity onto the incoming one. This
module proves the exchange; it performs no migration and settles no rule.

Evidence classes used below: **source-cited** (pinned pret text, `GUARDS` in the generator),
**ROM-byte-verified** (clean-ROM bytes asserted by the generator and re-checked by the Lua
observer at install), **synthetic fixture** (unit tests; no emulator ran for this slice).

## Files

| Path | Role |
| --- | --- |
| `tools/gen_gen1_npc_exchange_sites.py` | Generator: source guards, ROM byte pins, census cross-check, `--check` |
| `data/games/gen1_rby/npc_exchange_sites.json` / `gen1_npc_exchange_sites.lua` | Generated site tables (schema `rby-npc-exchange-sites-v1`, sha256 pinned in every receipt) |
| `server/gen1_npc_exchange_receipt.py` | Decoder: `validate(receipt, ...) -> fact` (schema `rby-npc-exchange-receipt-v1`) |
| `lua/gen1_npc_exchange_observer.lua` | Read-only BizHawk observer, grant-observer surface (`peek/acknowledge/status/close`) |
| `tests/unit/test_gen1_npc_exchange_receipt.py`, `tests/unit/test_gen1_npc_exchange_observer.py` | Positive matrix, hostile refusals, regeneration, census cross-check, Lua == Python wire contract |

## The engine flow (source-cited)

Red line numbers; Yellow differs only where noted (`.cache/pret/pokered/engine/events/in_game_trades.asm`,
`.cache/pret/pokeyellow/engine/events/in_game_trades.asm`).

1. Map script stores the row index and dispatches: `ld a, TRADE_FOR_X` / `ld [wWhichTrade], a` /
   `predef DoInGameTradeDialogue` (e.g. `scripts/CeruleanTradeHouse.asm:15-17`; Route 11 uses
   `xor a ; TRADE_FOR_TERRY`, `scripts/Route11Gate2F.asm:13`; the Cinnabar trade room's Gramps
   `jr`s into the Beauty's dispatch, `scripts/CinnabarLabTradeRoom.asm:14-25`).
2. `DoInGameTradeDialogue` (`:10-46`) loads the 14-byte `TradeMons` row: give species, receive
   species, dialog set, 11-byte nickname (`data/events/trades.asm:1-9`).
3. `InGameTrade_DoTrade` (`:99-161`): party menu; `cp` the selected mon's species against
   `wInGameTradeGiveMonSpecies`, else `.tradeFailed` (`:110-115`); `wCurEnemyLevel` := the selected
   party mon's level (`:116-121`); completion flag set (`:122-126`, before any party change);
   `InGameTrade_PrepareTradeData` rolls two `Random` bytes into `wTradedEnemyMonOTID` (`:199-202`);
   the animation runs; `wWhichPokemon`/`wCurEnemyLevel` restored (`:136-139`).
4. `wCurPartySpecies` := receive species; `wMonDataLocation` := 0; `wRemoveMonFromBox` := 0;
   `call RemovePokemon` (`:140-145`) — the **remove** witness PC, party still intact.
5. `wMonDataLocation` := `$80`; `call AddPartyMon` (`:146-148`): player party, naming skipped
   (`engine/pokemon/add_mon.asm:43-45`), out of battle so DVs are two `Random` bytes and stats are
   fresh (`add_mon.asm:109-116`, `.calcFreshStats`), OT := `wPlayerName`, OT id := `wPlayerID`,
   exp := `CalcExperience(level)`, EVs 0, header types/catch rate, `WriteMonMoves`, max PP.
6. `InGameTrade_CopyDataToReceivedMon` (`:212-230`) overwrites slot `wPartyCount-1`: nickname :=
   table row, OT name := `InGameTrade_TrainerString` (`dname "<TRAINER>"` = `$5D` + `$50`×10,
   `constants/charmap.asm:25,12`), OT id := `wTradedEnemyMonOTID` (2 bytes).
7. Trade-evolution hook. Red/Blue: `callfar InGameTrade_CheckForTradeEvo`
   (`engine/events/evolve_trade.asm:8-16`) acts only when the received NAME starts with `G` or
   `SP`; none of the nine used rows does (ROM-byte-verified against `MonsterNames`). Yellow:
   `call InGameTrade_CheckForTradeEvo` (`pokeyellow …/in_game_trades.asm:236-259`) force-evolves
   KADABRA/GRAVELER/MACHOKE/HAUNTER with `wForceEvolution=1` and `LINK_STATE_TRADING`; B cannot
   cancel (`engine/movie/evolution.asm:151-154`). Only RICKY (Cubone → Machoke) qualifies.
8. `call ClearScreen` (`:151`) — the **return** witness PC, reached only after 5-7 returned.

### What the evolution rewrites (Yellow RICKY only; `pokeyellow/engine/pokemon/evos_moves.asm`)

`.checkTradeEvo` (`:76-84`) → `.doEvolution`; `CalcStats` with `b=1` into `wLoadedMonStats`
(`:186-189`); HP += new max − old max, whole 44-byte `wLoadedMon` copied back (`:200-210`);
`LearnMoveFromLevelUp` teaches only a move at exactly the current level that is not already
known (`:325-357`); `predef SetPartyMonTypes` rewrites the two type bytes (`set_types.asm`); the
species-list byte is rewritten (`:232-233`). Not touched: catch-rate byte (stays Machoke's 90,
not Machamp's 45), experience (Machoke and Machamp share growth 3), DVs, EVs, PP, level,
nickname (`RenameEvolvedMon` keeps a nickname that differs from the old species name — "RICKY"
≠ "MACHOKE"). Machamp's learnset equals Machoke's at every level, so the move set is unchanged;
the generator asserts this for levels 1-100.

## The incoming record, field by field (what the decoder requires)

| Field | Required value | Basis |
| --- | --- | --- |
| species (+0, species list) | `delivered_species` (= receive species; Machamp for Yellow RICKY) | source-cited |
| HP (+1) | fresh max HP of `delivered_species` at level with the record's DVs | source-cited |
| box level (+3) | 0 | source-cited |
| status (+4) | 0 | source-cited |
| types (+5,+6) | header types of `delivered_species` | source-cited |
| catch rate (+7) | header catch rate of `receive_species` (Yellow Kadabra override table applies) | source-cited |
| moves (+8..11) | `fresh_moves(receive_species, level)` (WriteMonMoves emulation) | source-cited |
| OT id (+12,+13) | `wTradedEnemyMonOTID` as captured at the remove witness | source-cited |
| exp (+14..16) | `experience_for_level(receive growth, level)` | source-cited |
| stat exp (+17..26) | all zero | source-cited |
| DVs (+27,+28) | free (random) | — |
| PP (+29..32) | max PP per move, no PP Ups | source-cited |
| level (+33) | the outgoing mon's level (= `wCurEnemyLevel` at remove) | source-cited |
| stats (+34..43) | `fresh_stats(delivered_species, DVs, level)` | source-cited |
| OT name (+44..54) | exactly `5D 50 50 50 50 50 50 50 50 50 50` | ROM-byte-verified |
| nickname (+55..65) | the row's 11 table bytes | ROM-byte-verified |

## Witnesses and receipt shape

```
{schema:"rby-npc-exchange-receipt-v1", source_sha256, variant, context_generation, physical_instance,
 final_sha1, source_id,
 call:   {frame, pc, bank, sp, a, point}      -- ld [wWhichTrade], a in the map script; A = trade index
 remove: {frame, pc, bank, sp, point}         -- call RemovePokemon in InGameTrade_DoTrade
 return: {frame, pc, bank, sp, point}}        -- call ClearScreen in InGameTrade_DoTrade
point = {party_hex(404), box_hex(1122), trainer_hex(11), player_id_hex(2), map_id, battle_flag,
         which_trade, which_pokemon, cur_species, cur_level, mon_location, remove_from_box,
         give_species, receive_species, traded_ot_id_hex(2), trade_nick_hex(11), current_box}
```

Pinned PCs (ROM-byte-verified): Red/Blue remove `1C:5C74` (`CD 1F 39`), return `1C:5C8A`
(`CD 0F 19`); Yellow remove `1C:5D0D` (`CD 14 39`), return `1C:5D1E` (`CD DD 16`). The generator
pins the whole `pop af … jr .tradeSucceeded` block, the species/level check, the OT-id source,
`InGameTrade_CopyDataToReceivedMon`, the trainer string, every used table record, each script's
selector bytes and its `3E 54 CD <Predef>` dispatch (predef id 84 in all three titles).

### Proved by the decoder

- Pins: schema, table sha256, variant, admission context, ROM sha1; unknown/unused rows refused.
- Sites: call PC/bank per source; remove/return PC/bank; `call.a == trade_index`; frames
  `call ≤ remove ≤ return`; `remove.sp == return.sp < call.sp` (both engine calls sit in
  `InGameTrade_DoTrade`'s frame, eight bytes below the script's through `Predef`).
- Identity: `wPlayerName`/`wPlayerID` equal the admitted save in all three points; `wIsInBattle == 0`;
  `wCurMap` equals the site's map in all three points; `wCurrentBoxNum` unchanged.
- Row globals at remove and return: `wWhichTrade`, give/receive species, `wCurPartySpecies`,
  `wInGameTradeMonNick` equal the pinned row; `wMonDataLocation == 0`, `wRemoveMonFromBox == 0`
  at remove; `wTradedEnemyMonOTID` unchanged between remove and return; `wCurEnemyLevel` equals
  the outgoing mon's level at both.
- Party: call and remove parties byte-identical; box byte-identical at all three points;
  `which_pokemon` inside the party; outgoing species == give species; after-party has the same
  count, `after[:-1]` equals the before records with the outgoing slot removed (RemovePokemon
  compaction), `after[-1]` is the incoming record satisfying the table above.
- Keys: incoming key absent from the before party and the current box; no key in both party and box.

### Read, not proved (this slice ran no emulator)

- That BizHawk's `event.on_bus_exec` fires at these PCs with `hLoadedROMBank` = `$1C` / the
  script bank, and that `emu.getregister("A")` names the accumulator (the grant observer's
  `B`/`C`/`F` usage is the precedent). Synthetic Lua test only.
- That nothing between the selector store and `call RemovePokemon` writes party bytes (party
  menu, `PrepareTradeData`, `InternalClockTradeAnim`): read from source, enforced by the decoder's
  call == remove party equality, so a violation would refuse rather than pass.
- Yellow RICKY's post-evolution record: derived from `evos_moves.asm`; no live capture.

### Exclusions

- Unused rows (R/B index 2; Yellow 2, 4, 6) have no script site and are refused as unknown sources.
- The completion flag (`wCompletedInGameTradeFlags`) is not evidence: it is set before the party changes.
- Player-to-player Cable Club trades are a different path (`engine/link/cable_club.asm`) and are not exchanges.

## UPR

`data/games/gen1_rby/upr_layout.json` `profiles[variant].settings` carries the trade table root
(`TradeTableOffset` == `TradeMons`; the generator asserts it), but `server/gen1_upr_scan.py`
validates no trade domain (its `run()` covers wild, statics, trainers, evolutions, starters, TMs,
items, serialization) and `server/gen1_upr_policy.py` never mentions `inGameTradesMod`. Under
"every changed byte must belong to an explicitly validated domain" (`gen1_upr_scan.py:5`), any
change to the table, the trainer string or the engine sequence fails admission. The exchange
operands are therefore canonical: the decoder accepts no `rom_bytes` override (`rom_bytes`
must be empty) and pins the clean bytes.

## Handoff API (what the coordinator does with a fact)

```python
from server.gen1_npc_exchange_receipt import validate
fact = validate(receipt, variant=..., identity={"ot_id": ..., "trainer_name": ...},
                context_generation=..., physical_instance=..., final_sha1=...)
# fact = {
#   kind: "npc_exchange", source_id: "npc:<map>:<row>", exchange_id: "exchange:<map>:<row>" (title-neutral),
#   trade_index, map_id, give_species, receive_species, delivered_species,
#   outgoing: {key, species_index, level, slot, blob_hex},
#   incoming: {key, species_index, level, slot, blob_hex, ot_id, nickname},
#   call_frame, remove_frame, return_frame, frame, receipt_digest }
```

The coordinator, not this module, must:

1. Call `identity_registry.migrate_many` with `before_key = fact["outgoing"]["key"]` and the
   incoming witness (`fact["incoming"]["key"]`, `blob_hex`, `slot`, `receipt_digest`,
   `return_frame`), so the outgoing mon's logical identity, link membership and pending-capture
   area continue under the incoming key. The incoming mon is never a fresh acquisition: it must
   not consume the current route's encounter, and `exchange_id` (not the map) is its provenance.
2. Move the outgoing mon's pending-capture/link area to the incoming key unchanged.
3. Treat `fact["incoming"]["slot"]` as the incoming mon's party slot at `return_frame`
   (always the last slot) and `fact["outgoing"]["slot"]` as the slot that was compacted away.
4. Order by `frame` alongside grant and capture facts; `receipt_digest` deduplicates.

## Limitations

- **Codec seam (must change an existing file to remove the workaround).** `PartyCodec._name`
  rejects `$5D`, so `validate_blob` refuses every NPC-traded mon's OT name. The decoder hands
  the codec a stand-in (`STANDIN`, "TRAINER" spelled out) for a slot whose OT bytes equal the
  pinned trainer string exactly, and compares raw bytes itself. Every other consumer of
  `PartyCodec` (engine signals, grant/capture receipts, initial observation) still refuses a
  party or box that contains such a mon; see SEAMS.
- Frame equality is allowed (`≤`): on Red/Blue the remove and return PCs can execute in one frame.
- The decoder does not model an interrupted trade (power loss between remove and return); no
  receipt is produced, and the next selector supersedes the open one in the observer.
- `display_name` renders the nickname for the fact; raw bytes stay in `blob_hex`.

## Seams (existing files that would need to change)

- `data/games/gen1_rby/party_codec.json` `name_bytes` (+ `content_sha256`) and the Lua mirror
  `lua/gen1_party_codec.lua`: admit `0x5D` (`<TRAINER>`) so `PartyCodec._name` accepts NPC-traded
  OT names; then delete `STANDIN`/`_masked` here.
- `server/gen1_acquisition_runtime.py` / `server/gen1_runtime.py`: route `rby-npc-exchange-receipt-v1`
  receipts to `gen1_npc_exchange_receipt.validate` and hand the fact to the identity migration.
- `lua/gen1_client_entry.lua`: instantiate `gen1_npc_exchange_observer` beside the grant observer
  with the same `owned`/`held` closures and publish its `peek()` rows under the same hold.

## Runtime settlement (`server/gen1_npc_exchange_runtime.py`)

Component `gen1-npc-exchanges`, one entry per player: `{sequence, operation_id, previous_operation_id,
pending: [{kind: "npc_exchange", fact, source_ref: {event, index}}], settled: [... + exchange_event,
member_id, inventory_operation, rule: "link"|"pending_capture"|"identity_only", area,
before_evidence_digest, evidence_digest], [frame_origin]}`. Every row keeps the exact journaled receipt
it was decoded from; `verify_journal` re-decodes it and re-derives the stable checkpoint.

A fact stays pending until the player's latest inventory checkpoint at/after `return_frame` shows the
incoming key in the party with the receipt's species, level and OT id and no longer shows the
outgoing key; a later checkpoint that still holds the outgoing key or lacks the incoming mon refuses.
Settlement is one `identity_registry.migrate_many` (before_key = outgoing key, before evidence =
sha256 of the outgoing 66-byte record, after = incoming key + sha256 of the stable record); the
LinkEntry half or `pending_captures[area][player]` holding the outgoing key is rewritten in place
(same area, same status) and `party_keys` follows. No `acquire`, no ordinal, no new pending capture. An
outgoing key with no logical identity is refused (the registry never mints members on migration).

Root seams (reserved files): `gen1_frame_runtime.bundle_boundary` must admit `bundle["exchanges"]`
(rows `{kind: "npc_exchange", receipt}`, at most 16); `gen1_frame_journal` calls
`stage_exchanges(runtime, stage, document, player, operation, facts, frame_origin=reference,
frame_request=message)` after `gen1_frame_acquisitions.stage` and folds `records` and
`result["exchange_digest"]` into the frame commit (mirroring `acquisition_digest` in the settled-frame
check and `gen1_observation_provenance` result requirements, plus an `elif` for
`npc_exchange_observation` in `_contained`); `Gen1RuntimeState.__init__` adds `verify_state`,
`Gen1Runtime.state` adds `verify_journal`. Until the codec admits `$5D`, a checkpoint holding an
NPC-traded mon cannot pass `gen1_initial_observation.inventory`; the runtime tests shim that glyph.
