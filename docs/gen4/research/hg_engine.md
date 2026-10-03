# hg-engine vs vanilla HeartGold

Source: the owner's fork at `E:/Howard/HGEngine_ROMHack/hg-engine`, commit `fc5175764` (upstream BluRosie/hg-engine, plus a remote-build pipeline).

| Card | Result |
|---|---|
| G4-R3 `cx-a2bd6e6a` | 20 accepted, 0 rejected, 3 open |
| G4-R5 `cx-e3501ded` | 26 accepted, 0 rejected, 4 open |

The coordinator re-checked these directly:
- `Makefile` is IPKE-only.
- `ALLOW_SAVE_CHANGES`, `ITEM_POCKET_EXPANSION` and `NUM_PC_BOXES 30` are on.
- `hooks:150`, `:287` and `:632-636`.
- There are no hook lines for the shared vanilla sites.
- The save geometry was measured on a real hge save (FILE).

## 1. Build and identity

- **HeartGold USA only:** `Makefile:23-30` errors on any gamecode but `IPKE`. SoulSilver is not supported.
- **Builds on Linux only.** The owner's fork builds on the `hgbox` box through `build-remote.sh`. The output `test.nds` is about 183 MiB, larger than 128 MiB.
- **Header unchanged** (`base/header.bin` is re-used), so the gamecode stays `IPKE`. Admission must use the build sha1, never the header.
- **Symbols come only from the build:** `build/linked.o` (overlay 129) and `build/<overlay>_linked.o`, exported as `build/rom_gen.ld` and `offsets.ini` (`Makefile:271-273, 303-307`; `scripts/generate_ld.py:36-80`).
  - There is no `.map` or `.sym`.
  - The export keeps only nm types `t`/`d`, so a `.bss` symbol is dropped. Put any mailbox in `.data`.
- **Reproducibility is unproven.** devkitARM and armips are unpinned (`Makefile:186-188`). Pin each build by the sha1 of its output.
- **Code injection:**
  - Overlay **129** at 0x023D8000 is resident from boot (a `Main()` hook at 0x02000CD0, `armips/asm/syntheticoverlay.s`); `src/*.c` code runs at 0x023D8060+.
  - Overlay **130** at 0x023C4000 holds the battle C and is auto-loaded together with ov12 (`src/overlay.c:9-17`).
  - Overlay **131** at 0x023C8000 holds the field C.
  - Overlay ids 129-149 are new.

## 2. Record (SOURCE)

- **Same geometry** (0x88 / 0xEC) and the **same vanilla encryption, checksum and shuffle code**: `GetBoxMonData`/`SetMonData` entries are not hooked (`rom.ld:59,61`).
- Bit-level changes (`include/pokemon.h:226-265`):
  - Block A +0x08: `exp:21, unused:10, abilityMSB:1`, so ability = `byte@0x0D | abilityMSB<<8` (9 bits).
  - Block B +0x18: `fateful:1, gender:2, form:5`.
  - Block B +0x19 bit 0: hidden ability.
  - Block B +0x1A u16: nature / IV override / ability slot.
- ID spaces:

  | Space | hge | Vanilla |
  |---|---|---|
  | Species (canonical) | 1075 | 493 |
  | Species incl. forms (`MAX_SPECIES_INCLUDING_FORMS`) | 1476, fits 11 bits | |
  | Moves | 923 | 468 |
  | Items | 2684 | |
  | Abilities | 319 | |

  Fairy is `TYPE_FAIRY_INTERNAL 17`.
- The wild encounter word is `species(0x7FF) | form(0xF800)` (`asm/other_hook.s:206-263`).

## 3. Save (SOURCE + FILE)

- `ALLOW_SAVE_CHANGES` is on (`include/config.h:25-27`), and the source says it "will break compatibility with PKHeX". The changes:
  - misc array +4 stored `PartyPokemon` (`include/save.h:114-120`)
  - `NUM_PC_BOXES 30` (`include/constants/save.h:26`)
  - expanded pockets (`ITEM_POCKET_EXPANSION`, `include/constants/item.h:2870-2891`)
