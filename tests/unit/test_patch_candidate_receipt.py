"""Private candidate build evidence; requires the owner's pinned ROM/toolchain."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_private_fr_candidate_discloses_unqualified_heap_clamp(tmp_path):
    roms = os.environ.get("SLINK_GEN3_ROMS")
    if not roms or not os.environ.get("SLINK_ARMGCC"):
        pytest.skip("set SLINK_GEN3_ROMS and SLINK_ARMGCC for private candidate build")
    rom = Path(roms) / "Pokemon - FireRed Version (USA).gba"
    env = dict(os.environ, TMP=str(tmp_path), TEMP=str(tmp_path))
    result = subprocess.run(
        [sys.executable, str(ROOT / "patch/tools/build.py"), "--target", "firered",
         "--trade-candidate", "--rom", str(rom)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((ROOT / "patch/build/candidate-firered-trade/receipt.json").read_text())
    assert receipt["arena_static_check"] == "skipped: heap clamp unqualified"
    assert receipt["production"] is False
    assert receipt["ready"] == 0
    assert receipt["capabilities"] == 3
    assert len(receipt["panel_detours"]) == 6
    patched = (ROOT / "patch/build/candidate-firered-trade/probe.gba").read_bytes()
    clean = rom.read_bytes()
    for key, size in (("actions",72),("descriptions",36)):
        table = receipt["panel_tables"][key]
        start = table["address"] - 0x08000000
        original = table["original_address"] - 0x08000000
        assert patched[start:start+size] == clean[original:original+size]
        assert int.from_bytes(patched[start+size:start+size+4],"little") >= 0x08000000
