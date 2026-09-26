# PK4 record, party, PC and the flash save (HGSS)

Source: pokeheartgold @ad7a3afa. OMP card G4-R1 `cx-9e50c1ce` (27 accepted, 0 rejected).
The coordinator re-verified this card against a real battery save, marked FILE.

## Record (SOURCE)

| Item | Value | Evidence |
|---|---|---|
| `BoxPokemon` | 0x88 bytes. PID u32 @0; flags u16 @4 (`partyDecrypted:1, boxDecrypted:1, checksumFailed:1`); checksum u16 @6; `dataBlocks[4]` of 0x20 each @8 | `include/pokemon_types_def.h:155-162` |
| Block A | species @0, item @2, OT id @4, exp @8, friendship @0xC, ability @0xD, markings @0xE, language @0xF, EVs @0x10-0x15, contest @0x16-0x1B, ribbons @0x1C | `:50-84` |
| Block B | moves[4] @0, pp[4] @8, ppUps[4] @0xC, IV/egg/nickname bitfield @0x10, ribbons @0x14, fateful/gender/**form** @0x18, shinyLeaves @0x19, **egg/met location (Pt/HGSS) @0x1C/0x1E** | `:86-113` |
| Block C | nickname u16[11] @0, originGame @0x17 | `:115-121` |
| Block D | OT name @0, dates @0x10-0x15, DP egg/met loc @0x16/0x18, pokerus @0x1A, ball @0x1B, metLevel:7/otGender:1 @0x1C, **HGSS ball @0x1E** | `:123-146` |
| Party tail (`PartyPokemon`, 0x64) | status @0x88, level @0x8C, capsule @0x8D, hp @0x8E, maxHP @0x90, atk/def/spe/spa/spd @0x92-0x9A, mail @0x9C, seal coords @0xD4 | `:201-215` |
| `Pokemon` | 0xEC bytes | `:212-217` |
| Checksum | u16 sum of the 64 u16 words of `dataBlocks` | `src/pokemon.c:3941-3950` |
| Shuffle | 32-row table indexed by `(pid & 0x3E000) >> 13`. Rows 24-31 duplicate rows 0-7, so it is equivalent to `% 24`; port the table verbatim. `which` 0..3 = A..D | `src/pokemon.c:3951-3986`, `:483-486` |
| PRNG | `seed = seed*1103515245 + 24691; out = seed>>16` (0x41C64E6D / 0x6073); XOR per u16, symmetric | `src/math_util.c:150-157` |
| Seeds | blocks: `checksum`; party tail: `personality` | `src/pokemon.c:61-62` |
| Ball | `MON_DATA_POKEBALL` prefers Block D @0x1E when originGame is HG/SS | `src/pokemon.c:833-837` |
| HG vs SS | no layout-affecting `#if` in any of the 12 relevant files | grep (R1 §7) |

After a raw RAM write, the block data must be re-encrypted and the checksum recomputed. Otherwise the next `GetBoxMonData` asserts and sets `checksumFailed` (`src/pokemon.c:415-421, 466-472`).

## Party, save arrays, PC (SOURCE)

- `Party` = `{int maxCount; int curCount; Pokemon mons[6]}` followed by an aprijuice tail (`include/pokemon_types_def.h:310-327`). It is save array **2** (`SAVE_PARTY`), in the general block.
- There are 42 save arrays (`src/save_arrays.c:57-313`). Id 41 `SAVE_PCSTORAGE` is the **only** array in block 1. Everything else is in block 0: sysinfo 0, playerdata 1, party 2, bag 3, flags 4, local field data 5, …, roamer 21, …
- `SaveArray_Get(save, id) = &save->dynamic_region[save->arrayHeaders[id].offset]` (`src/save.c:128-131`). **Read the headers at runtime.** Don't hard-code intra-SaveData offsets: the offset comments in `include/save.h:73-85` are stale by 4 or more.
- On-disk chunk size = `((sizeof+3)&~3)+4` (`src/save.c:733-742`).
- `PCStorage` (`include/pokemon_storage_system.h:12-28`):

  | Field | Offset |
  |---|---|
  | `PC_BOX boxes[18]` (30×0x88 + 16 pad = **0x1000** each) | +0x00000 |
  | `curBox` | +0x12000 |
  | `boxModifiedFlag` | +0x12004 |
  | `box_names[18][20]` u16 | +0x12008 |
  | `wallpapers[18]` | +0x122D8 |
  | `unlockedWallpapers` | +0x122EA |

  Total size 0x122FC, block 0x12310.
- Player profile: save array 1. Field order (verified) is `Options`, `PlayerProfile{name u16[8], id u32, money u32, gender, language, johtoBadges, avatar, version, flags, kantoBadges}`, `coins`, `IGT` (`include/player_data.h:12-32`). The offsets are *derived* (id +0x14, money +0x18, johto +0x1E, kanto +0x22) and must be confirmed on a save.
- Badges: 0-7 are Johto bits, 8-15 are Kanto bits (`src/player_data.c:115-142`).
- Location: `SAVE_LOCAL_FIELD_DATA` (5), with `currentPosition` first: `Location {mapId, warpId, x, y, direction}` = 0x14 (`include/field_types_def.h:10-16`).
- At runtime, `FieldSystem+0x0C` = `SaveData*` and `FieldSystem+0x20` = `Location*` (the same memory) (`include/field_system.h:112-125`).

## Flash save format (SOURCE + FILE)

| Item | Value | Evidence |
|---|---|---|
| Size | 0x80000 (4 Mbit flash) | `src/save.c:145-148, 1100-1112` |
| Banks | bank 0 at 0x00000, bank 1 at 0x40000 (not a mirror) | `src/save.c:309-316` |
| Blocks per bank | general block at bank+0; PC block at bank+`spec->offset` (0x100-aligned) | `src/save.c:770-795` |
| Footer (last 0x10 of each block) | `u32 count; u32 size; u32 magic=0x20060623; u16 slot; u16 crc` | `include/save.h:18,33-39`; `src/save.c:318-376` |
| CRC | **CRC-16-CCITT, poly 0x1021, init 0xFFFF**, over `size-0x10` bytes | FILE (matched on the real save); `src/math_util.c:159-167` |
| Newest slot | per block, the larger `count` via `SaveCounterCompare` (wrap rule); general and PC must agree | `src/save.c:378-388, 429-528` |
| Write order | body first, footer last | `src/save.c:595-673` |

## Real-save verification (FILE)

Owner's HG battery save: `E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM`, 0x80000 bytes.

| Measured | Value |
|---|---|
| Populated bank | only bank 1 (count = 1) |
| General block | 0x40000, size **0xF628**, slot 0, CRC matches with init 0xFFFF |
| PC block | 0x4F700 (= bank + **0xF700**), size **0x12310**, slot 1, CRC matches |
| Party | general+**0x90** max=6, +0x94 count=1, first mon at +0x98: PID-decrypted, checksum valid, species **155** (Cyndaquil), level 5, HP 20/20 |
| PC | 0 mons, curBox 0 |

In RAM, `dynamic_region` sits at `SaveData+0x10`, so party count = `SaveData+0xA4` and first mon = `+0xA8`. That agrees with the legacy profile's 0xA4/0xA8.

**hg-engine save** (`patched hge ap.SaveRAM`): general block size **0xFFA0**, PC block at bank+**0x10000**, size **0x1E4FC** (30 boxes). See [hg_engine.md](hg_engine.md).

**Platinum:** the only local Platinum save (`…Platinum Version (USA).AutoSaveRAM.SaveRAM`) is **blank** (all 0xFF). A real one is needed for the D3 codec bind check.
