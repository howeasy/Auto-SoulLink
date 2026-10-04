# Gen 2 RAM / structure map — Polished Crystal v3.2.3 vs vanilla pokecrystal

Reference for porting SLink's Gen 2 Lua client (`lua/gen2/*`) onto **Polished Crystal v3.2.3**.

## Sources

| Role | Artifact |
|---|---|
| Vanilla symbol table (authoritative for the shipped client) | `data/games/gen2_crystal/profile.json` → `titles.crystal.{ram, ram_bank, hram, sram_bank, constants}` |
| Vanilla provenance | `profile.json:4-14` — `pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`, `rom_sha1 f4cd194b…`, `sym_sha256 cb16279e…` |
| Vanilla literals the client hardcodes | `lua/gen2/writes.lua:35-41` (`W.SYM`), `lua/gen2/reads.lua:221`, `lua/gen2/reads.lua:491-493` |
| Vanilla cross-check syms (in repo) | `data/gen2/pokecrystal.sym`, `data/gen2/crystal_slink.sym` |
| Polished symbol table | `F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym` (rgblink, `BB:AAAA Name`) |
| Polished source | `F:/slink-work/cache/polished/src/{macros/ram.asm, ram/wram0.asm, ram/wramx.asm, ram/sram.asm, ram/hram.asm, constants/*}` |

### How to read the Polished `.sym`

rgblink reports **WRAM bank `00` = `$C000-$DFFF`**, **banks `01`-`06` = `$D000-$DFFF`**, **bank `07` = `$C000-$DFFF`**, and **HRAM as bank `00` with `$FFxx` addresses**. The WRAM region of the sym is lines **63508-69843**; OAM is 69844+; HRAM is ~70046+.

### Bank numbering is NOT the same between the two games

Vanilla pokecrystal maps SRAM through the classic 4-bank arrangement and SLink's client hardcodes that assumption. Polished relabels the same logical banks:

| vanilla profile `sram_bank` | meaning | Polished section | Polished sym bank |
|---|---|---|---|
| `0` | save backup + mail + Battle Tower | `SRAM Bank 0`, `Backup Save`, `SRAM Mail`, `SRAM Battle Tower` | `00` |
| `1` | **save** + Hall of Fame + box metadata | `Save`, `SRAM Hall of Fame`, `Box metadata` | `01` |
| `2` | boxes 1-7 | `PokeDB bank 1A/1B/1C` | `01` / `00` / `01` (see §1.4) |
| `3` | boxes 8-14 | `PokeDB bank 2A/2B/2C` | `03` / — / `01` |

`reads.lua:274` hardcodes `bank ~= 1` for the active box, and `reads.lua:294-297` computes `expected_bank = index < NUM_BOXES/2 and 2 or 3`. Both are vanilla-only.

---

## 1. Symbol tables

### 1.1 `writes.lua` `W.SYM` — the four hardcoded literals

`lua/gen2/writes.lua:37-41`:

| symbol | vanilla bank:addr | Polished name | Polished bank:addr | verdict | note |
|---|---|---|---|---|---|
| `wCurPlayerMove` | `00:C6E3` | `wCurPlayerMove` | `00:C540` | moved | `-0x1A3`. Battle struct moved down; whole WRAM0 battle block re-laid out. |
| `wCurOTMon` | `00:C663` | `wCurOTMon` | `00:C4DD` | moved | `-0x186`. Not a constant delta vs `wCurPlayerMove` (`-0x11D`), because Polished inserts `wMirrorHerbPendingBoosts` and other fields inside the block. |
| `wOTPartyCount` | `01:D280` | `wOTPartyCount` | `01:D283` | moved | `+3`. Polished drops the 8-byte pad vanilla has between `wOTPlayerID` and `wOTPartyCount`. |
| `wOTPartyDataEnd` | `01:D42C` | `wOTPartyDataEnd` | `01:D42F` | moved | `+3`. Block length is 428 bytes in **both** games — see §2.4, the contents differ. |

Evidence: Polished `wCurPlayerMove`/`wCurOTMon` at `.sym:64052` / `.sym:63909`; `wOTPartyCount` `.sym:66118`; `wOTPartyDataEnd` `.sym:66429`. Vanilla addresses from `data/gen2/pokecrystal.sym:56101-56102,56330` (`wOTPlayerID d276`, `wOTPartyCount d280`, `wOTPartyDataEnd d42c`) and `profile.json` for `wCurPlayerMove`/`wCurOTMon`.

**Critical:** `writes.lua:94` derives `ot_species = ot_block + 1`. In vanilla those 7 bytes are `wOTPartySpecies1` (a real `$FF`-terminated species list — `pokecrystal.sym:56103`). In Polished the same 7 bytes are `wMirrorHerbPendingBoosts` (`F:/slink-work/cache/polished/src/ram/wramx.asm:760-762`, measured `.sym:66119 wOTPartyCount`, `.sym:66120 wOTPartyMon1` → 7-byte gap). Writing an enemy species list there **clobbers Mirror Herb state**. Polished has no enemy species list at all; species must come from each `party_struct`'s own `Species` byte.

