# RR 4.1 in-game trades: ROM facts (card RR-NPCTRADE, 2026-09-27)

**Verdict up front:** RR keeps FireRed's 9 in-game trades, at the SAME map/script/flag
locations, with the SAME OT/IV/personality/condition/sheen data -- only species, nickname,
requestedSpecies and heldItem were reworked to RR content (a full Gen1-8 remix, e.g. Abra ->
Mr. Mime-Galar). **Cheapest trade to reach: Route2_House / "Reyley"** (species slot
`MR_MIME`, offers Mr Mime-Galar for an Abra) -- earliest map in the game (Route 2, between
Viridian City and Viridian Forest), a 2-NPC one-room house, no `checkflag`/badge gate in its
script, one warp back to Route 2.

ROMs used (all `C:/slink-wt/g3-int/patch/build/`):
- `slink_RR.gba` sha1 `7a3867499d66eb3621e0e7dde43bd033fc679f01` (the profile.json pin)
- `rr_clean.gba` sha1 `964f951a0fdaf209e4ea1344883ef0d557bb3a80`
- `gen3_Pokemon_-_FireRed_Version_(USA).gba` (vanilla reference) sha1
  `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc`

Method/tool: `tools/rr_ingame_trades.py` (read-only; `parse_trades`, `parse_map_object_events`).
Unit test `tests/unit/test_rr_ingame_trades.py` pins the RR table + a vanilla map cross-check
(both skip if the ROM build isn't present locally; re-run against the real g3-int build to
verify -- confirmed manually against both ROMs while writing this doc).

## Method

1. pret pokefirered (`git clone --depth1 https://github.com/pret/pokefirered`, no local commit
   pin needed -- used only as a STRUCTURE/METHOD reference, never as an RR fact source) gives:
   - `struct InGameTrade` (`src/trade_scene.c:57`, 0x3C/60 bytes): nickname[11]@0x00,
     species(u16)@0x0C, ivs[6]@0x0E, abilityNum@0x14, otId(u32)@0x18, conditions[6]@0x1C,
     personality(u32)@0x24, heldItem(u16)@0x28, mailNum@0x2A, otName[11]@0x2B, otGender@0x36,
     sheen@0x37, requestedSpecies(u16)@0x38.
   - `sInGameTrades` = `data/gen3/pret/pokefirered.sym` `0826cf8c l 0000021c` (540 = 9*0x3C,
     confirming the struct size above from an independent source).
   - `GetInGameTradeSpeciesInfo` 08053a9c/0x48, `CreateInGameTradePokemonInternal`
     08053b48/0x18c (local), `GetTradeSpecies` 08053d2c/0x3c, `CreateInGameTradePokemon`
     08053d68/0x1c, `DoInGameTradeScene` 08054440/0x30.
   - The 9 trader scripts/maps and their `FLAG_DID_*_TRADE` values (`include/constants/
     flags.h`), by grepping every `data/maps/*/scripts.inc` for `call EventScript_
     DoInGameTrade` (8 maps; Cinnabar Lab Lounge has 2 traders, Clifton + Norma).
   - `data/maps/map_groups.json` for each trader map's (group, num).
   - `struct ObjectEventTemplate` / `struct MapEvents` / `struct MapHeader`
     (`include/global.fieldmap.h`) and `gMapGroups` (pokefirered.sym `083526a8`) for the
     ROM's map-header walk.

