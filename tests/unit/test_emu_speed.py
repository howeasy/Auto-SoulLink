"""W23 EMU-SPEED: Gen 3 drivers turn rendering off under a pcall guard, and gate/duo run
configs turn sound off."""
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import run_gate  # noqa: E402

GUARDED = re.compile(r"pcall\(function\(\) client\.invisibleemulation\([^\n]*\) end\)")


@pytest.mark.parametrize("rel", [
    "lua/tests/duo/duo_gen3_main.lua",
    "lua/tests/gen3_gatelib.lua",
    "lua/tests/gen3_boot_check.lua",   # M.open: every gen3 fixture/mkstates/probe driver
    "lua/tests/mkstate.lua",
])
def test_driver_turns_rendering_off_under_pcall(rel):
    src = Path(ROOT, rel).read_text(encoding="utf-8")
    calls = [ln for ln in src.splitlines() if "client.invisibleemulation" in ln
             and not ln.lstrip().startswith("--")]
    assert calls, f"{rel} never calls client.invisibleemulation"
    for ln in calls:   # BizHawk API members are userdata: an unguarded call can raise
        assert GUARDED.search(ln), f"unguarded invisibleemulation in {rel}: {ln.strip()}"


def test_boot_check_opens_invisible():
    src = Path(ROOT, "lua/tests/gen3_boot_check.lua").read_text(encoding="utf-8")
    body = src.split("function M.open(name)", 1)[1].split("\nend", 1)[0]
    assert "client.invisibleemulation" in body


def test_gate_config_disables_sound(tmp_path):
    src = tmp_path / "config.ini"
    src.write_text(json.dumps({"SoundEnabled": True, "SoundEnabledNormal": True,
                               "SoundEnabledRWFF": True, "SoundVolume": 50}), encoding="utf-8")
    dst = tmp_path / "out.ini"
    run_gate.write_gate_config(str(src), str(dst))
    cfg = json.loads(dst.read_text(encoding="utf-8"))
    assert (cfg["SoundEnabled"], cfg["SoundEnabledNormal"], cfg["SoundEnabledRWFF"],
            cfg["SoundVolume"]) == (False, False, False, 0)
