# Gen 4 Pret Decomp Citations

Single source of truth for every Gen 4 RAM address used by SLink, mapped back to the
upstream `pret` decompilation. Use this doc when validating a new ROM variant or
debugging an offset drift.

Two pret repos are authoritative:
- `pret/pokeheartgold` — HGSS struct layout, save format, battle system
- `pret/pokeplatinum` — Platinum-specific deltas (dynamic_region starts at +0x14
  vs HGSS +0x10; PlayerProfile base differs)

Concrete RAM addresses (the actual heap-chunk locations) are NOT symbolised in pret
since they live in dynamically-allocated chunks. For those we cross-reference
`Brian0255/NDS-Ironmon-Tracker` and `kwsch/PKHeX`, with pret providing the struct
layout that justifies the byte offsets within each chunk.

## PartyPokemon / BoxPokemon struct (236 / 136 bytes)

| Field | Offset | Type | Source |
|---|---|---|---|
| `pid` (personality) | +0x000 | u32 | `pret/pokeheartgold include/pokemon_types_def.h struct BoxPokemon.pid` |
| `flags` (partyDecrypted bit 0, boxDecrypted bit 1, checksumFailed bit 2) | +0x004 | u16 | `pokemon_types_def.h struct BoxPokemon.flags` |
| `checksum` (CRC-16-CCITT of dataBlocks) | +0x006 | u16 | `pokemon_types_def.h struct BoxPokemon.checksum` |
| `dataBlocks[4]` (32-byte blocks A/B/C/D, order from PID) | +0x008..+0x087 | block array | `pokemon_types_def.h struct PokemonDataBlock{A,B,C,D}` |
| `status` (party only) | +0x088 | u32 | `pokemon_types_def.h struct PartyPokemon.status` |
| `level` | +0x08C | u8 | `pokemon_types_def.h struct PartyPokemon.level` |
| `ballCapsuleID` | +0x08D | u8 | `pokemon_types_def.h struct PartyPokemon.capsule` |
| `curHP` | +0x08E | u16 | `pokemon_types_def.h struct PartyPokemon.hp` |
| `maxHP` | +0x090 | u16 | `pokemon_types_def.h struct PartyPokemon.maxHp` |
| `atk / def / speed / spatk / spdef` | +0x092..+0x09B | u16 × 5 | `pokemon_types_def.h struct PartyPokemon (stat block)` |

Block-order permutation: `((pid & 0x3E000) >> 13) % 24` (NOT `pid % 24`). Each
permutation selects a 24-entry table mapping block A→{0,32,64,96}. Reference table
in `pokemon_types_def.h` plus Project Pokemon Gen IV PKM docs.

Battle-stat block at +0x088 is PID-seeded LCRNG-encrypted in live RAM
(see `decrypt_stats` in `lua/memory_nds.lua`). Encryption applies whether or not
`flags.partyDecrypted` is set; verified against live HGSS scans.

## SaveData layout

| Field | Source |
|---|---|
| `saveData = *(*(0x0BA8) + 0x20)` — pointer chain | `pret/pokeheartgold src/save.c — gSavedataMainPtrAddr` |
| `dynamic_region[]` starts at SaveData+0x10 (HGSS) / +0x14 (Platinum) | `pret/pokeheartgold include/save.h struct SaveData` |
| `arrayHeaders[NUM_SAVE_CHUNKS]` at SaveData+0x23014 | `pret/pokeheartgold include/save.h + include/constants/save_arrays.h` |
| `arrayHeaders[SAVE_PCSTORAGE=41].offset` u32 field at SaveData+0x232AC | `save_arrays.h SAVE_PCSTORAGE constant + ArrayHeader struct (.offset is third u32)` |

PC storage base = `SaveData + 0x10 + r32(SaveData + 0x232AC)`.

## PartyCore + Bag

| Field | HGSS offset | Pt offset | Source |
|---|---|---|---|
| `Party.curCount` | base+0xA4 | base+0xB0 | `pret/pokeheartgold include/party.h struct Party.curCount` |
| `Party.mons[0]` (first PartyPokemon) | base+0xA8 | base+0xB4 | `include/party.h struct Party.mons[6]` |
| Bag balls pocket base | base+0xD14 | base+0xD00 | `pret/pokeheartgold include/bag.h struct BagItem[]` + `PKHeX PlayerBag4HGSS.cs/PlayerBag4Pt.cs` |
| Balls pocket slot count | 24 | 15 | `PKHeX PlayerBag4*.cs` battle-items boundary |

PartyPokemon stride = 0xEC bytes. BoxPokemon stride = 0x88. PC box stride = 0x1000
(30 × 0x88 = 0xF90, padded).

## PlayerProfile

| Field | HGSS offset | Pt offset | Source |
|---|---|---|---|
| `PlayerProfile.name[8]` | base+0x74 | base+0x7C | `pret/pokeheartgold include/player_data.h struct PlayerProfile.name` |
| `PlayerProfile.johtoBadges` | base+0x8E | (n/a) | `include/player_data.h struct PlayerProfile.johtoBadges (profile+0x1A)` |
| `PlayerProfile.kantoBadges` | base+0x93 | (n/a) | `include/player_data.h struct PlayerProfile.kantoBadges (profile+0x1F)` |
| `PlayerProfile.sinnohBadges` | (n/a) | base+0x96 | `pret/pokeplatinum equivalent struct PlayerProfile (badges at profile+0x1A)` |

Player name is Gen IV custom 16-bit charcode (see `readTrainerName` in `memory_nds.lua`),
NOT standard Unicode.

