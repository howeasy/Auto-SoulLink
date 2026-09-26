# BizHawk / melonDS platform facts

## Configuration (FILE: `E:/Howard/Bizhawk/config.ini`, BizHawk 2.11.1)

The melonDS sync settings live at `CoreSyncSettings["BizHawk.Emulation.Cores.Consoles.Nintendo.NDS.NDS"]`:

| Setting | Value | Consequence |
|---|---|---|
| `EnableJIT` | false | Interpreter; the precondition for reliable exec callbacks. Pin it false in every run config. |
| `UseRealTime` | **true** | RTC follows the wall clock, so it is **non-deterministic**. HGSS encounters and events depend on time of day. Run configs must set `false`. |
| `InitialTime` | `2010-01-01T00:00:00` | The RTC start when `UseRealTime=false`. Pin it per fixture (for example midday for day encounters). |
| `SkipFirmware` / `FirmwareOverride` | true / true | Boots straight into the game with a fixed firmware user |
| `UseRealBIOS` | false | HLE BIOS; no BIOS dumps needed |
| `UseDSi` | false | |

Other facts:
- **Paths:** the NDS `Save RAM` path entry is `./SaveRAM` under Base `./NDS`. Per-run configs redirect it to a short lane directory.
- **Controller:** `NDS Controller` buttons, plus analog `Touch X` / `Touch Y`. Touch is unused (D5).

The measured core facts (domains, registers, events) are in [prior_art.md](prior_art.md) §2. The live research probe results are added below when available.

## Platinum symbols (SOURCE: `platinumus.xMAP`)

| Symbol | Address | Note |
|---|---|---|
| `sSaveDataPtr` | 0x021C0794 | |
| `gSystem` | 0x021BF67C | |
| `Unk_021BF370` | 0x021BF370 (0xC0, `src/game_overlay.c`) | Same size as HGSS's `sOverlayRegions` (3×8×8) |
| `Overlay_LoadByID` / `Overlay_UnloadByID` | 0x02006590 / 0x02006514 | |
| `Party_AddPokemon` | 0x0207A048 | |
| `OS_WaitIrq` | 0x020C12B4 | |
| `BtlCmd_TryFaintMon` | 0x022418C0 | |

The names differ from HGSS but the roles match. The generator maps them by role per pack.

## Live research probe (PHYSICAL, research only; not G1 gate evidence)

- **Run by:** an Opus research worker on 2026-09-26, on BizHawk 2.11.1 / melonDS with `EnableJIT=false`.
- **Setup:** private configs (rewind and sound off; NDS SaveRAM redirected; `UseRealTime=false`, `InitialTime=2010-01-01T12:00:00`), with saves as copies.
- **Scripts and logs:** `C:/slink/g4/probe/` (`run.py`, `p1..p7*.lua`; `runs/<tag>/out.txt`). The coordinator re-read `hg_p6` (bench), `hg_p2` (PC census, hook args) and the romhash lines.

### API facts (row g)

- **Domains:**

  | Domain | Size |
  |---|---|
  | Main RAM | 4194304 |
  | Shared WRAM | 32768 |
  | ARM7 WRAM | 65536 |
  | SRAM | 524288 |
  | ROM | 134217728 |
  | ITCM | 32768 |
  | DTCM | 16384 |
  | BIOSes, Firmware | |

  `ARM9 System Bus` reports size **0**, but reads at 0x02xxxxxx work.
- **Registers:** `ARM9 r0..r15` and `ARM7 r0..r15`. There is **no CPSR**. `getregister` is **signed**, so mask with `& 0xFFFFFFFF`.
- **`event.on_bus_exec(fn, addr, name, scope)`:**
  - The callback gets `(addr, val, flags)`. `val` is the 32-bit word at the site, equal to the ROM/overlay bytes, so it **is the fire-time byte check at no cost**. `flags` is always 0x4000.
  - Scope: none or `"ARM9 System Bus"` works. `"Main RAM"`, `"System Bus"` and Main-RAM offsets return an **all-zero GUID and never fire** (no error), so a zero GUID must count as a failed registration.
  - A Thumb `addr+1` never fires. Use the even address.
- The callback runs **before** the instruction. `ARM9 r15` reads site+4 (Thumb) or site+8 (ARM); that offset is the only Thumb signal.
- **Joypad keys:** the usual buttons plus Touch, Touch X/Y, Lid, Power, Mic.

### Exec hooks (row a; 600 idle overworld frames)

| Site | Hits |
|---|---|
| `Main_RunOverlayManager` 0x02000E84 (Thumb) | 300 (field logic runs at 30 fps) |
| `OS_WaitIrq` 0x020D0E6C (ARM) | 600 |
| `VBlankCB_DmaTasksFramecounter` 0x0201A08C | 600 |
| Negatives: `DoSoftReset`, `Task_Blackout`, a `$d` literal | 0 |

### Overlay residency (rows b/c)