- **FILE** (`E:/Howard/Bizhawk/NDS/SaveRAM/patched hge ap.SaveRAM`):

  | Block | Location | Size |
  |---|---|---|
  | General | bank+0 | **0xFFA0** |
  | PC | bank+**0x10000** | **0x1E4FC** |

  Same footer magic. The codec takes its geometry from the footers and the box count from the pack.
- `sSaveDataPtr` is still **0x021D2228** (`rom.ld:552`; the same as the vanilla xMAP). Under the default config `SaveData_New` is hooked and heap-allocates (`hooks:402`, `src/save.c:139-147`), so the pointer must be followed on every read.
- Save arrays stay at 42.
- The footer sizes above establish **block geometry**, not a populated party offset, live PC dirty-flag address, or in-game persistence. The measured empty hge save has no mon to disambiguate party candidates; the `general+0x90` claim in [offline_measurements.md](offline_measurements.md) is a source projection, not a unique FILE result. G2 still needs a populated-mon decode and a dirty-flag mutation/save/reload receipt tied to hashes of the exact battery files. The 30-box C struct places `boxModifiedFlag` after `0x1000 * 30` bytes, at `PCStorage+0x1E004` (`include/pokemon_storage_system.h:50-59`; mutator `src/pokemon_storage_system.c:374-379`), but that source calculation is not the PHYSICAL persistence receipt.

## 4. Site survival: which vanilla hooks still work (SOURCE, G4-R5)

A hook line with a register writes an 8-byte `ldr rX,=sym; bx rX` trampoline. With no register it writes a 0x1C-byte full replacement. Either way the vanilla entry bytes are clobbered (`scripts/make.py:138-198`).

**Shared by vanilla HG and hge** (not in `hooks`):

| Site | Address |
|---|---|
| `Party_AddMon` | 0x02074524 |
| `Encounter_GetResult` | 0x020506F4 |
| `Task_Blackout` | 0x02052858 |
| `GetMonData` / `SetMonData` entries | 0x0206E540 / 0x0206EC40 |
| `Battle_GetClientPartyMon` (+`Size`) | 0x0223A880 (+0x0223A834) |
| `CheckIfAnyoneShouldFaint` | 0x0224DC74 (called from hge C) |
| `sOverlayRegions` (never patched) | 0x021D0DF0 |

Also kept:
- the field warp / location copy
- the vanilla battle script command table 0x0226C6C8 (commands < 0xE1)
- the catch tasks (only `CalculateBallShakes` is replaced)

**Replaced in hge; re-derive per build:**

| Site | hge replacement |
|---|---|
| `HandleLoadOverlay` 0x02006FF8 | `hooks:287`, C in ov129; adds linked overlays and `MAX_ACTIVE_OVERLAYS 8` |
| `UnloadOverlayByID` | |
| `BtlCmd_TryFaintMon` 0x0223E22C | `hooks:150`, full C in ov130, `battle_script_commands.c:5286-5313` |
| `BattleScriptCommandHandler` 0x0223CF68 | |
| `InitFaintedWork` | |
| `BtlCmd_PlayFaintAnimation` | |
| `PCStorage_PlaceMonInBoxFirstEmptySlot` 0x02073BFC **and** `PlaceMonInFirstEmptySlotInAnyBox` 0x02073BB8 | the latter is the party-full catch path; **29** `PCStorage_*` functions rewritten, `hooks:433-461` (the `#pc box expansion` block; `hooks:462 sub_02074128` is its one unnamed row and is not counted) |
| `Save_WriteManFinish` 0x02027CEC | |
| `GiveMon` 0x020541DC (script helper; the script command `ScrCmd_GiveMon` 0x0204D088 is **kept**, FILE-verified) | |
| `ScrCmd_GiveEgg` 0x0204D248 | |
| NPC trade `_CreateTradeMon` 0x02259C40 | |
| evolution dispatch 0x02070E34 | `sub_02075A7C` itself is kept |
| hatch stats `sub_0206D328` | |
| `AddWildPartyPokemon` 0x0224855C | |
| `SetFixedWildEncounter` | |

The wild species/level roll is **wrapped**: vanilla code runs, and hge decodes species|form.