### 1.2 Symbols the Gen 2 client reads/writes today

Vanilla column = `profile.json` `ram` + `ram_bank`. Polished column = measured `.sym`.

| vanilla symbol | vanilla bank:addr | Polished name | Polished bank:addr | verdict | note |
|---|---|---|---|---|---|
| `wPartyCount` | `01:DCD7` | `wPartyCount` | `01:DCCE` | moved | `-9`. Polished `wPlayerData` shrank 9 bytes (`wramx.asm:874-1323`). |
| `wPartySpecies` | `01:DCD8` | *(absent)* | — | absent | Polished has `ds 7 ; unused` (`wramx.asm:1358`). Byte offsets still hold, so `reads.lua:221-227` passes its geometry gate on an **unnamed, meaningless** range. |
| `wPartyMons` / `wPartyMon1` | `01:DCDF` | `wPartyMons` / `wPartyMon1` | `01:DCD6` | moved | `-9`. |
| `wPartyMonOTs` | `01:DD4F` | `wPartyMonOTs` | `01:DDF6` *(derived)* | moved | `wPartyMons + 6×48`. Not read from the `.sym` — UNVERIFIED. |
| `wPartyMonNicknames` | `01:DD9A` | `wPartyMonNicknames` | `01:DE38` *(derived)* | moved | `+ 6×11` further. Not read from the `.sym` — UNVERIFIED. |
| `wPartyMon1Status` | `01:DCFF` | `wPartyMon1Status` | `01:DCF6` | moved | struct offset `+32` in **both** games — unchanged. |
| `wPartyMon1HP` | `01:DD01` | `wPartyMon1HP` | `01:DCF8` | moved | `+34` both. |
| `wCurBox` | `01:DB72` | `wCurBox` | `01:DB7A` | moved | Polished `NUM_BOXES` = 20, not 14 (`pokemon_data_constants.asm:304`), so the `reads.lua:244` `>= c.NUM_BOXES` gate changes meaning. |
| `wBattleMode` | `01:D22D` | `wBattleMode` | `01:D233` | moved | |
| `wScriptRunning` | `01:D438` | `wScriptRunning` | `01:D437` | moved | `-1`. Safe-state predicate still exists. |
| `wMapGroup` | `01:DCB5` | `wMapGroup` | `01:DCAC` | moved | `-9`. |
| `wMapNumber` | `01:DCB6` | `wMapNumber` | `01:DCAD` | moved | `-9`. |
| `wPlayerID` | `01:D47B` | `wPlayerID` | `01:D478` | moved | `-3`. |
| `wPlayerName` | `01:D47D` | `wPlayerName` | `01:D47B` | moved | `-2`. |
| `wTextboxFlags` | `00:CFCF` | `wTextboxFlags` | `00:CFF4` | moved | corrected 2026-10-04: both cells previously read `01:CFF4`/same (wrong bank); vanilla data/gen2/pokecrystal.sym:55480, Polished sym:65521. |
| `wNumItems` | `01:D892` | `wNumItems` | `01:D827` | moved | `-0x77`. Pocket capacities all changed — §3.2. |
| `wItems` | `01:D893` | `wItems` | `01:D828` | moved | `ds MAX_ITEMS*2+1`, MAX_ITEMS 20→75. |
| `wNumKeyItems` | `01:D8BC` | `wNumKeyItems` | `01:D7FF` | moved | vanilla cell corrected 2026-10-04 (`test_polished_ram_doc.py`: profile `titles.crystal.ram.wNumKeyItems` = `$D8BC`, RAM.md said `$D8C8`). The Polished NAME is unverified: Polished has no `wNumKeyItems` symbol, and `$01:D7FF` is unlabelled space between `wPokemonJournalsEnd` ($01:D7F5) and `wKeyItems` ($01:D800). |
| `wKeyItems` | `01:D8BD` | `wKeyItems` | `01:D800` | moved | `ds NUM_KEY_ITEMS+1`, NUM_KEY_ITEMS 27 (vanilla `MAX_KEY_ITEMS` 25). |
| `wNumBalls` | `01:D8D7` | `wNumBalls` | `01:D90B` | moved | MAX_BALLS 12→25. |
| `wBalls` | `01:D8D8` | `wBalls` | `01:D90C` | moved | |
| `wTMsHMs` | `01:D859` | `wTMsHMs` | `01:D7F5` | moved | Both are `flag_array`; Polished uses `NUM_TMS + NUM_HMS` (`wramx.asm:1006`), vanilla `NUM_TM_HM` = 57. |
| `wBattleMon` / `wBattleMonSpecies` | `00:C62C` | `wBattleMon` / `wBattleMonSpecies` | `00:C4A5` | moved | struct layout also changed — §2.3. |
| `wBattleMonMoves` | `00:C62E` | `wBattleMonMoves` | `00:C4A7` | moved | |
| `wBattleMonDVs` | `00:C632` | `wBattleMonDVs` | `00:C4AB` | moved | |
| `wBattleMonPP` | `00:C634` | `wBattleMonPP` | `00:C4B0` | moved | **struct offset changed** `+8` → `+11`. |
| `wBattleMonHP` | `00:C63C` | `wBattleMonHP` | `00:C4B8` | moved | offset `+16` → `+19`. |
| `wBattlePlayerAction` | `01:D0EC` | `wBattlePlayerAction` | `01:D0F4` | moved | |
| `wJohtoBadges` / `wKantoBadges` | `01:D8B7` / `01:D8B8` | `wJohtoBadges` / `wKantoBadges` | `01:D7EE` / `01:D7EF` | moved | Both 8 badges; `wBadges` = 2 bytes, `flag_array` layout. |
| `wEventFlags` | `01:DA72` | `wEventFlags` | `01:DA5A` | moved | `flag_array NUM_EVENTS`, NUM_EVENTS = 2303 → 288 bytes. |
| `wMonType` | `01:CF9F` | `wMonType` | *(see UNVERIFIED)* | UNVERIFIED | not measured. |
| `wJoypadDisable` | *(not in profile `ram`)* | `wJoypadDisable` | *(not measured)* | UNVERIFIED | `copilot-instructions.md` says it reads `00` in overworld and with START open — it is **not** the safe-state predicate; `wScriptRunning` is. |

