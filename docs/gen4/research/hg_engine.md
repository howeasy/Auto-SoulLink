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
| `PCStorage_PlaceMonInBoxFirstEmptySlot` 0x02073BFC **and** `PlaceMonInFirstEmptySlotInAnyBox` 0x02073BB8 | the latter is the party-full catch path; 25 PC functions rewritten, `hooks:434-462` |
| `Save_WriteManFinish` 0x02027CEC | |
| `ScrCmd_GiveMon` 0x020541DC | |
| `ScrCmd_GiveEgg` 0x0204D248 | |
| NPC trade `_CreateTradeMon` 0x02259C40 | |
| evolution dispatch 0x02070E34 | `sub_02075A7C` itself is kept |
| hatch stats `sub_0206D328` | |
| `AddWildPartyPokemon` 0x0224855C | |
| `SetFixedWildEncounter` | |

The wild species/level roll is **wrapped**: vanilla code runs, and hge decodes species|form.

**Design consequence:** build the hge pack from the shared site set plus per-build symbols for the replaced ones. The client code is the same. Only the pack differs.

## 5. FYI for the owner's fork (not a Soul Link issue)

`hooks:632-636` files five **overlay-2** encounter-slot hooks (0x0224768C…0x022477C0) under `arm9`. `scripts/make.py:357-360` therefore writes them into `base/arm9.bin` at offset 0x24768C+, not into overlay 2, so the hge slot-roll C (`src/field/encounter_check.c:20`) is dead code. The region column should be `0002`.

## Open

- Battler→party mapping inside hge's battle (`CLIENT_PARAM` layout): use the shared `Battle_GetClientPartyMon`.
- The size effect of the `hooks:632-636` misfile.
- Whether overlays 129 and 131 overlap in practice (linker ranges overlap on paper).
- Per-build addresses of the replacement C (`offsets.ini`).
