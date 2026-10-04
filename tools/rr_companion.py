"""The Radical Red companion's identity, from ONE data source: the "rr" row of patch/dist/companion_pins.json.

patch/tools/build.py writes that row together with the build (patched_md5, rom_sha1, canonical_sha1, version, version_slot), and a
release stamp rewrites it, so no tool or test may carry the companion's sha1 as a literal. Which identity to ask for:

  rom_sha1()          the exact cartridge bytes on disk (admission rows, the staged patch/build/slink_RR.gba, the web patcher's md5)
  canonical_sha1()    the build with its fixed-width version field zeroed (patch/tools/rom_identity.py): what qualification is keyed on
  accepted_sha1s()    the exact hash plus the earlier builds the row lists as canonical-equal (equivalent_sha1s): any of these is the
                      same qualified build, so a receipt or pin carrying one of them is accepted
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:               # imported as a sibling by a script run from tools/
    sys.path.insert(0, str(ROOT))
from patch.tools import companion_pins  # noqa: E402

PINS = ROOT / "patch" / "dist" / "companion_pins.json"


def pin(path: Path = PINS) -> dict:
    return companion_pins.load(path)["pins"]["rr"]


def rom_sha1(path: Path = PINS) -> str:
    row = pin(path)
    if "rom_sha1" not in row:
        raise KeyError(f"{path}: the rr row has no rom_sha1; run python patch/tools/build.py --target radical_red")
    return row["rom_sha1"]


def equivalent_sha1s(path: Path = PINS) -> list[str]:
    """Earlier stamps of the same canonical build (patch/tools/build.py write_pin)."""
    return list(pin(path).get("equivalent_sha1s") or [])


def canonical_sha1(path: Path = PINS) -> str:
    return pin(path)["canonical_sha1"]


def accepted_sha1s(path: Path = PINS) -> frozenset[str]:
    row = pin(path)
    return frozenset({rom_sha1(path), *(row.get("equivalent_sha1s") or ())})