### 1.3 `hram` (100 keys, vanilla profile lines 269-369)

Polished HRAM is contiguous `00:FF00`-`00:FFFE`. Measured anchors:

| symbol | vanilla | Polished | verdict |
|---|---|---|---|
| `hROMBank` | `FF87` | `00:FF87` | same |
| `hVBlank` | `FF8D` | `00:FF8D` | same |
| `hVBlankCounter` | `FF8E` | `00:FF8E` | same |
| `hMapEntryMethod` | `FF90` | `00:FF90` | same |
| `hScriptVar` | `FF85` | `00:FF85` | same |
| `hHours` | `FF8A` | `00:FF8A` | same |

The vanilla profile's `hram` block also contains `h*` keys that are **not HRAM at all** — `hLastTalked`, `hMapAnims`, `hTileAnimFrame`, `hSystemBooted`, `hCGB`, `hCGBPalUpdate`, `hDMATransfer`, `hSGB`, `hMobile`, `hBattleTurn`, `hJoyIgnore`-style names and the whole `hMG*`/`hMath*` group are HRAM in pokecrystal, and their Polished counterparts were not individually measured. **UNVERIFIED** — regenerate with the recipe below before relying on any `h*` row.

### 1.4 `sram_bank` (365 keys) — the boxes are gone

Vanilla `profile.json:2198-2563` describes `sBox1..sBox14` (banks 2/3), `sBoxMon1..20` + per-field aliases, `sBoxCount`, `sBoxMons`, `sBoxSpecies`, `sBoxEnd`, plus save/backup/mail/HoF/BattleTower symbols.

Polished **replaces the entire box storage format**:

- `F:/slink-work/cache/polished/src/ram/sram.asm:138-148` — `sNewBox1..sNewBox20` (`newbox` macro: 20 `Entries` flag bytes + 20-bit `Banks` flag array + 9-byte name + theme) and a backup copy. No per-mon records here.
- `sram.asm:150-177` — `sBoxMons1A/2A/1B/2B/1C/2C`, each a `pokedb` of `savemon_struct` records (49 bytes), split across sections A (167), B (28), C (12). Measured `.sym:50810 sBoxMons1A = 02:A000`, `.sym:50849 sBoxMons1AMon1End = 02:A031` (49 bytes), `.sym:57158 sBoxMons1AMon167End = 02:BFF7`.
- `NUM_BOXES` = 20, `MONDB_ENTRIES` = 207, `MIN_MONDB_SLACK` = 10 (`pokemon_data_constants.asm:299-304`).

Verdict for the whole `sBox*` family: **`different-layout`**, and for the vanilla per-field aliases (`sBoxMon1HPExp`, `sBoxMon1DVs`, …) **`absent`**.

Save-region symbols that *do* survive, with byte-identical anchors (important — Polished is save-compatible):