**Design consequence:** build the hge pack from the shared site set plus per-build symbols for the replaced ones. The client code is the same. Only the pack differs.

**Historical error and declared-image correction.** [data/hge_site_survival.json](data/hge_site_survival.json) retains the old ARM9 zero-byte reads in `historical_wrong_image`. The old `.cache/gen4/offline/common.py:43-58` chose ARM9 before overlays; hge's expanded ARM9 overlaps these ov12 addresses. The current `hge_binary`/`hge_bytes` fields select the declared ov12 image: the faint entry is patched, while `ov12_0223843C` has a matching 16-byte prefix, not a proved unchanged full function. The exported faint replacement at `0x023CEDD0` (`.cache/gen4/hge/offsets.ini:91`) also has separately measured ov130 FILE bytes. Live owning-overlay residency and game behavior remain OPEN. The generator must resolve image identity and complete extent rather than reusing the historical address-first resolver.

## 4b. Battle data layout vs vanilla (G4-R9 `cx-d11ad936`)

The coordinator re-checked `hooks:387` and `include/battle.h:881, 914, 1392, 1403`, and `src/battle/battle_start.c:34-38`.

**One offset table serves both ROMs.** These are identical in vanilla HGSS and the hge build (pret `battle.h` vs hge `include/battle.h:852-923, 1392-1446, 1587`):

| Field | Offset |
|---|---|
| ctx pointer | `BattleSystem+0x30` |
| selected party index per battler (6 = empty) | `ctx+0x219C` |
| `battleMons[i]` | `ctx+0x2D40 + 0xC0*i` |
| (vanilla `unk_312C`) | `ctx+0x312C` |
| BattleMon species / moves / form-shiny / level / nickname / hp / maxHp / exp / personality / status / status2 / gender | 0x00 / 0x0C / 0x26 / 0x34 / 0x36 / 0x4C / 0x50 / 0x64 / 0x68 / 0x6C / 0x70 / 0x7E; **hp is s32, full four bytes**, in both hge (`include/battle.h:905`) and vanilla (`include/battle/battle.h:248`); party-tail HP remains u16 (`include/pokemon.h:345` in hge; `include/pokemon_types_def.h:203` in pret) |
| BattleMon size | 0xC0 |
| `BattleSetup` (unchanged) | `{type 0x0, party[4] 0x4, winFlag 0x14}` |
| outcome byte (vanilla accessors, unhooked) | `BattleSystem+0x2420` |

Battler→party resolution is vanilla code in both ROMs (`Battle_GetClientPartyMon` 0x0223A880).

The shared layout does **not** prove the active-faint mechanism. The hge script command is replaced in ov130, while controller command-11 coverage, both-copy HP effects, faint presentation, and native win/loss healing still require build-specific SOURCE checks and PHYSICAL receipts. Do not infer a working hge `TurnEnd` sweep or an acceptable D7 latency from offsets alone.

**Differences, carried by the pack:**
- **Ability:** vanilla `u8` @0x27; hge `u16` @**0x7A**, with 0x27 now a dead `dummy` (`armips/asm/abilities.s:59-69, 180`).
- **0x30C4-0x30DB:** repurposed in hge. Not read by Soul Link.
- **The struct grows past vanilla's 0x3158** (move table at 0x317E, total ≥0x6B40).
- **Allocation:** hge allocates the context itself; `ServerInit` is replaced (`hooks:387`, `battle_start.c:37`).

Which offsets apply comes from the pack chosen by admission, not from a runtime probe.

## 5. FYI for the owner's fork (not a Soul Link issue)

`hooks:632-636` files five **overlay-2** encounter-slot hooks (0x0224768C…0x022477C0) under `arm9`. `scripts/make.py:357-360` therefore writes them into `base/arm9.bin` at offset 0x24768C+, not into overlay 2, so the hge slot-roll C (`src/field/encounter_check.c:20`) is dead code. The region column should be `0002`.

## Open

- The size effect of the `hooks:632-636` misfile.
- Whether overlays 129 and 131 overlap in practice (linker ranges overlap on paper).
- Per-build addresses of the replacement C (`offsets.ini`).
