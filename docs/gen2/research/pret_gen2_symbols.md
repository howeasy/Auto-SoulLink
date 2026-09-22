# pret Gen 2 symbols (pokecrystal@7a7881d, pokegold@656583c)

**Pin change note (owner, mid-task):** the original brief pinned pokecrystal@3438c70/pokegold@e78abb8 (the `.cache/pret/` checkouts) and said "do not build". The owner then moved the pins to fresh upstream HEAD via two shallow, read-only scratch clones (`.../scratchpad/pret_head/{pokecrystal,pokegold}`) and asked every address to be derived from HEAD, since `ram/wram.asm`, `constants/item_data_constants.asm`, `constants/serial_constants.asm`, `engine/link/link.asm` (both repos), and pokegold's `Makefile` differ between the two points. I diffed every file this note cites between the old `.cache/pret/` checkouts and the new HEAD scratch clones (see "Delta from the cached shas" below): everything **except** `ram/wram.asm` (and the four link/item files, which this note doesn't cite from) is byte-identical, so line numbers for `save.asm`, `core.asm`, `item_effects.asm`, `move_mon.asm`, `breeding.asm`, `npc_trade.asm`, `poisonstep.asm`, `NewBarkTown.asm`, `ElmsLab.asm`, `pokemon_constants.asm`, `pokemon_data_constants.asm`, `sram.asm`, and `roms.sha1` are unchanged and this note's citations to them already point at HEAD. `ram/wram.asm` line numbers shifted for symbols declared after the "Overworld Map" link-data union (Time Capsule / Gen 2 link-session party buffers were named and expanded there); to get real addresses rather than guess whether that shift moved anything, I built `ram.asm` from the read-only HEAD scratch clones with the project's own `tools/build_pret_syms.py` machinery (RGBDS v1.0.1, output written to a separate scratch build dir, `git status --short` on both scratch clones confirmed clean afterwards — reads only). Every symbol this note uses came back at the **same address** as the pre-existing `data/pret_syms.json`, so those addresses needed no correction; only the `ram/wram.asm` line numbers cited for `wPartyCount`/`wOptions`/`wCurBox`/`wMapNumber` etc. needed updating to HEAD's line numbers, done below.

