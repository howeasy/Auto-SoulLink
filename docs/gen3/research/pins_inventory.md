# Gen 3 Plan Pins Inventory

**Date generated:** 2026-09-21  
**Command:** `python tools/gen3_pins.py`

## Artifacts table

| Artifact | Hash Type | Hash | Notes |
|---|---|---|---|
| bizhawk_emuawk.exe | sha256 | f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd | BizHawk 2.11.1 |
| bizhawk_mgba.dll | sha256 | ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1 | mGBA core DLL |
| bizhawk_cores.dll | sha256 | 444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5 | BizHawk emulation cores |
| rr_base.gba | md5 | 8529f3a45d32bce4da637976fcf269d4 | Radical Red 4.1 base ROM |
| rr_base.gba | sha1 | 964f951a0fdaf209e4ea1344883ef0d557bb3a80 | |
| slink_RR.gba | md5 | MISSING | Patched build not yet built |
| slink_RR.gba | sha1 | MISSING | Path: `patch/build/slink_RR.gba` |
| firered.gba | md5 | MISSING | Not found in standard locations |
| firered.gba | sha1 | MISSING | Checked: `E:/Google Drive/SLink/Pokemon - Fire Red.gba`, `E:/Howard/GBA/Pokemon - Fire Red.gba` |
| leafgreen.gba | md5 | MISSING | Not found in standard locations |
| leafgreen.gba | sha1 | MISSING | Checked: `E:/Google Drive/SLink/Pokemon - Leaf Green.gba`, `E:/Howard/GBA/Pokemon - Leaf Green.gba` |
| slink_rr.ups | sha256 | 3baf01003de0e851001134683d990b8db915b9fa9d39f4a0009cbabca4cfdf08 | SLink companion UPS patch |

## Missing artifacts

### slink_RR.gba (patched RR build)
- **Path:** `patch/build/slink_RR.gba`
- **Action:** Build with `python patch/tools/build.py --rom "E:/Google Drive/SLink/Pokemon - Radical Red.gba"`

### firered.gba (clean FireRed US 1.0)
- **Paths checked:**
  - `E:/Google Drive/SLink/Pokemon - Fire Red.gba`
  - `E:/Howard/GBA/Pokemon - Fire Red.gba`
- **Action:** Place clean FireRed US 1.0 (1.0 sha1 TBD) at one of the checked paths

### leafgreen.gba (clean LeafGreen US 1.0)
- **Paths checked:**
  - `E:/Google Drive/SLink/Pokemon - Leaf Green.gba`
  - `E:/Howard/GBA/Pokemon - Leaf Green.gba`
- **Action:** Place clean LeafGreen US 1.0 (1.0 sha1 TBD) at one of the checked paths

## Coordinator addendum (2026-09-21): artifacts found outside the script search paths

| Artifact | Path | sha1 | md5 | bytes | Note |
|---|---|---|---|---|---|
| firered_usa | `E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba` | `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` | `e26ee0d44e809351c8ce2d73c7400cdd` | 16777216 | pret firered.sha1 = 41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc -> MATCH (US 1.0) |
| firered_rev1 | `E:/Howard/Dev/Pokemon_SoulLink/Pokemon - FireRed Version (USA, Europe) (Rev 1).gba` | `dd5945db9b930750cb39d00c84da8571feebf417` | `51901a6e40661b3914aa333c802e24e8` | 16777216 | pret firered_rev1.sha1 = dd5945db9b930750cb39d00c84da8571feebf417 -> MATCH (v1.1, not admitted) |
| slink_RR_root_build | `E:/Google Drive/SLink/patch/build/slink_RR.gba` | `b7d1e0756fcc66575878affc8f7b95c45386bb1c` | `bf8e94a01c0aee0aa7eb37c7333329af` | 33554432 | patcher.py:72 patched md5 8dcffce7... -> MISMATCH (stale build?) |
| rr_clean_root_build | `E:/Google Drive/SLink/patch/build/rr_clean.gba` | `964f951a0fdaf209e4ea1344883ef0d557bb3a80` | `8529f3a45d32bce4da637976fcf269d4` | 33554432 | build.py:90 base md5 8529f3a4... -> MATCH |