| symbol | vanilla | Polished | evidence |
|---|---|---|---|
| `sCheckValue1` | `A007` | `01:A007` | `sram.asm:38` `assert sCheckValue1 == $a007`; `.sym:49229` |
| `sCheckValue2` | `AD0F` | `01:AD0F` | `sram.asm:39` `assert sCheckValue2 == $ad0f`; `.sym:49238` |
| `sChecksum` | `AD0C` | `01:AD0D` | `sram.asm:32`; `.sym:49237` |
| `sGameData` / `sPlayerData` | `A008` | `01:A008` | `.sym:49230-49231` |
| `sBackupGameData` | `B208` | `00:B208` | `.sym:49220` |

New in Polished: `sSaveVersion` (`dw`, `00:ABE2`), `sUpgradeStep`, `sWritingBackup`, `sRTCStatusFlags`, `sLuckyNumberDay`, `sLuckyIDNumber` (`sram.asm:1-11`, `.sym:48145-48147`). Note `sBackupOptions3` + 393 unused + `sBackupChecksum` now live in **bank `00`**, whereas the vanilla profile says `sram_bank.sBackupCheckValue1 = 0` — the profile's bank number happens to match, but the *offsets* differ (`B207` vs vanilla `BF0B`-era layout).

### 1.5 `constants` (142 keys)

Every vanilla constant SLink asserts on is checked at `reads.lua:59-72` and `writes.lua:64-87`. Values that **changed** in Polished:

| constant | vanilla | Polished | evidence |
|---|---|---|---|
| `NUM_POKEMON` | 251 | 123 | `constants/pokemon_constants.asm:317-318` |
| `NUM_BOXES` | 14 | 20 | `pokemon_data_constants.asm:304` |
| `MAX_ITEMS` | 20 | 75 | `constants/item_data_constants.asm:39` |
| `MAX_BALLS` | 12 | 25 | `item_data_constants.asm:41` |
| `MAX_KEY_ITEMS` | 25 | `NUM_KEY_ITEMS` = 27 | `constants/item_constants.asm:678-679` |
| `MAX_ITEM_STACK` | 99 | 99 | `item_data_constants.asm:45` (unchanged) |
| `NUM_TM_HM` | 57 | `NUM_TMS + NUM_HMS` | `wramx.asm:1006` |
| `NUM_BADGES` | 16 | `NUM_JOHTO_BADGES + NUM_KANTO_BADGES` | `constants/ram_constants.asm:297` |
| `MONS_PER_BOX` | 20 | 20 | `pokemon_data_constants.asm:298` (unchanged) |
| `PARTYMON_STRUCT_LENGTH` | 48 | 48 | measured, §2.1 |
| `BOXMON_STRUCT_LENGTH` | 32 | *no `boxmon_struct` macro exists* | `macros/ram.asm` has `savemon_struct` (49) instead |

New constants with no vanilla analogue: `MAX_MEDICINE` (37), `MAX_BERRIES` (31), `MAX_PC_ITEMS` (40), `NUM_EVENTS` (2303), `NUM_POKEMON_JOURNALS`, `NUM_HOF_TEAMS` (10), `MONDB_ENTRIES_A/B/C`.

### 1.6 Regenerating the exhaustive table

The full per-key join was **not completed** in the time budget (see the peer reply, *RECOMMENDATION*). The recipe that produces it deterministically:

```
# vanilla name/addr/bank:  profile.json  lines 430-1256 (ram), 1257-2083 (ram_bank)
# Polished name/addr:     polishedcrystal-3.2.3.sym  lines 63508-69843 (WRAM),
#                                                    69844+    (OAM/HRAM),
#                         grep '^0[0-9a-f]:a' for SRAM, '^0[0-9a-f]:b' for SRAM
```

---

## 2. Struct layouts

Offsets below are **measured**, not read off the macro: Polished from `.sym`, vanilla from `profile.json`'s pinned pokecrystal `ram` block (base `wPartyMons = 0xDCDF` / `wBattleMon = 0xC62C`).

### 2.1 `party_struct` — 48 bytes in both games, but the middle differs

Polished offsets measured from `.sym:67524-67570` (base `wPartyMon1 = 01:DCD6`).

