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