- **Load hook vs table:** 15 `HandleLoadOverlay` entry hits == 15 newly-active ids in `sOverlayRegions`, with r0 = id and r1 = load type. The table shows each load one frame later.
- **Boot sequence:** 0, 38, 60, 60, 74 (main menu), 36, 124, then field overlays 1, 2, 3, 27.
- **START menu** loads no overlay; only `taskman` changes (0 → heap pointer).
- **The party screen unloads every field overlay** and runs from static ARM9 with MAIN empty; overlays 1/2/3/27 reload on exit.
- **Same-address collision observed live at 0x021E5900** (shared by 40+ overlays):

  | Resident overlay | Hits | Bytes |
  |---|---|---|
  | ov60 | 1 | TitleScreen_Init `10b52c49…` |
  | ov1 | 352 | FieldMap_VBlankCallback `10b5041c…` |

  0 hits while MAIN was empty. **Residency + `val` are both required.**
- Menu-only ov74 hooks fired only while MAIN=[74], with bus bytes == `val` == ndspy file bytes.

### SaveData (row h)

- `[0x021D2228]` → SaveData; the heap address varies per boot (0x0227C204 / 0x0227C220).
- The file's active-bank **general block begins at SaveData+0x10**: 63012/63016 bytes equal; the 4 diffs are at +0x24/+0x28/+0x2C/+0x89. Party max/count read at +0x10+0x90.
- The PC block is at SaveData+0xF710 (this match is weak evidence: the boxes are mostly empty).
- `fs=[0x021D4158]`: `fs+0x0C == SaveData`; `fs+0x10` is 0 idle and non-zero with START open.
- **The archived `[0x02000BA8]+0x20` chain equals SaveData from about frame 197 onward.** A different global happens to hold the same pointer, so it is not a usable negative control at steady state. (Frames 1-196: garbage, then 0.) `sSaveDataPtr` is valid from frame 24.

### CPU at frame end (row m)

- **Never inside `OS_WaitIrq`:** 0/600 overworld, 0 START, 0 party. The main thread waits there, but the frame-end PC is the NitroSDK **idle thread's `OS_Halt`** (PC 0x020D3F64 = 0x020D3F58+8): 300/600 on the overworld (every other frame), 120/120 on the party screen. Other frame-end PCs: the ITCM IRQ handler, the BIOS vector, copy loops, ov1 code.
- **Counters:** `gSystem.vblankCounter` (+0x2C) advances 1 per frame; +0x30 is not a counter.

### ROM hash (row j)

`gameinfo.getromhash()` returns:

| ROM | Hash | Kind |
|---|---|---|
| HG | `258CEA3A…D788` | **MD5** |
| SS | `8A6C8888…73F2` | **MD5** |
| hge build | `CB2DC435…F4CEA1` | **SHA1** |

The algorithm depends on whether BizHawk's gamedb knows the ROM, so admission pins must hold both digests (Gen 3 `entry.lua` already indexes both).

### Buttons-only boot (row l)

| ROM | Result |
|---|---|
| HG + save | Overworld at **frame 1035**, deterministic over 6 pinned runs |
| hge + save | Overworld at frame 980 |
| SS cold boot (no save) | A/Start reach the intro, then **stall at "Please touch any topic"** (ov53). A new game needs touch or D-pad (D-pad untested). |

Consistent with D5 as long as SS fixtures come from the owner's save (D4). A scripted new game would need input beyond A/Start.

**SaveRAM naming:** BizHawk names the battery file after the **gamedb name** for known ROMs (`Pokemon - HeartGold Version (USA).SaveRAM`) and after the ROM basename for unknown ones (the hge build).

### Hook overhead (row f)

Unthrottled idle overworld, 600 frames per case:

| Hooks registered | fps |
|---|---|
| 0 | ~200 |
| 1 (never hit, per-frame, or 202k hits alike) | ~100 |
| 2 / 3 / 4 | 87 / 73 / 64 |
| 6 / 8 | 52 / 41.5 |
| 15 | 28 |

**The cost is per registered hook, not per hit.** The first hook adds about 5 ms/frame and each further one about 2 ms. Unregistering restores full speed. **On this machine more than 4 simultaneous hooks cannot hold 60 fps.**

### hg-engine (information only)

- MAIN = 129, 1, 131, 2, 3, 27; ov129 is resident from frame 9 (base reads "hg-engin").
- SaveData resolves exactly as in vanilla.
- `Party_AddMon`, `Task_Blackout`, `Encounter_GetResult`, `Main_RunOverlayManager` and `OS_WaitIrq` are byte-identical to vanilla on the bus.
- **`HandleLoadOverlay` is patched** (`ldr r2,[pc]; bx r2`). Its entry hook still fires for vanilla-path loads but **misses hge's own loads of 129/131**. Only the table sees every load.

### RTC (row k)

- `sRTCWork` @0x021D1048: date +0x10, time +0x20.
- Two pinned boots give identical values; a different `InitialTime` is followed exactly; `UseRealTime=true` gives the wall clock.
- Pinned game time = `InitialTime` + frames/60.
