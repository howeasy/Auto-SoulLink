# Offline ROM / save measurements (FILE)

Source: a Sonnet research worker, 2026-09-26. The scripts are in `.cache/gen4/offline/` (gitignored). The coordinator re-checked the `ScrCmd_GiveMon`/`GiveMon` addresses and the hge arm9 size.

## Site bytes, HG vs SS

All 21 candidate symbols are **byte-identical in HG and SS, at identical addresses** (ndspy-decompressed arm9/overlay images; xMAP addresses). All are arm9 except `BtlCmd_TryFaintMon` and `ov12_0223843C` (overlay 12). Data: [data/site_bytes_hg_ss.json](data/site_bytes_hg_ss.json).

## hg-engine site survival

Bytes at vanilla addresses in the pinned hge build (`test.nds` SHA1 `cb2dc435196d09c8c9209bf037240ed834f4cea1`). Data: [data/hge_site_survival.json](data/hge_site_survival.json). The original resolver (`.cache/gen4/offline/common.py:43-58`) searched expanded ARM9 before overlays. Its ARM9-zero readings for the two ov12 addresses were therefore **wrong-image measurements**, not evidence of replacement. A read-only ndspy remeasurement selected declared ov12 directly: `BtlCmd_TryFaintMon` 0x0223E22C → `004b1847d1ed3c02012107f067f9281c` (changed); `ov12_0223843C` 0x0223843C → `f8b5051ccef526ff041c281ccef52cff` (same 16-byte prefix as vanilla). The hge export `.cache/gen4/hge/offsets.ini:91` puts the replacement `BtlCmd_TryFaintMon` at 0x023CEDD0; declared ov130 there reads `f8b50c002a4b01210600200000f068fa`. These are FILE bytes for the pinned image, not live execution/residency proof. The JSON retains the earlier zero readings as historical wrong-image metadata.

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
| `BtlCmd_TryFaintMon` | source replacement at 0x023CEDD0 (ov130); the vanilla ov12 address contains a branch trampoline, not ARM9 zeros |
| `PCStorage_PlaceMonInBox…` | |
| `Save_WriteManFinish` | |
| `ScrCmd_GiveEgg` | |
| `GiveMon` (the script helper) | 0x020541DC |

The non-overlay rows match the source-level verdicts in [hg_engine.md](hg_engine.md) §4. The ov12/ov130 row needs separate source, image and PHYSICAL site evidence; address overlap cannot choose the owning image. The earlier "`ScrCmd_GiveMon` 0x020541DC replaced" wording mixed up two symbols: 0x020541DC is `GiveMon` (`script_pokemon_util.o`), which hge replaces; the script command `ScrCmd_GiveMon` itself is kept.

**hge geometry:**
- arm9 is **0x2477C8** bytes (vanilla 0x111760), ending at 0x022477C8. This confirms the `hooks:632-636` misfile: the overlay-2 hooks landed in a bloated arm9, and overlay 2 at 0x1B0C..0x1C40 is unchanged from vanilla.
- The hge arm9 is stored uncompressed. ndspy's auto-detector false-positives on it, so tools must fall back to raw bytes.
- There are **22 new overlay ids (128-149)**. Most of 132-149 alias the RAM regions of 129/130/131.

## Acquisition manifest

A bounded grep over all 1501 `scr_seq/*.s` files found 61 sites for the selected command set:

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

Species are resolved via `species.h` and maps via the scr_seq filename token. Variable-driven species (Kanto starter, Game Corner) are recorded with their script context, but their runtime outcomes remain open. The 61 script hits must be joined to C producers, NARC records, and runtime branches before claiming exhaustive acquisition coverage. Data: [data/acquisition_manifest.json](data/acquisition_manifest.json).

## NPC trades

13 × 0x54-byte records from NARC `a/1/1/2`, **byte-identical in HG and SS**. The authored scripts contain 11 `LoadNPCTrade` sites using ten IDs (0,1,2,3,5,8,9,10,11,12); ID 8 has two sites. IDs 6/7 are Shuckle/Spearow loan grants through `GiveLoanMon`, and Rapidash ID 4 is a dormant record in the pinned authored-source scan. Steelix ID 5 and Pikachu ID 10 are same-species **executed exchanges**, not loans. Data: [data/npc_trades.json](data/npc_trades.json). This classification does not establish hge's authored paths.

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
- The empty-party scan found **two** candidates at general+`0x90` and general+`0xCAB4`, both count 0 and first PID 0 (`.cache/gen4/offline/task7_hge_save.json`). FILE evidence cannot select the party offset. Source projection favors `0x90`, but it remains unconfirmed by this save.
- PC: 30 boxes, all empty; the box names decode to "Box 1".."Box 30".
- The untouched PC's apparent modified-flag value is zero; this does not prove the flag's offset or mutation/persistence semantics.

The measured battery file is `E:/Howard/Bizhawk/NDS/SaveRAM/patched hge ap.SaveRAM`, SHA256 `67759699ee32ba3f5ec920efab5dad45e71306f8c93ba2dda1f233bc5062aea0`. It is a bare, separately measured AP-named save; do not substitute it for a probe save or a future hge↔hge fixture. The real HG profile observation above used `E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM`, SHA256 `e18a15c7e3a9959a687d9e069dda0617bcd735363a59ddf5378df88e3371b5e6`. A populated hge mon and the box dirty-flag behavior remain open, and the owner-played hge duo fixtures have not been staged.