| field | vanilla off | Polished off | verdict |
|---|---|---|---|
| Species | +0 | +0 | same |
| Item | +1 | +1 | same |
| Moves (×4) | +2 | +2 | same |
| OT ID (`dw`) | +6 | +6 | same |
| Exp (×3) | +8 | +8 | same |
| **EVs** | **+11, 5 × `dw` = 10 bytes** (`wPartyMon1HPExp` +11, `AtkExp` +13, `DefExp` +15, `SpdExp` +17, `SpcExp` +19) | **+11, 6 × `db` = 6 bytes** (`HPEV`…`SdfEV`) | **different-layout** |
| **DVs** | **+21, 2 bytes** | **+17, 3 bytes** (`HPAtkDV`/`DefSpeDV`/`SatSdfDV`) | **different-layout** |
| **Personality / Shiny / Ability / Nature** | **absent** | **+20 (1 byte)** | **added** |
| **ExtSpecies / Form / Gender / IsEgg** | **absent** | **+21 (1 byte)** | **added** |
| **PP** | **+23 (×4)** | **+22 (×4)** | **moved −1** |
| Happiness (`EggCycles` alias) | +27 | +26 | moved −1 |
| PokerusStatus | +28 | +27 | moved −1 |
| CaughtData / CaughtTime / CaughtBall | +29 | +28 | moved −1 |
| CaughtLevel | (+29, packed with time) | +29 | split out (`.sym` 01:dcf3) |
| CaughtLocation (`CaughtGender` alias) | +30 | +30 | same (`.sym` 01:dcf4; coordinator correction 2026-10-04) |
| Level | +31 | +31 | same |
| Status | +32 | +32 | same |
| Unused | +33 | +33 | same |
| HP (`dw`, BE) | +34 | +34 | same |
| MaxHP (`dw`, BE) | +36 | +36 | same |
| Attack / Defense / Speed / SpAtk / SpDef (5 × `dw`) | +38 | +38 | same |
| End | +48 | +48 | same |

**This is the single most dangerous difference.** The head (`+0`..`+10`) and the tail (`+31`..`+48`) are identical, which is exactly why a length-only check (`writes.lua:64`, `reads.lua:60`) passes and the wrong bytes get written. Every field SLink reads between `+11` and `+30` is at a different offset, and Polished carries two bytes vanilla does not.

Note `writes.lua:6-7` cites "C:75-113 … Status is +32, unused byte +33, HP is BE +34..35" — that half is still true in Polished. The *front* is not.

Polished source that defines the front (`macros/ram.asm:5-40`, `breed_struct`): `Species db`, `Item db`, `Moves ds NUM_MOVES`, `ID dw`, `Exp ds 3`, 6 EV bytes, 3 DV bytes, then `\1Personality::`/`\1Shiny::`/`\1Ability::`/`\1Nature:: db` (all aliases of **one** byte — rgbds attaches the `db` to the last label), then `\1Gender::`/`\1IsEgg::`/`\1ExtSpecies::`/`\1Form:: db` (aliases of **one** byte), `PP ds NUM_MOVES`, then `\1EggCycles::` (a bare label aliasing `Happiness`).

> **Inconsistency inside Polished, flagged.** `constants/pokemon_data_constants.asm:155-173` declares `MON_PERSONALITY rw` and `MON_CAUGHTDATA rb 3`, implying a 34-byte breed struct. The measured struct is 32. **The macro in `macros/ram.asm` is the one that matches the built ROM** (`.sym`). Do not generate offsets from the `rsreset` block.

### 2.2 `breed_struct` — 32 bytes, layout identical to vanilla's party head

Polished `macros/ram.asm:5-40`; measured via §2.1 offsets. Byte-for-byte the same shape as the vanilla `party_struct` head minus the two Polished-only bytes' consumers. Because SLink never reads a `breed_struct` directly (breed is an egg, never in PC boxes in these games), this table is here for completeness; the operative fact is §2.1.

### 2.3 `battle_struct` — 32 bytes vanilla, 35 bytes Polished

Vanilla offsets from `profile.json:896-916` relative to `wBattleMon = 0xC62C`; Polished measured from `.sym:63849-63908` (base `wBattleMon = 00:C4A5`). SLink's decoder hardcodes exactly the vanilla list at `reads.lua:491-493`.

| field | vanilla off | Polished off | verdict |
|---|---|---|---|
| Species | +0 | +0 | same |
| Item | +1 | +1 | same |
| Moves (×4) | +2 | +2 | same |
| DVs | +6 (**2 bytes**, `wBattleMonDVs`=+6, `wBattleMonPP`=+8) | +6 (**3 bytes**) | different-layout |
| Personality / Shiny / Nature | absent | +9 | added |
| ExtSpecies / Form / Gender / IsEgg | absent | +10 | added |
| PP (×4) | **+8** | **+11** | moved |
| Happiness | +12 | +15 | moved |
| Level | +13 | +16 | moved |
| Status | +14 | +17 | moved |
| Unused | +15 | +18 | moved |
| HP (`dw`) | **+16** | **+19** | moved |
| MaxHP (`dw`) | +18 | +21 | moved |
| Attack / Defense / Speed / SpclAtk / SpclDef | +20..+29 | +23..+32 | moved |
| Type1 / Type2 | +30 / +31 | +33 / +34 | moved |
| StructEnd | **+32** | **+35** | **different-layout** |

Field **rename**: Polished spells them `wBattleMonSpAtk` / `wBattleMonSpDef`; vanilla is `wBattleMonSpclAtk` / `wBattleMonSpclDef` (`.sym:63853+` vs `profile.json:908-909`). `reads.lua:491` builds symbol names by string concat, so this is a **hard break**, not a soft one.