## Map header (zone ID)

| Field | HGSS offset | Pt offset | Source |
|---|---|---|---|
| `FieldSystem.childMapHeader` pointer | base+0x25FE4 | base+0x239B0 | `pret/pokeheartgold src/field/field_system.c struct FieldSystem.childMapHeader` |
| `MapHeader.mapID` (u16) | *ptr + 0x02 | *ptr + 0x02 | `pret/pokeheartgold include/map_header.h struct MapHeader.mapId` |

If `r16(base + ZONE_ID_OFF)` reads 0, fall back to dereferencing the location
as a pointer and reading u16 at `ptr+2`.

## Battle struct

| Field | HGSS offset | Pt offset | Source |
|---|---|---|---|
| Player battle copy slot 0 (PartyPokemon[]) | base+0x4EA98 | base+0x4B8AC | `pret/pokeheartgold src/battle/battle_setup.c — player party buffer inside BattleSystem` |
| Enemy battle copy slot 0 | base+0x4F068 | base+0x4BE5C | `pret/pokeheartgold src/battle/battle_setup.c — opponent party buffer` |
| Enemy trainer ID (u16) | base+0x440AA | base+0x4189E | `pret/pokeheartgold src/battle/battle_setup.c — TrainerData.id` |
| Battle status absolute | 0x246F48 | 0x24A55A | `pret/pokeheartgold include/battle/battle.h BATTLE_STATUS_* macros` |
| `gBattlersCount` equivalent | TBD (Phase 3 scan) | TBD | `pret/pokeheartgold src/battle/battle_controllers.c — BattleSystem_NumBattlers / MaxBattlersByMode` |
| Per-battler `statChanges[7]` | TBD (Phase 3 scan) | TBD | `pret/pokeheartgold src/battle/battle_system.c — struct BattleMon.statChanges` |

`pret` does not symbolise the BattleSystem heap chunk's RAM address — it allocates
dynamically. Concrete RAM offsets are sourced from `NDS-Ironmon-Tracker
MemoryAddresses.lua` (HEART_GOLD playerBattleBase / enemyBase) and confirmed against
live battles. Phase 3 adds live discovery scripts for the doubles + stat-stage offsets.

## Item ID ranges (balls)

| Range | Items | Source |
|---|---|---|
| 0x0001..0x0010 | Master Ball → Cherish Ball (16 standard balls) | `pret/pokeheartgold include/constants/items.h ITEM_MASTER_BALL..ITEM_CHERISH_BALL` |
| 0x01EC..0x01F4 | Fast Ball → Sport Ball (9 Kurt/Apricorn balls, HGSS-only) | `pret/pokeheartgold include/constants/items.h ITEM_FAST_BALL..ITEM_SPORT_BALL` |

Platinum lacks the Apricorn ball range.

## Special species

| Species | ID | Source |
|---|---|---|
| Egg | 494 | `pret/pokeheartgold include/constants/species.h SPECIES_EGG` |
| Last regular species (Arceus) | 493 | `include/constants/species.h SPECIES_ARCEUS` |

## Trainer + move data tables

| Data | File | Notes |
|---|---|---|
| Trainer parties / names / classes | `pret/pokeheartgold data/trainers/trainer_data.h` + `data/trainers/trainer_classes.h` | Generated to `data/games/gen4_hgsspt/trainers_hgss.json` |
| Move metadata (type/power/accuracy/PP/split) | `pret/pokeheartgold data/battle/moves.h` | Generated to `GEN4_MOVE_DATA` in `server/move_data.py` |
| Move names (English) | `pret/pokeheartgold data/text/moves_en.s` (or equivalent string bank) | Generated to `GEN4_MOVE_NAMES` |
| Species → base abilities | `pret/pokeheartgold data/pokemon/base_stats.h struct BaseStats.abilities[2]` | Used as fallback when battle-struct ability is unavailable |

Platinum equivalents live in `pret/pokeplatinum` under the same paths.

## Renegade Platinum (RP)

RP is a difficulty hack on Platinum maintained at `github.com/Drayano60/Renegade-Platinum`.

| Aspect | Source |
|---|---|
| ROM detection | SHA1 / CRC32 whitelist; RP keeps Platinum's "CPUE" game code |
| RAM struct layout | Preserved from vanilla Platinum (no save format changes) |
| Trainer rosters | Drayano60 source repo's ARM9 binary trainer tables — generated to `data/games/gen4_hgsspt/rp_trainers.json` |
| Ability overrides | Per-species mon ability remaps — generated to `server/rp_ability_overrides.py` |
| Move backports | RP backports several Gen 5–9 moves to existing IDs; additional move-table extension required |

RP-specific deltas are live-scanned (not in pret) and documented per-constant in
`lua/games/gen4_hgsspt.lua _RP_PROFILE` comments.

## How to add a new address

1. Open the relevant `pret/pokeheartgold` or `pret/pokeplatinum` header to find the
   struct layout that defines the field.
2. If the address lives in a static EWRAM/IWRAM symbol (rare in NDS games — most live
   inside heap chunks), search pret's `*.s` linker scripts or `gSavedataMain*` globals.
3. If the address is dynamic (e.g. inside the BattleSystem heap chunk), use
   `NDS-Ironmon-Tracker MemoryAddresses.lua` for the concrete RAM offset, and cite both
   pret (for struct layout) and Ironmon (for the offset).
4. Add an inline `-- Source:` comment in the relevant `.lua` file.
5. Update this file with the new entry.