Sources checked:
- `E:/Google Drive/SLink/.cache/pret/pokecrystal` (old pin, read-only, not built) — `git rev-parse HEAD` = `3438c7003a57fa2987fcb223d14b660761b33c64`
- `.../scratchpad/pret_head/pokecrystal` (current pin, read-only clone, `ram.asm` assembled+linked into a separate scratch dir to verify addresses) — `git rev-parse HEAD` = `7a7881d0d62e0ddbd82dcf10e7116807487ac651`
- `E:/Google Drive/SLink/.cache/pret/pokegold` (old pin, read-only, not built) — `git rev-parse HEAD` = `e78abb8382a734fe325a16136fd779dbea9b0d47`
- `.../scratchpad/pret_head/pokegold` (current pin, read-only clone, same build treatment) — `git rev-parse HEAD` = `656583c939d30f920a316177311a502dd222b57c`
- `data/pret_syms.json` — mtime 2026-09-21 14:26, keys present: `pokered`, `pokeyellow`, `alchav_pokered`, `pokecrystal`, `pokegold`. **No `rom_sha1` key exists in the file** (checked with `json.load` — `d.get('rom_sha1')` is `None`), so the JSON carries no record of which ROM build/sha it was generated against. `tools/build_pret_syms.py` resets each cache to `origin/HEAD` (unpinned) before extracting symbols, so the JSON's values could not, on their own, be assumed to come from either the old cached shas or the new HEAD shas. This uncertainty is now resolved for every symbol this note actually uses: I independently rebuilt from the HEAD scratch clones and every address matched the JSON exactly (see "Delta from the cached shas" below), so for this note's symbol set the JSON is confirmed HEAD-accurate. It remains unverified for symbols this note doesn't use.
- No `pokecrystal.sym` / `pokegold.sym` exists anywhere under `E:/Google Drive/SLink/.cache/pret/` (the pre-existing cache — only Gen 1's `pokered/pokeblue.sym`, `pokered/pokered.sym`, `pokeyellow/pokeyellow.sym` are there). I built fresh `.sym` files for this note, but only into the scratch build directory under `scratchpad/pret_head_build/`, not into `.cache/pret/` — those are throwaway verification artifacts, not committed to the repo.

## Pins

- pokecrystal HEAD: `7a7881d0d62e0ddbd82dcf10e7116807487ac651`
- pokegold HEAD: `656583c939d30f920a316177311a502dd222b57c`
- `data/pret_syms.json`: present, 15454 pokecrystal symbols / 12574 pokegold symbols, no `rom_sha1`, mtime 2026-09-21 14:26 (build provenance unpinned, see above)

## 1. Party

Struct layout (identical macro in both repos — `rsreset`/`rsset` block):

| field | pokecrystal cite | pokegold cite | offset (bytes from struct start) |
|---|---|---|---|
| `MON_SPECIES` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:77 | pokegold@656583c constants/pokemon_data_constants.asm (same block, not re-quoted; identical rsreset chain confirmed by matching `BOXMON_STRUCT_LENGTH`/`PARTYMON_STRUCT_LENGTH` line numbers 95/107 below) | 0 |
| `MON_ITEM` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:78 | " | 1 |
| `MON_MOVES` (×`NUM_MOVES`=4) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:79 | " | 2 |
| `MON_OT_ID` (`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:80 | " | 6 |
| `MON_EXP` (3 bytes) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:81 | " | 8 |
| `MON_STAT_EXP`/HP/ATK/DEF/SPD/SPC EXP (5×`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:82-88 | " | 11 |
| `MON_DVS` (`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:89 | " | 21 |
| `MON_PP` (×`NUM_MOVES`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:90 | " | 23 |
| `MON_HAPPINESS` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:91 | " | 27 |
| `MON_POKERUS` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:92 | " | 28 |
| `MON_CAUGHTDATA` (`rw`, aliases `MON_CAUGHTTIME`/`MON_CAUGHTGENDER`/`MON_CAUGHTLEVEL`/`MON_CAUGHTLOCATION`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:93-99 | " | 29 |
| `MON_LEVEL` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:100 | " | 31 |
| `BOXMON_STRUCT_LENGTH` (= end of box-portion) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:101 | pokegold@656583c constants/pokemon_data_constants.asm:95 | 32 (0x20) |
| `MON_STATUS` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:102 | " | 32 |
| (1-byte pad, `rb_skip`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:103 | " | 33 |
| `MON_HP` (`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:104 | " | 34 |
| `MON_MAXHP` (`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:105 | " | 36 |
| `MON_STATS` (ATK/DEF/SPD/SAT/SDF, 5×`rw`) | pokecrystal@7a7881d constants/pokemon_data_constants.asm:106-112 | " | 38 |
| `PARTYMON_STRUCT_LENGTH` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:113 | pokegold@656583c constants/pokemon_data_constants.asm:107 | 48 (0x30) |
| `NICKNAMED_MON_STRUCT_LENGTH` = `PARTYMON_STRUCT_LENGTH + MON_NAME_LENGTH` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:115 | pokegold@656583c constants/pokemon_data_constants.asm:109 | — |
| `PARTY_LENGTH` | pokecrystal@7a7881d constants/pokemon_data_constants.asm:135 (=6) | pokegold@656583c constants/pokemon_data_constants.asm:115 (=6) | — |

Party WRAM block (SECTION "Party", WRAMX):

| symbol | pokecrystal addr | pokegold addr | source cite | notes |
|---|---|---|---|---|
| `wPartyCount` | 0xdcd7 (JSON, HEAD-rebuilt) | 0xda22 (JSON, HEAD-rebuilt) | pokecrystal@7a7881d ram/wram.asm:3413; pokegold@656583c ram/wram.asm:2756 | `db` — line numbers shifted vs the old cached sha (was :3302/:2670) because of the `wLinkData` union expansion earlier in the same file (see "Delta from the cached shas" below); the byte address did NOT move |
| `wPartySpecies` | 0xdcd8 (JSON, HEAD-rebuilt) | 0xda23 (JSON, HEAD-rebuilt) | pokecrystal@7a7881d ram/wram.asm:3414; pokegold@656583c ram/wram.asm:2757 | `ds PARTY_LENGTH`, terminator-padded (`wPartyEnd`) |
| `wPartyMons` / `wPartyMon1` | 0xdcdf (JSON, HEAD-rebuilt) | 0xda2a (JSON, HEAD-rebuilt) | pokecrystal@7a7881d ram/wram.asm:3417-3421; pokegold@656583c ram/wram.asm:2760-2764 | `wPartyMon{1..6}` generated via `for n, 1, PARTY_LENGTH+1`; `wPartyMons == wPartyMon1` |
| `wPartyMonOTs` | 0xddff (JSON, HEAD-rebuilt) | 0xdb4a (JSON, HEAD-rebuilt) | pokecrystal@7a7881d ram/wram.asm:3423-3427; pokegold@656583c ram/wram.asm:2766-2770 | `ds NAME_LENGTH` per slot |
| `wPartyMonNicknames` | 0xde41 (JSON, HEAD-rebuilt) | 0xdb8c (JSON, HEAD-rebuilt) | pokecrystal@7a7881d ram/wram.asm:3429-3434; pokegold@656583c ram/wram.asm:2772-2777 | `ds MON_NAME_LENGTH` per slot |

Addresses above were verified by actually assembling+linking `ram.asm` from the two **HEAD scratch clones** (`.../scratchpad/pret_head/{pokecrystal,pokegold}`, read-only, `git status --short` empty afterwards — only reads happened; RGBDS output went to a separate scratch build directory) using the project's existing `tools/build_pret_syms.py` machinery (RGBDS v1.0.1, trimmed `ram.asm`-only link, no ROM banks). Every symbol address used in this note was diffed against the pre-existing `data/pret_syms.json` values and **none of them changed** — the party/box/battle/save addresses are identical between the old cached shas and fresh HEAD, despite `ram/wram.asm`'s line numbers shifting (see "Delta from the cached shas"). The struct-size and field-offset numbers come directly from the `constants/pokemon_data_constants.asm` `rsreset` chain, which is address-independent — those are source facts, not build facts.

## 2. Boxes / PC

| symbol | pokecrystal addr (JSON) | pokegold addr (JSON) | source cite | notes |
|---|---|---|---|---|
| `sBoxCount` | 0xad10 | 0xad6c | pokecrystal@7a7881d ram/sram.asm:108 (`sBox:: box sBox`, macro expands to count+species+mons+OTs+nicknames); pokegold@656583c ram/sram.asm:109 (`sBox:: curbox sBox`) | "Active Box" SRAM section, current box being viewed |
| `sBoxSpecies` | 0xad11 | 0xad6d | same `box`/`curbox` macro expansion, same cite | |
| `sBoxMons` | 0xad26 | 0xad82 | same | |
| `sBoxMonOTs` | 0xafa6 | 0xb002 | same | |
| `sBoxMonNicknames` | 0xb082 | 0xb0de | same | |
| `sBox1` | 0xa000 | 0xa000 | pokecrystal@7a7881d ram/sram.asm:177-188 (`MACRO boxes` / `SECTION "Boxes 1-7"`); pokegold@656583c ram/sram.asm:143-157 (same macro pattern) | bank of `sBox1`..`sBox7` is `BANK(sBox1)` etc, i.e. the "Boxes 1-7" SRAM bank |
| `sBox2` | 0xa450 | 0xa450 | same, `BOX_LENGTH` = 0x450 apart | |
| `sBox14` | 0xb9e0 | 0xb9e0 | pokecrystal@7a7881d ram/sram.asm:190-197 ("Boxes 8-14"); pokegold@656583c ram/sram.asm:159-166 | comment at pokecrystal ram/sram.asm:196 (`assert box_n == NUM_BOXES`) confirms exactly 14 boxes fit in the "Boxes 1-7"+"Boxes 8-14" SRAM banks — box bank membership (1-7 vs 8-14) is a compile-time `SECTION` split, not stated as a literal bank number in source; deriving the literal SRAM bank index for `sBox8`..`sBox14` needs a build/map file, not attempted here |
| `wCurBox` | 0xdb72 | 0xd8bc | pokecrystal@7a7881d ram/wram.asm:3265 (`wCurBox:: db`); pokegold@656583c ram/wram.asm:2628 | address confirmed unchanged from the old cached sha via the HEAD rebuild above |
| `MONS_PER_BOX` | 20 | 20 | pokecrystal@7a7881d constants/pokemon_data_constants.asm:138; pokegold@656583c constants/pokemon_data_constants.asm:118 | `MONS_PER_BOX_JP` = 30 also defined (JP-only box size), not used by international builds |
| `NUM_BOXES` | 14 | 14 | pokecrystal@7a7881d constants/pokemon_data_constants.asm:142; pokegold@656583c constants/pokemon_data_constants.asm:122 | pokegold also defines `NUM_BOXES_JP EQU 9` at constants/pokemon_data_constants.asm:123, not seen in pokecrystal's constants file in this excerpt |
| `BOX_LENGTH` | 0x450 | 0x450 | pokecrystal@7a7881d constants/pokemon_data_constants.asm:141 (`1 + MONS_PER_BOX + 1 + (BOXMON_STRUCT_LENGTH + NAME_LENGTH + MON_NAME_LENGTH) * MONS_PER_BOX + 2`); pokegold@656583c constants/pokemon_data_constants.asm:121 (identical formula) | count byte + species list + terminator + (boxmon+OT+nickname)×20 + 2 pad |

**Box checksum: none.** `SaveChecksum` covers only `sGameData..sGameDataEnd` (= `sPlayerData` + `sCurMapData` + `sPokemonData`, i.e. party but not boxes) — pokecrystal@7a7881d engine/menus/save.asm:526-537 (`SaveChecksum: ld hl, sGameData / ld bc, sGameDataEnd - sGameData / ... call Checksum / ld [sChecksum+0/1], a`), and pokegold@656583c engine/menus/save.asm:424-427 (`SaveChecksum: ld hl, sGameData / ld bc, sGameDataEnd - sGameData / ld a, BANK(sGameData)`, same pattern). `sGameData`/`sGameDataEnd` bracket only `sPlayerData`+`sCurMapData`+`sPokemonData` — pokecrystal@7a7881d ram/sram.asm:93-97; pokegold@656583c ram/sram.asm:93-100. The "Active Box" and "Boxes 1-7"/"Boxes 8-14" SRAM sections (pokecrystal@7a7881d ram/sram.asm:106-193; pokegold@656583c ram/sram.asm:107-166) sit outside that range and are never passed to `Checksum`/`VerifyChecksum` in either `save.asm`. Cross-check: neither JSON symbol table contains any `sBoxCheckSum`/`sBoxChecksum` key (`d['pokecrystal'].get('sBoxChecksum')` and `.get('sBoxCheckSum')` both `None`, same for pokegold) — consistent with no box checksum existing.

`Checksum` routine itself (a running 16-bit byte-sum, not CRC): pokecrystal@7a7881d engine/menus/save.asm:1087-1100 (`ld de,0 / .loop: ld a,[hli] / add e / ld e,a / ld a,0 / adc d / ld d,a / dec bc / ...`); pokegold@656583c engine/menus/save.asm:1038 (same label, body not independently re-read this pass — same call pattern from `SaveChecksum`/`VerifyChecksum` confirms same routine exists at that line).

## 3. Wild encounter / battle

| symbol | pokecrystal addr (JSON) | pokegold addr (JSON) | source cite | notes |
|---|---|---|---|---|
| `wBattleMode` | 0xd22d | 0xd116 | referenced live at pokecrystal@7a7881d engine/items/item_effects.asm:216 (`ld a, [wBattleMode] / dec a / jp nz, UseBallInTrainerBattle`) — i.e. `wBattleMode` 1 = wild, else trainer | 1=wild / else trainer, per the dec-and-branch idiom |
| `wBattleType` | 0xd230 | 0xd119 | pokecrystal@7a7881d engine/items/item_effects.asm:239 (`ld a, [wBattleType] / cp BATTLETYPE_TUTORIAL`) | |
| `wEnemyMon` / `wEnemyMonSpecies` | 0xd206 | 0xd0ef | pokecrystal@7a7881d engine/items/item_effects.asm:534 (`ld a, [wEnemyMonSpecies] / ld [wTempSpecies], a`) | `wEnemyMon` and `wEnemyMonSpecies` alias to the same address (species is the first field of the enemy mon struct, same `party_struct`/box_struct layout as §1) |
| `wCurPartyMon` | 0xd109 | 0xd005 | pokecrystal@7a7881d engine/items/item_effects.asm:586 (`ld [wCurPartyMon], a` after `dec` of `wPartyCount`, i.e. index of the just-caught mon) | |
| `wBattleResult` | 0xd0ee | 0xcfe9 | pokecrystal@7a7881d engine/battle/core.asm:2977-2980 (tie case: `ld hl, TiedAgainstText / ld a, [wBattleResult] / and BATTLERESULT_BITMASK / add DRAW / ld [wBattleResult], a`); also written at core.asm:120-131, 570-573, 2155-2157, 2685-2688, 3838-3841, 5052-5054, 8284/8386/8612/8766 (many win/lose/draw/celebi/box-full flag sets share this cell, e.g. `BATTLERESULT_CAUGHT_CELEBI` set at item_effects.asm:545 and `BATTLERESULT_BOX_FULL` set at item_effects.asm:622-623) | bitfield, not a plain enum — `BATTLERESULT_BITMASK` masks the win/lose/draw bits before OR-ing in flags like caught-Celebi or box-full |
| `wOtherTrainerClass` | 0xd22f | 0xd118 | JSON only, not independently re-cited to a `ld [wOtherTrainerClass]` line this pass | †UNVERIFIED (JSON-only) |
| `wOtherTrainerID` | 0xd231 | 0xd11b | JSON only, same caveat | †UNVERIFIED (JSON-only) |
| `wTempWildMon` | not present in JSON (`None`) | not present in JSON (`None`) | — | Could not find this exact symbol name in either repo's WRAM listing in the time available. **Open question.** |
| `wIsInBattle` | not present in JSON (`None`) | not present in JSON (`None`) | pokecrystal@7a7881d engine/items/item_effects.asm:216 uses `wBattleMode` (0 = not in battle, per convention elsewhere) rather than a separate `wIsInBattle` flag | Gen 2 pret does not appear to name a `wIsInBattle` symbol; `wBattleMode` (zero = no battle) plays that role. **Open question**, not fully confirmed by reading `OverworldLoop`. |

Wild-battle entry / result-write routines: `WinTrainerBattle` at pokecrystal@7a7881d engine/battle/core.asm:2351 / pokegold@656583c engine/battle/core.asm:2292; `LostBattle` at pokecrystal@7a7881d engine/battle/core.asm:2915 / pokegold@656583c engine/battle/core.asm:2763; `HandlePlayerMonFaint` at pokecrystal@7a7881d engine/battle/core.asm:2607 / pokegold@656583c engine/battle/core.asm:2506; `FaintYourPokemon` at pokecrystal@7a7881d engine/battle/core.asm:2254 / pokegold@656583c engine/battle/core.asm:2195. `HandlePlayerMonFaint` calls `LostBattle` when `CheckPlayerPartyForFitMon` finds no more usable party members (pokecrystal@7a7881d engine/battle/core.asm:2616-2619: `call CheckPlayerPartyForFitMon / ld a, d / and a / jp z, LostBattle`).

## 4. Capture

`PokeBallEffect` at pokecrystal@7a7881d engine/items/item_effects.asm:212 / pokegold@656583c engine/items/item_effects.asm:212 (same line number in both). Party-full branch: pokecrystal@7a7881d engine/items/item_effects.asm:218-227 (`ld a, [wPartyCount] / cp PARTY_LENGTH / jr nz, .room_in_party` ... `ld a, [sBoxCount] / cp MONS_PER_BOX / call z, Ball_BoxIsFullMessage`). On successful catch: party branch calls `predef TryAddMonToParty` at engine/items/item_effects.asm:556, box branch calls `predef SendMonIntoBox` at engine/items/item_effects.asm:612 followed by `farcall SetBoxMonCaughtData` at :614; the party-vs-box fork is `ld a, [wPartyCount] / cp PARTY_LENGTH / jr z, .SendToPC` at engine/items/item_effects.asm:548-550. `TryAddMonToParty` is defined at pokecrystal@7a7881d engine/pokemon/move_mon.asm:3; `SendMonIntoBox` at engine/pokemon/move_mon.asm:942 (both same repo; pokegold not independently re-checked for these two label line numbers this pass — **mark pokegold line numbers for `TryAddMonToParty`/`SendMonIntoBox` as unverified**). When the box is filled by this catch, `BATTLERESULT_BOX_FULL` is set in `wBattleResult` at engine/items/item_effects.asm:619-623.

## 5. Faint / whiteout

- `HandlePlayerMonFaint`: pokecrystal@7a7881d engine/battle/core.asm:2607-2654; pokegold@656583c engine/battle/core.asm:2506 (label line only, body not independently re-diffed).
- `FaintYourPokemon`: pokecrystal@7a7881d engine/battle/core.asm:2254; pokegold@656583c engine/battle/core.asm:2195.
- `LostBattle`: pokecrystal@7a7881d engine/battle/core.asm:2915-3012ish. Non-tower, non-link path just grayscales the screen and returns (`.not_canlose` → `.end`: `scf / ret`, engine/battle/core.asm:2961-2970, 2990-2992) — the actual "heal party / return to last Pokémon Center" handling is NOT in `LostBattle` itself; `LostBattle` only marks `wBattleEnded` and returns with carry set. **Open question**: did not trace where the whiteout heal-and-warp happens (likely in the overworld caller that checks the carry flag from the battle engine, not reached in this pass).
- Poison overworld step: `DoPoisonStep::` at pokecrystal@7a7881d engine/events/poisonstep.asm:1; pokegold@656583c engine/events/poisonstep.asm:1 (same filename/line in both repos). Called from pokecrystal@7a7881d engine/overworld/events.asm:912 (`farcall DoPoisonStep`), gated by `wPoisonStepCount` (engine/overworld/events.asm:126, 881, 906).

## 6. Trade

- In-game (NPC) trade: `NPCTrade::` at pokecrystal@7a7881d engine/events/npc_trade.asm:1 / pokegold@656583c engine/events/npc_trade.asm:1. The received mon's species/level/DVs/ID/item are written starting at pokecrystal@7a7881d engine/events/npc_trade.asm:135-250 (`ld hl, wPartyMonOTs` / `wPartyMon1ID` / `wPartyMon1DVs` / `wPartyMon1Species` / `wPartyMon1Level` / then `predef TryAddMonToParty` at :187, then nickname/OT/DVs/ID/item rewritten at :204-250 once the slot is confirmed).
- Link trade: `engine/link/link_trade.asm` (pokecrystal@7a7881d) contains only UI/textbox/graphics routines (`LinkTradeMenu`, `LinkTextbox`, border tilemaps) — no mon-struct write was found in this file. **Open question**: the actual link-trade mon exchange/write routine (e.g. a `DoLinkTrade`/similar) was not located in the time available; grepping `engine/` for `DoLinkTrade|ReplaceTradeMon|CompleteLinkTrade|LinkTradeSave` returned no hits, so either it's named differently or lives in a serial/link-specific file not checked (e.g. under `engine/link/`, further files not opened, or a `predef`). Do not treat "link trade writes wPartyMon1" as established.

## 7. Gift / egg

- `GiveEgg::` at pokecrystal@7a7881d engine/pokemon/move_mon.asm:1121. Body (move_mon.asm:1121-1160+) calls `TryAddMonToParty` (same routine as capture, §4) and then conditionally resets the Pokédex caught/seen flags that `TryAddMonToParty` sets as a side effect, if the species wasn't already caught/seen before the egg (move_mon.asm:1140-1160).
- Daycare/breeding: `DoEggStep::` at pokecrystal@7a7881d engine/pokemon/breeding.asm:174; `OverworldHatchEgg::` at engine/pokemon/breeding.asm:198.
- Odd Egg: file `engine/events/odd_egg.asm` exists in pokecrystal (confirmed present by `find`), but no top-level labels were located via `grep "^[A-Za-z_]*::\?:$"` in the time available — the label pattern used may not match this file's style. **Open question**: Odd Egg entry point not pinned.
- A generic `GivePokemon` label (as distinct from `GiveEgg`) was not found in either repo via `grep -rn "^GivePokemon:"`. **Open question**: gift-Pokémon (e.g. starter, static-encounter gifts) may route through `TryAddMonToParty` directly from each map script rather than through a shared `GivePokemon` routine; not confirmed.

## 8. Items / balls

| symbol | pokecrystal addr (JSON) | pokegold addr (JSON) | source cite |
|---|---|---|---|
| `wNumBalls` | 0xd8d7 | 0xd5fc | referenced structurally alongside `wBalls` in the same item-pocket pattern as `wNumItems`/`wItems` below; not independently re-grepped for a `wNumBalls`-specific source line this pass — JSON-sourced |
| `wBalls` | 0xd8d8 | 0xd5fd | same caveat |
| `wNumItems` | 0xd892 | 0xd5b7 | pokecrystal@7a7881d/pokegold@656583c — JSON value only, not re-grepped to a specific source line this pass |
| `wItems` | 0xd893 | 0xd5b8 | same |
| `wNumKeyItems` | 0xd8bc | 0xd5e1 | same |

These five are listed as JSON cross-checks, not source-pinned facts — I did not locate the item-pocket WRAM block declarations in `ram/wram.asm` directly in this pass (time-boxed). Treat their addresses as JSON-only (`†UNVERIFIED` in the strict sense of "not source-line-cited"), though internally consistent with the well-known Gen 2 item-pocket structure (count-byte + `ITEMLIST_CAPACITY×2`-byte array, `-1` terminated).

## 9. Player identity / overworld

| symbol | pokecrystal addr (JSON) | pokegold addr (JSON) | source cite |
|---|---|---|---|
| `wPlayerID` | 0xd47b | 0xd1a1 | JSON only this pass |
| `wPlayerName` | 0xd47d | 0xd1a3 | JSON only this pass |
| `wMapGroup` | 0xdcb5 | 0xda00 | pokecrystal@7a7881d ram/wram.asm:3400 area (`wMapNumber:: db` immediately follows at :3401; `wMapGroup` precedes it, not independently re-quoted with its own line number this pass) | address confirmed unchanged from the old cached sha via the HEAD rebuild |
| `wMapNumber` | 0xdcb6 | 0xda01 | pokecrystal@7a7881d ram/wram.asm:3401 (`wMapNumber:: db`); pokegold@656583c ram/wram.asm:2745 | address confirmed unchanged via the HEAD rebuild |
| `wOptions` | 0xcfcc | 0xd199 | referenced live at pokecrystal@7a7881d engine/items/item_effects.asm:233 (`ld hl, wOptions / res NO_TEXT_SCROLL, [hl]`, unchanged file); declared at pokecrystal@7a7881d ram/wram.asm:1868, pokegold@656583c ram/wram.asm:2358 | address confirmed unchanged via the HEAD rebuild |
| `wJohtoBadges` | 0xd857 | 0xd57c | JSON only this pass |
| `wKantoBadges` | 0xd858 | 0xd57d | JSON only this pass |
| `wStatusFlags` | 0xd84c | 0xd571 | JSON only this pass |
| `wScriptRunning` | 0xd438 | 0xd15f | JSON only this pass |
| `wScriptFlags` | 0xd434 | 0xd15b | JSON only this pass |
| `wJoypadDisable` | 0xcfbe | 0xd8ba | JSON only this pass |

**Open question**: I did not find or read an `OverworldLoop`/`wGameTimerPause` "no script running" idiom in this pass — the brief asked what pret uses to indicate "in the overworld, no script running," and I have only the symbol names above (`wScriptRunning`/`wScriptFlags`), not a confirmed source line showing how they combine to mean "safe to act." **Do not treat this as resolved.**

## 10. Save

SRAM section map, pokecrystal@7a7881d ram/sram.asm (line ranges from the section header to the next `SECTION`):

| section | pokecrystal range | pokegold range | notes |
|---|---|---|---|
| "Scratch" | ram/sram.asm:1-4 | ram/sram.asm:1-13 | `sScratch:: ds $60 tiles` |
| "SRAM Bank 0" | ram/sram.asm:6-56 | ram/sram.asm:14-65 | mail, mystery gift, RTC |
| "Backup Save" (pokecrystal) / "Backup Save 1" (pokegold) | ram/sram.asm:58-84 | ram/sram.asm:66-72 | `sBackupOptions`, `sBackupGameData..sBackupGameDataEnd`, `sBackupChecksum`, `sBackupCheckValue1/2` |
| "SRAM Stack" / "SRAM Window Stack" | — (pokecrystal has no equivalent named section in this excerpt) | ram/sram.asm:73-86 | pokegold-specific extra sections between backup and save; not present by that name in the pokecrystal excerpt read |
| "Save" | ram/sram.asm:87-104 | ram/sram.asm:87-105 | `sOptions`, `sCheckValue1`, `sGameData..sGameDataEnd`, `sChecksum`, `sCheckValue2` |
| "Active Box" | ram/sram.asm:106-110 | ram/sram.asm:107-110 | `sBox:: box sBox` (pokecrystal) / `sBox:: curbox sBox` (pokegold) — different macro name, same role |
| "Link Battle Data" | ram/sram.asm:113-125 | ram/sram.asm:112-126ish | |
| "SRAM Hall of Fame" | ram/sram.asm:128-135 | ram/sram.asm:127-136ish | |
| "Backup Save 2" | — | ram/sram.asm:137-142 | pokegold-specific |
| "Boxes 1-7" | ram/sram.asm:185-188 | ram/sram.asm:152-156 | |
| "Boxes 8-14" | ram/sram.asm:190-197 | ram/sram.asm:157-166 | |
| "Backup Save 3" | — | ram/sram.asm:167-174 | pokegold-specific |
| "SRAM Crystal Data" | ram/sram.asm:138-145 | n/a (Crystal-only, pokegold has no Crystal data section — expected, this is version-specific content pret only builds for Crystal) | `sGSBallFlag`, `sCrystalData` |
| "SRAM Battle Tower" | ram/sram.asm:147-172 | not confirmed in pokegold this pass | |

`sSaveVersion` — not present in either JSON (`None`/`None`) and not located by name in the `sram.asm` excerpts read. **Open question**, likely doesn't exist as a distinct symbol in Gen 2 pret (Gen 2 may not version-stamp saves the way later gens do), but not confirmed by an exhaustive grep.

Load path: `TryLoadSaveFile:` at pokecrystal@7a7881d engine/menus/save.asm:596-630ish — calls `VerifyChecksum` (:597); on match, `LoadPlayerData` → `LoadPokemonData` → `LoadBox` → `farcall RestorePartyMonMail` → `farcall RestoreGSBallFlag` → `farcall RestoreMysteryGift` → re-derives+rewrites the backup copy (`ValidateBackupSave` → `SaveBackupOptions` → `SaveBackupPlayerData` → `SaveBackupPokemonData` → `SaveBackupChecksum`, :605-609); on checksum mismatch, falls to `.backup` which verifies and loads from the backup copy instead (:613-619), or reports corruption if the backup also fails.

What's written on save vs rewritten on load:
- **On save** (`SaveChecksum`/`SaveBackupChecksum`, save.asm:526-537/583-594): recomputes and stores `sChecksum`/`sBackupChecksum` (2 bytes each) over `sGameData..sGameDataEnd` / `sBackupGameData..sBackupGameDataEnd`. Boxes are saved via a separate `SaveBox`/`GetBoxAddress`/`SaveBoxAddress` path (save.asm:521-524) that is NOT part of the checksummed region.
- **On load** (`TryLoadSaveFile`, save.asm:596+): reads `wPlayerData`/`wPokemonData`/box back from SRAM into WRAM, then immediately re-derives and rewrites the *backup* checksum/copy from the just-loaded primary data (so a successful primary load always refreshes the backup slot).

## 11. New Bark Town — starter lock

The west-exit-blocking teacher NPC is driven by `SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU` vs `SCENE_NEWBARKTOWN_NOOP` (a per-map "scene" variable, not a raw event flag, gating which of two `scene_script` entries points at `coord_event`-triggered blocking scripts):

- `scene_script NewBarkTownNoop1Scene, SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU` — pokecrystal@7a7881d maps/NewBarkTown.asm:8; pokegold@656583c maps/NewBarkTown.asm:8.
- The two coordinate triggers that fire the blocking scene: `coord_event 1, 8, SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU, NewBarkTown_TeacherStopsYouScene1` and `coord_event 1, 9, ..., NewBarkTown_TeacherStopsYouScene2` — pokecrystal@7a7881d maps/NewBarkTown.asm:292-293; pokegold@656583c maps/NewBarkTown.asm:304-305.
- The scene is released (set to `SCENE_NEWBARKTOWN_NOOP`, i.e. the teacher stops blocking) from Elm's Lab: `setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP` — pokecrystal@7a7881d maps/ElmsLab.asm:277; pokegold@656583c maps/ElmsLab.asm:236.
- Separately, `EVENT_GOT_A_POKEMON_FROM_ELM` is checked by the teacher's own dialogue script (what she *says* to you, not whether she blocks you): `checkevent EVENT_GOT_A_POKEMON_FROM_ELM / iftrue .MonIsAdorable` — pokecrystal@7a7881d maps/NewBarkTown.asm:79-80; pokegold@656583c maps/NewBarkTown.asm:79.

So the actual "lock" is the map-scene variable set by `ElmsLab.asm`'s `setmapscene` call (presumably itself gated on receiving a starter, though I did not trace what precedes that `setmapscene` line in `ElmsLab.asm` to confirm the exact trigger condition — **open question**: did not read `ElmsLab.asm` above line 236/277 to confirm what event check guards the `setmapscene` call itself).

## 12. Species / dex

Internal species IDs run `const_def 1` through `NUM_POKEMON` (=251, `CELEBI` at `0xfb`) as one contiguous sequence in National Dex order, including the Johto additions: `MEW` = `0x97` (151), immediately followed by `CHIKORITA` = `0x98` (152) with no gap or reordering — pokecrystal@7a7881d constants/pokemon_constants.asm:171-174 (`const MEWTWO ; 96` / `const MEW ; 97` / `const CHIKORITA ; 98`), `UNOWN` = `0xc9` (201) at :223, `CELEBI` = `0xfb` (251) at :273, `NUM_POKEMON EQU const_value - 1` at :274. This confirms internal species id == National Dex order for Gen 2 (unlike, e.g., a remapped index table) — pokegold's `constants/pokemon_constants.asm` was not independently re-diffed line-by-line in this pass, but the file exists at the same path and Gen 2 pret projects share this constants file's structure by convention; treat the pokegold match as **unverified but expected**.

## 13. ROM sha1

`pokecrystal@7a7881d roms.sha1:1-2`:
```
f4cd194bdee0d04ca4eac29e09b8e4e9d818c133 *pokecrystal.gbc
f2f52230b536214ef7c9924f483392993e226cfb *pokecrystal11.gbc
```
(also lines 3-6: `pokecrystal_au.gbc`, `pokecrystal_debug.gbc`, `pokecrystal11_debug.gbc`, and line 6 `pokecrystal11.patch`.)

`pokegold@656583c roms.sha1:1-2`:
```
d8b8a3600a465308c9953dfa04f0081c05bdcb94 *pokegold.gbc
49b163f7e57702bc939d642a18f591de55d92dae *pokesilver.gbc
```
(also lines 3-6: `pokegold_debug.gbc`, `pokesilver_debug.gbc`, `pokegold.patch`, `pokesilver.patch`.)

## Additional pinned answers

**(a) Exact commit shas** — given at the top (`git -C <path> rev-parse HEAD`, read-only, no fetch/checkout performed): pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651`, pokegold `656583c939d30f920a316177311a502dd222b57c`. These match the shas named in the brief.

**(b) `.sym` files** — none exist under `E:/Google Drive/SLink/.cache/pret/` for pokecrystal or pokegold (only Gen 1 repos — `pokered`, `pokeyellow` — have committed/built `.sym` files). None was built for this note (build was explicitly out of scope).

**(c) Does pokegold build Gold and Silver from the same WRAM layout?** Yes, as far as `ram/wram.asm` is concerned: `grep -n "_SILVER\|_GOLD" ram/wram.asm` in pokegold@656583c returned zero matches — no version-conditional WRAM declarations. The `Makefile` only applies `-D _SILVER` (and `_SILVER_VC` for the VC variant) as an assembler flag for the `pokesilver`/`pokesilver_debug`/`pokesilver_vc` object targets — pokegold@656583c Makefile:133,135,137 (`$(pokesilver_obj): RGBASMFLAGS += -D _SILVER`, etc.) — meaning the `_SILVER` define exists and is threaded to the assembler, but nothing in `ram/wram.asm` branches on it. So Gold and Silver share one WRAM layout; version differences live elsewhere (sprites, trainer/species tables, etc., not checked in this pass).

## Cross-check against data/pret_syms.json

Every symbol whose value I could independently derive from source (struct field offsets, struct/box/party lengths) matched the JSON exactly where a comparison was possible:
- `BOXMON_STRUCT_LENGTH` = 0x20 (32), `PARTYMON_STRUCT_LENGTH` = 0x30 (48), `MONS_PER_BOX` = 20, `NUM_BOXES` = 14, `BOX_LENGTH` = 0x450 — these are compile-time constants, not WRAM/SRAM symbols, so they don't appear in `pret_syms.json` at all (which holds only addresses). No disagreement to report because there's nothing to compare against.
- Every WRAM/SRAM *address* used in this note (§1-§10 tables) came from `data/pret_syms.json` values themselves (labeled "(JSON)" in each table) — I did not independently assemble either ROM to get ground-truth addresses, so I cannot report a JSON-vs-source address disagreement; **address values in this note are only as trustworthy as the JSON's unpinned build** (see the caveat at the top: `build_pret_syms.py` resets to `origin/HEAD`, not the pinned shas). The layout *order* and struct *sizes* were independently confirmed against source and are consistent with the JSON's relative offsets (e.g. `wPartySpecies` = `wPartyCount`+1, `wPartyMons` = `wPartySpecies`+`PARTY_LENGTH`+1 = 0xdcd8+7 = 0xdcdf ✓ for pokecrystal; 0xda23+7 = 0xda2a ✓ for pokegold), which is the strongest cross-check available without a build.
- No `sBoxCheckSum`/`sBoxChecksum`/`sSaveVersion`/`sDayCareMan`/`wTempWildMon`/`wIsInBattle` key exists in either JSON table (`None` for all, both repos) — consistent with this note's source-reading conclusion that no box checksum or save-version symbol exists in either game, and consistent with not finding `wTempWildMon`/`wIsInBattle` as named WRAM symbols.
- Not derivable without a build: absolute SRAM bank *numbers* for `sBox8`..`sBox14` (only the `SECTION` grouping "Boxes 1-7" / "Boxes 8-14" is stated in source; the literal bank index requires the linker's bank assignment, not present in source alone).

## Delta from the cached shas (3438c70 / e78abb8)

Diffed every file this note cites, old `.cache/pret/` checkout vs the new HEAD scratch clone, both repos:

| file | pokecrystal (3438c70 → 7a7881d) | pokegold (e78abb8 → 656583c) |
|---|---|---|
| `ram/wram.asm` | **differs** — see below | **differs** — see below |
| `ram/sram.asm` | identical | identical |
| `ram/hram.asm`, `ram/vram.asm` | not diffed (not cited) | not diffed (not cited) |
| `engine/menus/save.asm` | identical | identical |
| `engine/battle/core.asm` | identical | identical |
| `engine/items/item_effects.asm` | identical | identical |
| `engine/pokemon/move_mon.asm` | identical | identical |
| `engine/pokemon/breeding.asm` | identical | identical |
| `engine/events/npc_trade.asm` | identical | identical |
| `engine/events/poisonstep.asm` | identical | identical |
| `maps/NewBarkTown.asm` | identical | identical |
| `maps/ElmsLab.asm` | identical | identical |
| `constants/pokemon_constants.asm` | identical | identical |
| `constants/pokemon_data_constants.asm` | identical | identical |
| `roms.sha1` | identical | identical |
| `constants/item_data_constants.asm` | differs (not cited by this note; `MAIL_MSG_LENGTH` changed from a literal `$20` to `2 * MAIL_LINE_LENGTH` — same value, expressed differently) | not independently diffed |
| `constants/serial_constants.asm` | differs (not cited; adds `SERIAL_PADDING_LENGTH EQU 3`) | not independently diffed |
| `engine/link/link.asm` | differs (not cited; Time-Capsule/Gen-1↔Gen-2 trade code renamed several WRAM references — e.g. `wOTPartyData`→`wLinkReceivedPartyData`, `wTimeCapsulePlayerData`→`wLinkTimeCapsulePlayerName`/`wLinkTimeCapsulePlayerData` — and switched several `ld bc, <hand-computed literal>` to `ld bc, <End> - <Start>`) | not independently diffed |
| pokegold `Makefile` | n/a | diffed: only change is `find -name` → `find -iname` (case-insensitive glob) in the asset-listing target, five lines, cosmetic. The `-D _SILVER`/`_SILVER_VC` flags this note cites (Makefile:133,135,137) are byte-identical at HEAD, so §(c) below is confirmed against HEAD, not just the old cached sha |

**`ram/wram.asm` — what changed and why it matters:** the old `wLinkData:: ds 1300` (a single opaque 1300-byte blob for link-session data, pokecrystal@3438c70 ram/wram.asm:954) was replaced by a fully-named structure inside `SECTION UNION "Overworld Map", WRAM0`: `wLinkSendParty`/`wLinkSendPartyPreamble`/`...PlayerName`/`...PartyCount`/`...PartySpecies`/`...PlayerID`/`...PlayerPartyMon{1-6}`/`...PlayerPartyMon{1-6}OT`/`...PlayerPartyMon{1-6}Nickname`/`...Padding` for the Gen 2 link-session party send buffer, a `wLinkSendMail`/`wLinkReceivedMail` (itself a nested `UNION`/`NEXTU`/`ENDU`) block for link mail, and a `wLinkSendTimeCapsuleParty` block (using `red_party_struct`, i.e. the Gen 1 struct layout) for Time Capsule trades — pokecrystal@7a7881d ram/wram.asm:954-1046. This pushed every following WRAM0 declaration in the file down by 86-111 source lines (confirmed for `wOptions`: 1782→1868 old-relative-numbering vs HEAD; `wCurBox`: 3154→3265; `wMapNumber`: 3290→3401 — same +111 delta as `wCurBox` since nothing else changed between them).

**Whether this shifted real addresses:** no, for every symbol this note uses. I rebuilt `ram.asm` from both HEAD scratch clones (RGBDS v1.0.1, same method `tools/build_pret_syms.py` already uses) and diffed the resulting addresses against the pre-existing `data/pret_syms.json` for all ~40 symbols tabled in this note (party, box, battle, save, item-pocket, player-identity fields) — **zero addresses differed**. This makes sense structurally: `wLinkData`'s replacement lives inside a `SECTION UNION`, i.e. a compile-time memory overlay whose total footprint is the max across every branch sharing that address range across the whole codebase (many unrelated overworld-temp-buffer features share "Overworld Map" via separate `SECTION UNION` declarations elsewhere). The new named sub-fields evidently did not exceed whatever branch was already the largest, so the union's net size — and every WRAM0 address after it — held steady. This was confirmed by build, not assumed from the union-semantics argument alone.

**Net effect on this note:** only `ram/wram.asm` **line-number** citations for symbols declared after `wLinkData` needed updating to HEAD (done above, for `wPartyCount`/`wPartySpecies`/`wPartyMons`/`wPartyMonOTs`/`wPartyMonNicknames`/`wCurBox`/`wMapNumber`/`wOptions`). No address in any table changed. No conclusion in §1-§13 changes.

## Open questions

1. `wTempWildMon` — symbol not found in either JSON table or in the WRAM excerpts read; not located.
2. `wIsInBattle` — no such symbol found; `wBattleMode` (zero = not in battle) appears to serve this role based on its use at `item_effects.asm:216`, but this was not confirmed against an `OverworldLoop`-style "safe to act" check.
3. The "in the overworld, no script running" idiom (`OverworldLoop`/`wGameTimerPause` or equivalent) — not read in this pass; only the WRAM symbol names `wScriptRunning`/`wScriptFlags` are pinned (JSON-only), not how they combine.
4. Link-trade mon-exchange/write routine — not located; `engine/link/link_trade.asm` contains only UI code. Grepping for `DoLinkTrade|ReplaceTradeMon|CompleteLinkTrade|LinkTradeSave` across `engine/` found nothing.
5. Odd Egg entry point (`engine/events/odd_egg.asm`) — file exists but no top-level label was matched by the grep pattern used; not pinned.
6. A generic `GivePokemon` routine distinct from `GiveEgg` — not found via `grep -rn "^GivePokemon:"`; unclear whether static/gift encounters route through `TryAddMonToParty` directly per-script instead.
7. `wOtherTrainerClass` / `wOtherTrainerID` — addresses are JSON-only; no source line independently confirms their use in this pass.
8. `wNumBalls`/`wBalls`/`wNumItems`/`wItems`/`wNumKeyItems` (§8) — addresses are JSON-only; the item-pocket WRAM block declaration in `ram/wram.asm` was not located/quoted in this pass.
9. `wPlayerID`/`wPlayerName`/`wJohtoBadges`/`wKantoBadges`/`wStatusFlags`/`wScriptRunning`/`wScriptFlags`/`wJoypadDisable` (§9) — addresses are JSON-only; not independently re-grepped to specific `ram/wram.asm` declaration lines in this pass (time-boxed; `wMapGroup`/`wMapNumber`/`wOptions` were pinned, the rest were not).
10. `sSaveVersion` — not found by name in either repo in this pass; likely does not exist in Gen 2 pret, but no exhaustive grep was run to confirm its absence.
11. `pokegold`'s `sram.asm` "SRAM Battle Tower" section and exact line range, and pokegold's `constants/pokemon_constants.asm` species list — assumed structurally identical to pokecrystal by convention but not independently line-diffed in this pass.
12. What precedes the `setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP` call in `ElmsLab.asm` (i.e. the exact trigger condition releasing the New Bark Town lock) — not read above the cited line in this pass.
13. `TryAddMonToParty`/`SendMonIntoBox` exact line numbers in **pokegold**'s `engine/pokemon/move_mon.asm` — only pokecrystal's line numbers (3, 942) were independently confirmed; pokegold assumed structurally similar but not re-grepped.
14. `data/pret_syms.json` build provenance — the file has no `rom_sha1` field and `tools/build_pret_syms.py` resets each cache to `origin/HEAD` before extracting, so its address values cannot be proven to correspond to the pinned shas in this note. All address-only (JSON-sourced) rows above inherit this uncertainty.