LeafGreen: no dump found under E:/Howard or E:/Google Drive/SLink (depth 3) -> owner item for G0.

## G0 addendum (2026-09-21)

| Artifact | sha1 | md5 | Note |
|---|---|---|---|
| `E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba` | `574fa542ffebb14be69902d1d36f1ec0a4afd71e` | `612ca9473451fa42b51d1711031ed5f6` | MATCH pret leafgreen.sha1 (US 1.0) |
| `patch/build/slink_RR.gba` rebuilt from `patch/dist/SLink-RR.ups` over the verified base via `patch/tools/make_ups.py ups_apply` | `b7d1e0756fcc66575878affc8f7b95c45386bb1c` | `bf8e94a01c0aee0aa7eb37c7333329af` | MISMATCH vs `server/patcher.py:72` |

## C5-3 companion rebuild (2026-09-24)

Owner approved the RR companion rebuild on 2026-09-24. It was built from `patch/src` at `f6d503f4`, which adds FORCE_MOVE_SLOT fix `15a274ec` + `21df5314`, the handlers.c guards, and OP_RIVAL_SWAP 28 `2dc1b750` on top of the `cd11fca7` build. Build command: `python patch/tools/build.py` (Battle Calc included), with xPack arm-none-eabi-gcc 15.2.1-1.1 and base RR md5 `8529f3a45d32bce4da637976fcf269d4`. Control check: the same toolchain on the `cd11fca7` source reproduces the old `bf8e94a0…` ROM and a UPS byte-identical to the old one.

| Artifact | sha1 | md5 | Note |
|---|---|---|---|
| `patch/dist/SLink-RR.ups` (12744 B) | `e3d16c3374d4e05647524522d292abf90998fa81` | `c4cb17a641569e848d1c4f4a6dcbdca2` | sha256 `9cd75e6442ca937c3c46eb1a1aa642d0746a549e81204e164a74bd29a3cd82e6` |
| `patch/build/slink_RR.gba` (33554432 B) | `ea5352f8a3b9073f8ae20870ad12857925d442cd` | `6cf77ba4a63634a0fd452be6f206bfc3` | `ups_apply(base, ups)` == built ROM byte for byte |

The old→new diff touches only SLink-owned bytes: backup BL `0x0804C10E`/`0x0804C214`, the start-menu setup literal `0x0806ED58`, the battletext detour BL `0x080D87C0`, start-menu words `0x09148FDC` and `0x09149030..35`, and the code region `0x08378F74..0x0837B2E5`. The hook BL at `0x0800051A` and CODE_BASE `0x08378F70` did not move.

Re-pinned: `server/patcher.py` (RR `patched_md5`), `patch/README.md` (result md5), `data/games/gen3_rr/engine_signals.json` (companion `rom_md5`/`rom_sha1`, regenerated), `docs/gen3_engine_sites.md` (regenerated), `tools/pin_gen3_site.py` (ROM_SPECS), and `tools/research/rr_save_callers.py` (ROMS). The profile and write_checkpoint pins (`tools/gen_gen3_profile.py`, `tools/gen_gen3_write_checkpoint.py`, `tests/unit/test_gen3_profile.py`, and the RR `profile.json`/`write_checkpoint.json`) are re-pinned by W1's regeneration.

Anchors: all 19 PINNED companion sites in `engine_signals.json` are unchanged (address, offset and bytes). The only regenerated-inventory changes are two UNVERIFIED diagnostics: the backup literal's aligned hit moved from 0x8379708 to 0x8379724, and the party-base literal count went from 910 to 911. There is no `data/games/gen3_rr/admission.json`: Gen 3 admission is the `engine_signals.json` artifact table (`lua/gen3/entry.lua`).

The rollback bundle stays frozen at the old `bf8e94a0…`/`84082ec3…` build (owner ruling (c)).
