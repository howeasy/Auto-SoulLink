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
