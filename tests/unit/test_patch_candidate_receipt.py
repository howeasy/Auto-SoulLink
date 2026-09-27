"""Private candidate build evidence; requires the owner's pinned ROM/toolchain."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("title,filename", [
    ("firered","Pokemon - FireRed Version (USA).gba"),
    ("leafgreen","Pokemon - LeafGreen Version (USA).gba"),
    ("emerald","Pokemon - Emerald Version (USA, Europe).gba"),
])
def test_private_candidate_discloses_unqualified_heap_clamp(tmp_path,title,filename):
    roms = os.environ.get("SLINK_GEN3_ROMS")
    if not roms or not os.environ.get("SLINK_ARMGCC"):
        pytest.skip("set SLINK_GEN3_ROMS and SLINK_ARMGCC for private candidate build")
    rom = Path(roms) / filename
    env = dict(os.environ, TMP=str(tmp_path), TEMP=str(tmp_path))
    result = subprocess.run(
        [sys.executable, str(ROOT / "patch/tools/build.py"), "--target", title,
         "--trade-candidate", "--rom", str(rom)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = ROOT / f"patch/build/candidate-{title}-trade"
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["target"] == title
    assert receipt["arena_static_check"] == "skipped: heap clamp unqualified"
    assert receipt["production"] is False
    assert receipt["ready"] == 0
    assert receipt["capabilities"] == (87 if title == "emerald" else 23)
    if title == "emerald":
        assert receipt["frame_detour"]["continuation"] == {
            "address": 0x08000525, "gmain_literal": 0x0800053C, "gmain": 0x030022C0,
            "original_tail": "01d0e6f2d3fd6068",
        }
    assert set(receipt["rival_bindings"]) == {"RIVAL_START", "RIVAL_DUMMY"}
    assert set(receipt["sound_bindings"]) == {"SOUND_SE", "SOUND_FANFARE"}
    assert set(receipt["carrier_bindings"]) == {"CARRIER_SPAWN", "CARRIER_REMOVE", "CARRIER_CHOOSE"}
    assert len(receipt["panel_detours"]) == (3 if title == "emerald" else 6)
    patched = (output / "probe.gba").read_bytes()
    clean = rom.read_bytes()
    tables = (("actions",104),) if title == "emerald" else (("actions",72),("descriptions",36))
    for key, size in tables:
        table = receipt["panel_tables"][key]
        start = table["address"] - 0x08000000
        original = table["original_address"] - 0x08000000
        assert patched[start:start+size] == clean[original:original+size]
        assert int.from_bytes(patched[start+size:start+size+4],"little") >= 0x08000000
