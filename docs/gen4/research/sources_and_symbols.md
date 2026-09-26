# Symbol source, HG vs SS, key addresses

## Symbol source: pret xMAP linker maps (SOURCE)

- pret/pokeheartgold cannot be built for shipping: it needs the non-redistributable Metrowerks `mwccarm`. pret's CI builds it anyway and publishes the linker maps on an **`xmap` branch**.
  - `heartgoldus.xMAP` and `soulsilverus.xMAP`, pinned in [README.md](README.md).
  - pret/pokeplatinum publishes `platinumus.xMAP` the same way.
- Each map lists every symbol, statics included, as `address size section name (object)`. Example line: `021D2228 00000004 .bss sSaveDataPtr (save.o)`.
- The CI build only publishes after a sha1-matching build, so the addresses describe the retail ROMs whose sha1s are pinned.
- A Gen 3-style generator consumes the maps and emits committed JSON packs; Lua never parses a map.

## HG vs SS (FILE, measured with ndspy + both xMAPs)

| Check | Result |
|---|---|
| Decompressed arm9 length | Equal (1120352 B); 2179 bytes differ, all data or version constants |
| Overlays | 129 each; **114/129 byte-identical**; all overlay RAM addresses equal. Differing: 1, 2, 12, 18, 25, 39, 45, 60, 62, 70, 73, 74, 75, 76, 112 (data only where it matters) |
| Symbols | 36737 each, same names; **1234** differ in address, **only** in `overlay_18.o` (Pokédex, 498), `overlay_74_thumb.o` (304), `ov18_*` (258), `nitrocrypto.o` (67), intro movie / title screen / main menu. **0** in static ARM9 or the battle overlay. |

**Consequence:** one symbol set serves both titles. The generator asserts HG==SS for every symbol a pack uses and pins `expected_hex` per title.

## Key addresses (SOURCE: xMAP, identical in HG and SS)

| Symbol | Address | Where | Note |
|---|---|---|---|
| `sSaveDataPtr` | 0x021D2228 | .bss save.o | live `SaveData*` (heap) |
| `sOverlayRegions` | 0x021D0DF0 (0xC0) | .bss poke_overlay.o | `PMiLoadedOverlay {FSOverlayID id; BOOL active;}[3 regions][8]`, `src/poke_overlay.c:13-20` |
| `gSystem` | 0x021D110C | .bss system.o | |
| `HandleLoadOverlay` | 0x02006FF8 | arm9 | `src/poke_overlay.c:64` |
| `Save_WriteManFinish` | 0x02027CEC | arm9 | save settled |
| `Encounter_GetResult` | 0x020506F4 | arm9 | `src/encounter.c:96-108` |
| `Task_Blackout` | 0x02052858 | arm9 | `src/blackout.c:189` |
| `PCStorage_PlaceMonInBoxFirstEmptySlot` | 0x02073BFC | arm9 | |
| `Party_AddMon` | 0x02074524 | arm9 | |
| `BtlCmd_TryFaintMon` | 0x0223E22C | ov12 | `src/battle/battle_command.c:978-986` |

**Pinnable offline (FILE).** Site bytes read from the ndspy-decompressed images are identical in HG and SS:

| Site | Bytes |
|---|---|
| `BtlCmd_TryFaintMon` | `70b50d1c061c281c` (Thumb `push {r4-r6,lr}`) |
| `Task_Blackout` | `f8b586b0061cfdf7` |
| `HandleLoadOverlay` | `f8b50c1c0021c943` |

## Overlay address sharing (FILE)

- ov12 (battle) loads at **0x022378C0**, size 0x37380; ov2 (field encounter) at 0x02245B80.
- **Overlays 57, 58, 70 and 72 load at ov12's address.** An execute hook on ov12 code can therefore fire while a different overlay occupies that RAM.
- Every overlay-site hook needs a fire-time residency check (the `sOverlayRegions` entry is active) **and** a byte check.

## Correction to the archived Gen 4 probe

`archive/claude/gen4-prep-planning:docs/gen4/platform_probe.md` §2 stated that `sSaveDataPtr` is 0x02111880, reached as `[0x02000BA8]+0x20`. **Both halves are wrong about names (xMAP):**
- 0x02000BA0..0x02000BC4 is crt0's `_start_ModuleParams` (.rodata), so `[0x02000BA8]` is a module-params word (the .bss start, 0x02111860).
- 0x02111880 is inside `main.o _02111868` (.bss, 0x1C bytes) at +0x18. It is a different global that happens to hold `SaveData*` after the save loads; the owner's AP probes saw it become non-zero at about frame 134.
- The real `sSaveDataPtr` is 0x021D2228, and hg-engine's `rom.ld:552` lists the same value.

G1 row h must resolve SaveData through 0x021D2228, confirmed by the save page signature. The archived chain is the negative control.