`reads.lua:501` reads `offset` bytes; it will read 35 in Polished against a field table that sums to 32, so `geometry()` at `reads.lua:498` will fail closed — but only because the *symbol lookup* fails, not because the size differs.

### 2.4 Enemy party block `wOTPartyData` … `wOTPartyDataEnd`

**Both games: 428 bytes, count → data-end.** The contents differ.

| | vanilla pokecrystal | Polished 3.2.3 |
|---|---|---|
| `wOTPartyData` | `01:D26B` | *(not measured)* |
| `wOTPlayerName` (`ds NAME_LENGTH`) | `01:D26B` | *(not measured)* |
| `wOTPlayerID` (`dw`) | `01:D276` | `01:D281` |
| *(pad)* | `D278`-`D27F`, 8 bytes | *none* |
| `wOTPartyCount` | `01:D280` | `01:D283` |
| **7 bytes after count** | `wOTPartySpecies1` — real species list | `wMirrorHerbPendingBoosts` (`ds NUM_LEVEL_STATS - 1`) |
| `wOTPartyMons` (6 × 48) | `01:D288` | `01:D28B` |
| `wOTPartyMonOTs` | `D3A8`, 6 × 11 = 66 | `01:D3AB`, per mon `OT ds PLAYER_NAME_LENGTH`(8) + `Extra ds 3` = 11 → 66 |
| `wOTPartyMonNicknames` | `D3EA`, 6 × 11 = 66 | `01:D3ED`, 6 × 11 = 66 |
| `wOTPartyDataEnd` | `01:D42C` | `01:D42F` |

Evidence: vanilla `pokecrystal.sym:56095-56330`; Polished `wramx.asm:748-798` and `.sym:66118-66429`.

Consequences for `writes.lua:89-96` (the W-4 Rival Team Swap):

1. `ot_species = ot_block + 1` → in Polished that is `wMirrorHerbPendingBoosts`. **Refuse to write there.**
2. `ot_length` arithmetic (`1 + 7 + 6*(48+11+11) = 428`) still matches `wOTPartyDataEnd`, so the assertion at `writes.lua:92-93` passes and gives false confidence.
3. `ot_mons` must be `0xD28B`, not `0xD288`.
4. `ot_names` = `0xD3AB`, `ot_nicks` = `0xD3ED` — the *same* deltas as vanilla (`+0x123`, `+0x162` from `ot_block`), because Polished moved the `Extra ds 3` from per-mon-nickname into the OT block, keeping the per-mon stride at 11.

### 2.5 `trademon_struct`

Polished `macros/ram.asm:252-273` (`trademon`): Species `db` +0; SpeciesName `ds MON_NAME_LENGTH` +1..11; Nickname `ds 11` +12..22; SenderName `ds NAME_LENGTH` +23..33; OTName `ds NAME_LENGTH` +34..44; DVs +45,+46,+47; Personality/Shiny/Ability/Nature +48; ExtSpecies/Form/Gender/IsEgg +49; ID `dw` +50,+51; CaughtData +52; End +53. **53 bytes.**

Vanilla pokecrystal's `trademon` is the same macro with a `Species db` and the same name fields; the vanilla length is 53 as well. **Verdict: same layout, but UNVERIFIED against a vanilla symbol** — no `wTradeMon*` measurement was taken and SLink's Gen 2 client does not read trademon. Treat as "believed same, not proven".

### 2.6 `savemon_struct` — 49 bytes, no vanilla analogue

Measured from `.sym:50811-50849`. This is Polished's box record; vanilla's is `boxmon_struct` (32 bytes, no nickname/OT in the struct — those live in parallel arrays).

| off | field |
|---|---|
| +0x00 | Species (aliases Gender, IsEgg, ExtSpecies, Form) |
| +0x01 | Item |
| +0x02 | Moves (×4) |
| +0x06 | ID (`dw`) |
| +0x08 | Exp (×3) |
| +0x0B | EVs (×6) |
| +0x11 | DVs (×3) |
| +0x14 | Personality (aliases Shiny, Ability, Nature) |
| +0x15 | ExtSpecies / Form |
| +0x16 | **PPUps — 1 byte**, replaces breed's `PP ds 4` |
| +0x17 | Happiness |
| +0x18 | PokerusStatus |
| +0x19 | CaughtData / CaughtTime / CaughtBall |
| +0x1A | CaughtLevel |
| +0x1B | CaughtLocation |
| +0x1C | Level |
| +0x1D | Extra (×3) |
| +0x20 | Nickname (10) |
| +0x2A | OT (7) |
| +0x31 | End |

---

## 3. Species encoding, bag, flags, badges

### 3.1 Species: 9-bit species + packed second byte

Polished stores species as **two aliased bytes**, not one (`macros/ram.asm:5-40`, `pokemon_data_constants.asm:137-162`):