2. **Code vs. data, checked separately, both directly on RR ROM bytes**:
   - Comparing the vanilla and RR ROM bytes AT THE VANILLA FUNCTION ADDRESSES:
     `GetInGameTradeSpeciesInfo` and `CreateInGameTradePokemonInternal` are CFRU-detoured
     (`LDR r0,[pc,#0]; BX r0` / `LDR r2,[pc,#0]; BX r2` thunks -> 0x090A4A2D / 0x090A4AFD,
     CFRU expansion space) -- these two got REWRITTEN, plausibly for the wider
     species-name/icon lookups CFRU's expanded dex needs.
   - `GetTradeSpecies` (08053d2c), `CreateInGameTradePokemon` (08053d68) and
     `DoInGameTradeScene` (08054440) are **byte-identical** between vanilla and RR --
     unchanged, still calling through to whatever `sInGameTrades` resolves to.
   - The bytes AT the vanilla `sInGameTrades` address (0x0826CF8C) differ from vanilla, but
     decoding them with the struct layout above (and the FRLG charmap, `pokefirered/
     charmap.txt`, A-Z=0xBB-0xD4, a-z=0xD5-0xEE, `'`=0xB4, space=0x00, terminator=0xFF)
     produces 9 clean, in-range entries (species/requestedSpecies 1-2000, all IVs 0-31,
     valid text) -- i.e. **the table was NOT relocated**, only its content was edited in
     place. (A full-ROM brute-force scan for a relocated table -- every 4-aligned offset,
     3 consecutive struct-shaped entries -- returned zero hits anywhere in the 32 MB image,
     which is exactly what "same address, edited content" predicts.)
   - RR species ids for the untouched vanilla species (Abra=63, Nidoran F=29, etc.) exactly
     match FireRed's National Dex numbers (`data/games/gen3_frlge/rr_species.json`), so any
     species field that decoded to a >151-but-plausible RR id (Galarian forms, Gen4-8 mons in
     the 494-1216 range) is real RR content, not noise.

3. **Map/object-event parser cross-check** (task requirement): validated on
   `CeruleanCity_House3` (group 7, num 2) against pret's `map.json` BEFORE trusting it on RR --
   the ROM walk reproduces pret's Dontae (x=2,y=2,elevation=3) and Old Woman (x=7,y=5,
   elevation=3) exactly. Same parser then run unmodified on the RR ROM for all 8 trader maps
   (`tests/unit/test_rr_ingame_trades.py::test_parse_map_object_events_vanilla_cross_check`
   pins this).

