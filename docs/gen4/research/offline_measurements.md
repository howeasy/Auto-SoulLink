# Offline ROM / save measurements (FILE)

Source: a Sonnet research worker, 2026-09-26. The scripts are in `.cache/gen4/offline/` (gitignored). The coordinator re-checked the `ScrCmd_GiveMon`/`GiveMon` addresses and the hge arm9 size.

## Site bytes, HG vs SS

All 21 candidate symbols are **byte-identical in HG and SS, at identical addresses** (ndspy-decompressed arm9/overlay images; xMAP addresses). All are arm9 except `BtlCmd_TryFaintMon` and `ov12_0223843C` (overlay 12). Data: [data/site_bytes_hg_ss.json](data/site_bytes_hg_ss.json).

## hg-engine site survival

Bytes at the vanilla addresses in the pinned hge build (`cb2dc435…`). Data: [data/hge_site_survival.json](data/hge_site_survival.json).

**KEPT:**

| Site | Address |
|---|---|
| `Encounter_GetResult` | |
| `Task_Blackout` | |
| `Party_AddMon` | |
| `ScrCmd_GiveMon` | 0x0204D088 |

**CHANGED:**

| Site | Address |
|---|---|
| `HandleLoadOverlay` | |
| `UnloadOverlayByID` | |
| `BtlCmd_TryFaintMon` | |
| `PCStorage_PlaceMonInBox…` | |
| `Save_WriteManFinish` | |
| `ScrCmd_GiveEgg` | |
| `GiveMon` (the script helper) | 0x020541DC |

These match the source-level verdicts in [hg_engine.md](hg_engine.md) §4. The earlier "`ScrCmd_GiveMon` 0x020541DC replaced" wording mixed up two symbols: 0x020541DC is `GiveMon` (`script_pokemon_util.o`), which hge replaces; the script command `ScrCmd_GiveMon` itself is kept.

**hge geometry:**
- arm9 is **0x2477C8** bytes (vanilla 0x111760), ending at 0x022477C8. This confirms the `hooks:632-636` misfile: the overlay-2 hooks landed in a bloated arm9, and overlay 2 at 0x1B0C..0x1C40 is unchanged from vanilla.
- The hge arm9 is stored uncompressed. ndspy's auto-detector false-positives on it, so tools must fall back to raw bytes.
- There are **22 new overlay ids (128-149)**. Most of 132-149 alias the RAM regions of 129/130/131.

## Acquisition manifest

A grep over all 1501 `scr_seq/*.s` files found 61 sites:

| Command | Sites |
|---|---|
| `GiveMon` | 13 |
| `GiveEgg` | 3 |
| `GiveTogepiEgg` | 1 |
| `GiveSpikyEarPichu` | 1 |
| `GiveLoanMon` | 2 |
| `CreateRoamer` | 8 |
| `WildBattle` | 21 |
| `LoadNPCTrade` | 11 |
| `ChooseStarter` | 1 |

Species are resolved via `species.h` and maps via the scr_seq filename token. Variable-driven species (Kanto starter, Game Corner) are recorded with their script context. Data: [data/acquisition_manifest.json](data/acquisition_manifest.json).

## NPC trades

13 × 0x54-byte records from NARC `a/1/1/2`, **byte-identical in HG and SS**, all decoding to known trades (e.g. Onix↔Bellsprout, Machop↔Drowzee … Beldum↔Forretress). The four records with give == ask species (Steelix, Shuckle, Spearow, Pikachu) are the loan / special mons. Data: [data/npc_trades.json](data/npc_trades.json).

## Player profile on the real HG save

The profile was found by charmap search after verifying the known party header first:

| Location | Value |
|---|---|
| `SAVE_PLAYERDATA` | general+**0x60** (`Options` u32) |
| `PlayerProfile` | general+**0x64** |
| name +0x00 | "SPLERM" |
| TID/SID +0x10 | 26310 / 29888 |
| money +0x14 | 3000 |
| gender +0x18 | 1 |
| language +0x19 | 2 (English) |
| Johto badges +0x1A / Kanto badges +0x1E | 0 / 0 |
| version +0x1C | **7 = VERSION_HEARTGOLD** |

Consistency check: 0x60 + sizeof(PLAYERDATA) 0x2C + 4 (chunk CRC) = 0x90, which is exactly the party chunk start. The derived profile offsets hold. IGT, bag and local field data were not pinned.

## Encounter data

`gs_enc_data.json` has 142 map entries:

| Method | Slots |
|---|---|
| land | 1332 |
| surf | 360 |
| rock smash | 20 |
| each rod | 355 |

53 of 142 maps have an HG/SS split somewhere (sometimes nested under time-of-day or swarm/radio blocks).

## hg-engine save

- Both footer CRCs verify.
- Party at general+**0x90** (same as vanilla), count 0.
- PC: 30 boxes, all empty; the box names decode to "Box 1".."Box 30".

This save is bare, so a populated hge fixture must be made at G5.