| byte | aliases | bit layout (`constants/pokemon_data_constants.asm:241-247`) |
|---|---|---|
| **+0** | `Species` | low 8 bits of species |
| **+20** (party) / **+21** (battle) | `Personality`, `Shiny`, `Ability`, `Nature` | personality byte — shiny/ability/nature are **bit fields**, not separate bytes |
| **+21** (party) / **+10** (battle) | `Gender`, `IsEgg`, `ExtSpecies`, `Form` | `%10000000` GENDER, `%01000000` IS_EGG, `%00100000` EXTSPECIES (species bit 8), `%00011111` FORM |

So: **9-bit species** = byte0 (8 bits) OR (`byte_form & %00100000` ? 0x100 : 0); **form** = `byte_form & %00011111`; **gender** = `byte_form & %10000000`; **is-egg** = `byte_form & %01000000`.

Where species lives:

| struct | low byte | high/form byte |
|---|---|---|
| `party_struct` | +0 | +21 |
| `battle_struct` | +0 | +10 |
| `savemon_struct` | +0 | +0x15 |
| `trademon` | +0 | +49 |
| `savemon_struct` in PokeDB | +0 | +0x15 |

Form values run 1..31 and are resolved through `VariantSpeciesAndFormTable` / `CosmeticSpeciesAndFormTable` (`home/pokemon.asm:463-473`, `GetSpeciesAndFormIndex`). `GetSpeciesAndFormIndex` takes `c = species`, `b = form` and returns an extended index.

**SLink impact:** `reads.lua:105-106` does `local species = bytes[c.MON_SPECIES + 1]` with `MON_SPECIES = 0` and validates `1 <= species <= NUM_POKEMON`. In Polished that reads only the low byte, so **species 256-511 read as 0-255**, and `NUM_POKEMON` is 123 so a form bit set (`EXTSPECIES_MASK`) makes the low byte fall outside the range. The identity key `DDDD:TTTT:SS` would also need to carry the form.

### 3.2 Bag pockets — five now, not three

`reads.lua:350-354` decodes exactly three. Polished `wramx.asm:1006-1026`:

| pocket | count byte | data | stride | capacity | vanilla equivalent |
|---|---|---|---|---|---|
| TM/HM | `wNumItems` (shared) | `wTMsHMs` | flag array | `NUM_TMS + NUM_HMS` | same idea, 57 |
| key items | `wNumKeyItems` | `wKeyItems` `ds NUM_KEY_ITEMS+1` | 1 | 27 | 25 |
| items | `wNumItems` | `wItems` `ds MAX_ITEMS*2+1` | 2 | 75 | 20 |
| **medicine** | `wNumMedicine` | `wMedicine` `ds MAX_MEDICINE*2+1` | 2 | 37 | **absent** |
| **balls** | `wNumBalls` | `wBalls` `ds MAX_BALLS*2+1` | 2 | 25 | 12 |
| **berries** | `wNumBerries` | `wBerries` `ds MAX_BERRIES*2+1` | 2 | 31 | **absent** |
| PC items | — | — | — | `MAX_PC_ITEMS` 40 | **absent** |

Key items are still ID-only (width 1) with an `$FF` terminator; all other pockets are (id, quantity) pairs. `MAX_ITEM_STACK` is 99 in both.

**SLink impact — the Nuzlocke gate.** The Gen 2 Apricorn-ball gate (`copilot-instructions.md`, "Apricorn balls … for nuzlocke gate detection") reads the **balls** pocket. Polished's balls pocket is capacity 25, not 12, and a *separate medicine pocket* and *berries pocket* exist. The ball-ID set must be re-derived from Polished's `constants/item_constants.asm`; the vanilla set is wrong.

### 3.3 Event flags and badges

| | vanilla | Polished | evidence |
|---|---|---|---|
| badges | `wJohtoBadges`/`wKantoBadges`, 1 byte each, 8 badges | same, 1 byte each, 8 badges | `ram_constants.asm:274-297`, `.sym:67247-67250` |
| `wBadges` | — | `01:D7EE`, End `01:D7F0` (2 bytes) | `.sym:67247-67250` |
| event flags | `wEventFlags` | `wEventFlags:: flag_array NUM_EVENTS`, NUM_EVENTS = 2303 → **288 bytes** (`01:DA5A`-`01:DB79`) | `constants/event_flags.asm:2433-2434`, `.sym:67402`, `wramx.asm:1180` |

Badge bit order is **NOT** identical (coordinator correction 2026-10-04): Johto is the same (Zephyr, Hive, Plain, Fog, Mineral, Storm, Glacier, Rising), but Kanto swaps bits 4/5 — Polished is Boulder, Cascade, Thunder, Rainbow, **Marsh, Soul**, Volcano, Earth (`ram_constants.asm:288-289`), vanilla is ..., Rainbow, **Soul, Marsh**, .... `wEventFlags` is a **bit array**, not a byte array: the bit index for an event id `N` is `N`, byte `N >> 3`, mask `1 << (N & 7)`. Vanilla pokecrystal also uses `flag_array NUM_EVENTS` with NUM_EVENTS = 0x800-ish, so the *encoding* is the same; only the **count** moved.