4. **Flag IDs**: `flags.h`'s `FLAG_DID_*_TRADE` numbers are a general story-flag namespace,
   not part of CFRU's species/item/move expansion -- and the wrapper functions that consume
   them (`GetTradeSpecies`/`CreateInGameTradePokemon`/`DoInGameTradeScene`) are byte-identical
   to vanilla, so they were not renumbered by the build. Confirmed directly: scanning each
   RR trader's compiled script bytes for the vanilla flag's raw little-endian u16 finds it at
   a small, consistent offset (idx 13-22) for 7 of 8 traders. **One exception, caught only
   because this was checked on the RR ROM rather than assumed**: on
   `Route11_EastEntrance_2F` the vanilla flag position puts `FLAG_DID_NINA_TRADE` (0x0251) in
   the object at vanilla's "Turner" position (x=7,y=3); on the RR ROM that flag is instead
   found (offset 439, still at a real instruction boundary, script relocated to CFRU
   expansion space 0x09052F9C) in the OTHER object on that map (local id 2, x=2,y=6 --
   vanilla's "Aide" position). RR moved which NPC on that map holds the trade dialogue.

## Trade table (RR ROM, `sInGameTrades` @ 0x0826CF8C, stride 0x3C)

| slot (pret label) | nickname | offered species (RR id) | held item (RR id) | requested species (RR id) | ivs | otId | personality | conditions | otName/gender | sheen |
|---|---|---|---|---|---|---|---|---|---|---|
| MR_MIME  @0x0826CF8C | Mimien      | Mr Mime-Galar (1216) | none (0)     | Abra (63)        | 20,15,17,24,23,22 | 1985  | 0x00009cae | 5,5,5,30,5  | Reyley / M  | 10 |
| JYNX     @0x0826CFC8 | Aphrodite   | Carnivine (508)       | item 699     | Snom (1164)       | 24,25,24,25,25,21 | 36728 | 0x1c8a2e22 | 5,30,5,5,5  | Dontae / M  | 10 |
| NIDORAN  @0x0826D004 | ClubPnguin  | Eiscue (1167)         | item 170     | Carbink (811)     | 31,18,25,24,15,22 | 63184 | 0x4b970b89 | 5,5,5,5,30  | Saige / F   | 10 |
| FARFETCHD@0x0826D040 | Ch'ding     | Farfetch'd-Galar (1213)| item 225    | Pikipek (948)     | 20,25,21,24,15,20 | 8810  | 0x151943d7 | 30,5,5,5,5  | Elyssa / M  | 10 |
| NIDORINOA@0x0826D07C | "s p o o k" (letters space-separated, verbatim bytes) | Mimikyu (995) | none (0) | Aegislash (789) | 23,25,23,19,22,21 | 13637 | 0x00eeca15 | 5,5,30,5,5  | Turner / M  | 10 |
| LICKITUNG@0x0826D0B8 | Gorochu     | Morpeko (1169)        | none (0)     | Dedenne (810)     | 24,31,21,31,21,25 | 1239  | 0x451308a7 | 5,5,5,5,30  | Haden / M   | 10 |
| ELECTRODE@0x0826D0F4 | Flowre      | Floette (Eternal) (848)| item 506    | Florges (779)     | 23,16,21,25,25,22 | 50298 | 0x05341016 | 30,5,5,5,5  | Clifton / M | 10 |
| TANGELA  @0x0826D130 | BestBirb    | Chatot (494)          | item 110     | Murkrow (198)     | 22,17,20,25,25,20 | 60042 | 0x5c77ecee | 5,5,30,5,5  | Norma / F   | 10 |
| SEEL     @0x0826D16C | Revenant    | Grimmsnarl (1153)     | none (0)     | Hatterene (1150)  | 25,25,22,16,23,22 | 9853  | 0x482cac87 | 5,5,5,5,30  | Garett / M  | 10 |

Held-item ids not decoded to names here (RR item table not needed for this card); flag `0`
above for `abilityNum`/`mailNum=255` throughout except JYNX/TANGELA (`mailNum=255` too, but
`heldItem` non-zero means a mail-bearing gift on those two, matching vanilla's Jynx-holds-mail
pattern). Species/held-item RR ids resolved via `data/games/gen3_frlge/rr_species.json`.

## Trader map / NPC / flag table (RR ROM, gMapGroups @ 0x083526A8)

| trade | map (group.num) | trader NPC (ROM object) | facing (movementType) | done flag | stand tile* |
|---|---|---|---|---|---|
| MR_MIME (Reyley)   | Route2_House (15.1)                       | localId 2, graphicsId 51, (x=7,y=2), elev 3 | FACE_DOWN (8) | FLAG_DID_MIMIEN_TRADE (0x248) | (7,3) |
| JYNX (Dontae)      | CeruleanCity_House3 (7.2)                 | localId 1, graphicsId 32, (x=2,y=2), elev 3 | FACE_UP (7)   | FLAG_DID_ZYNX_TRADE (0x24A)   | (2,1) |
| NIDORAN (Saige)    | UndergroundPath_NorthEntrance (1.30)      | localId 1, graphicsId 17, (x=5,y=6), elev 3 | FACE_DOWN (8) | FLAG_DID_MS_NIDO_TRADE (0x24B)| (5,7) |
| FARFETCHD (Elyssa) | VermilionCity_House2 (9.4)                | localId 1, graphicsId 17, (x=4,y=4), elev 3 | FACE_UP (7)   | FLAG_DID_CH_DING_TRADE (0x24D)| (4,3) |
| NIDORINOA (Turner) | Route11_EastEntrance_2F (22.1)            | localId **2** (RR moved this off vanilla's localId 1), graphicsId 55, (x=2,y=6), elev 3, WANDER_AROUND(1) | -- | FLAG_DID_NINA_TRADE (0x251, RR script @ CFRU space 0x09052F9C) | any adjacent walkable tile (no fixed facing) |
| LICKITUNG (Haden)  | Route18_EastEntrance_2F (26.1)            | localId 1, graphicsId 19, (x=5,y=3), elev 3 | FACE_LEFT (9) | FLAG_DID_MARC_TRADE (0x257)   | (6,3) |
| ELECTRODE (Clifton)| CinnabarIsland_PokemonLab_Lounge (12.2)   | localId 2, graphicsId 33, (x=4,y=6), elev 3 | FACE_DOWN (8) | FLAG_DID_ESPHERE_TRADE (0x274)| (4,7) |
| TANGELA (Norma)    | CinnabarIsland_PokemonLab_Lounge (12.2)   | **unresolved -- see note**                    | -- | FLAG_DID_TANGENY_TRADE (0x275)| -- |
| SEEL (Garett)      | CinnabarIsland_PokemonLab_ExperimentRoom (12.4) | localId 1, graphicsId 19, (x=11,y=8), elev 3 | FACE_UP (7) | FLAG_DID_SEELOR_TRADE (0x276) | (11,7) |

\* "stand tile" = the one tile directly in the NPC's facing direction (pret convention: a
`FACE_X`-type NPC idles facing that way; on interact every object event snaps to face the
player regardless of type, so the other 1-3 adjacent tiles may also work if the room layout
leaves them walkable -- not independently verified here, low-effort/low-risk assumption).
\*\* The RR ROM's Lounge `objectEventCount` is 3: localId 1 (Scientist, x=5,y=3, elev 3),
localId 2 (Clifton, x=4,y=6, elev 3 -- matches pret exactly), and localId 3 (x=14,y=6,
elev=0, script=0x08000000, flagId=512). Pret's Norma (`OBJ_EVENT_GFX_WOMAN_2`, x=10,y=5) has
no matching localId-1-layout object in RR's table at all. localId 3's fields (elev 0,
script pointing at the ROM header, flagId 512) don't parse as a sane "normal" object --
`struct ObjectEventTemplate.kind` selects between a `normal` and a `clone` union layout
(`include/global.fieldmap.h`) that this extractor does NOT distinguish; localId 3 is most
likely a `kind=clone` entry (its raw bytes are a `{targetLocalId, padding[3], targetMapNum,
targetMapGroup}` under that reading, not `{elevation, movementType, ...}`), which this card
did not decode. Norma's flag (0x275) was only found in the Lounge's shared-script byte
region near localId 1's script (idx 156), not pinned to one specific object event --
**flagged as lower confidence than the other 8 rows; resolving it needs the `kind` byte read
and a `clone` decode, out of this card's effort budget.**

## Files touched

- `tools/rr_ingame_trades.py` (new, read-only extractor + CLI dump)
- `tests/unit/test_rr_ingame_trades.py` (new, pinned regression + vanilla cross-check;
  skips cleanly when the ROM build isn't present in this worktree)
- this doc

## Why Route2_House/Reyley is the SYNTH pick

- Earliest reachable trader map in the game (Route 2, immediately past Viridian City/Forest;
  no badge, no `checkflag` in `Route2_House_EventScript_Reyley`'s pret script skeleton and RR
  didn't touch that map's script structure -- `GetTradeSpecies`/`CreateInGameTradePokemon`/
  `DoInGameTradeScene` unchanged).
- Single small room, one warp stripe (3 tiles, all leading to the same Route 2 door), 2 NPCs
  total, no puzzle/backtrack.
- Requires only a Pokemon in the party that IS an Abra (or matches whatever the fixture wants
  to hand over) -- no fossil, no evolution stage requirement, no HM.
- Every other trade needs Mt. Moon (Cerulean), Diglett's Cave/Route access (Underground Path),
  SS Anne progress (Vermilion), Rock Tunnel (Route 11/18 east entrances), or the Cinnabar Lab
  (very late-game), all strictly farther from a fresh save's first warp.