---

## 4. Trainer classes and the trainer-id packing

### 4.1 The packing SLink uses

`server/adapters/gen2_gsc.py:255-258` and `:689-691`:

> trainer_id = `class * 256 + instance`, built from `wOtherTrainerClass` / `wOtherTrainerID`.

`_rival_ids = {cls*256 + inst for (cls,inst) in _trainer_names if cls in {RIVAL1, RIVAL2}}` (`gen2_gsc.py:265-267`). The adapter loads `data/games/gen2_crystal/trainers.json` and reads `classes`, `parties`, `class_constants`.

### 4.2 Vanilla pokecrystal classes

`data/games/gen2_crystal/trainers.json:771` → `"9": "RIVAL1"`; `:804` → `"42": "RIVAL2"` (`$2A`). These match the adapter's own comment citing `constants/trainer_constants.asm:55,454`. There is **no `RIVAL0` and no `LYRA*`** in the vanilla class table — the `grep` for those keys in `trainers.json` returned nothing.

So SLink's rival set today = every instance of classes 9 and 42.

### 4.3 Polished 3.2.3 classes

`F:/slink-work/cache/polished/src/constants/trainer_constants.asm`, with `trainerclass` at `:10-15` (`DEF \1 EQU __trainer_class__` then `+= 1`, starting from `__trainer_class__ = 0` at `:8`). The trailing `; nn` comments are **hex** (`TRAINER_NONE ; 0` at `:29`, `CARRIE ; 1` at `:39`).

| constant | Polished class | line |
|---|---|---|
| `RIVAL0` | `$1B` (27) | `:95` |
| `RIVAL1` | `$1C` (28) | `:97` |
| `RIVAL2` | `$1D` (29) | `:111` |
| `LYRA1` | `$1E` (30) | `:113` |
| `LYRA2` | `$1F` (31) | `:127` |

Sub-constants exist as `const RIVAL1_4`..`RIVAL1_15` (`:98-109`) and `LYRA1_1`..`LYRA1_12` (`:114-125`) — these are **instance** indices into `TrainerGroups`, not classes, and are exactly the `inst` half of `class*256+inst`.

Consequences:

- The rival class set changes from `{9, 42}` to at least `{28, 29}`; **`RIVAL0` (27) is a new rival SLink does not currently gate on**, and `LYRA1`/`LYRA2` are new rival-class trainer battles too.
- Every `trainer_id` SLink has ever computed is wrong on Polished, because the class byte itself moved.
- A Polished `trainers.json` pack (with `classes`, `parties`, `class_constants`) must be generated; there is none today.

---

## 5. What breaks, ranked

1. **`party_struct` mid-section.** Same length, same head/tail, different middle. A `PARTYMON_STRUCT_LENGTH == 48` assertion (`writes.lua:64`, `reads.lua:60`) passes and every EV/DV/PP/field write lands 1-2 bytes off. `writes.lua:81-83` validates only `wPartyMon1`, `wPartyMon1Status`, `wPartyMon1HP` — all in the *unchanged* tail.
2. **`battle_struct` renamed + resized** (`SpclAtk`→`SpAtk`, `SpclDef`→`SpDef`; 32→35 bytes). `reads.lua:491-493` builds every field name by concatenation.
3. **Enemy party block** — `writes.lua:94` would write Mirror Herb state.
4. **Box storage format replaced** — `reads.lua:273-301` (`read_active_box`, `read_storage_box`, the `NUM_BOXES/2` bank split) has no target.
5. **Species is 9-bit + form** — `reads.lua:105-106` reads one byte and validates against `NUM_POKEMON` (251 → 123).
6. **Trainer class ids all moved**; `RIVAL0` and `LYRA1/2` are unmodelled rivals.
7. **Bag** — five pockets; ball IDs and capacities differ; the Nuzlocke gate's ball set is wrong.

## 6. Open items

- `data/gen2/pokecrystal.sym` contains **no** `wPartyMon1*` member symbols, and `data/gen2/crystal_slink.sym` does contain them but at a **different** geometry from the pinned `profile.json` (its `wPartyMon1DVs` is at `0xDCF4`, `wPartyMon1Happiness` at `0xDCFA`, `StructEnd` at `0xDD0F`). The vanilla offsets in §2.1 are therefore taken from the `profile.json` the client actually consumes, and the two repo syms could not be reconciled with it.
- The full `ram`/`ram_bank` → Polished join (§1.6) was not completed.
- `wMonType`, `wJoypadDisable`, `wEnemyMonSpecies`, `wPokemonStorage`, `wBoxMons`, `wSlot1` Polished addresses were not measured.