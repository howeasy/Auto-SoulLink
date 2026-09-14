"""PHYSICAL lane for the rewritten Gen 1 modules (docs/gen1_requirements.md R-1, S, W-7, F-6).

    SLINK_LIVE=1 pytest tests/live/test_gen1_new_gates.py -q

Each case boots a committed battery save in EmuHawk, runs lua/tests/test_gen1_inspect_gate.lua
on the real cartridge, and then decodes the raw party bytes the gate dumped with the Python
codec: Lua on hardware and Python on the same bytes must agree field for field. Skipped, never
hung, without EmuHawk or the ROM dumps — and the release runner counts a skip as a failure.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from server.adapters import gen1_codec as codec  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 1 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/test_gen1_inspect_gate.lua"
ROMS = ("red", "blue", "yellow")
TARGETS = ("town", "battle")


@pytest.fixture(scope="module")
def emuhawk():
    import gen1_playthrough as play
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


def _lua_json(text: str, tag: str):
    m = re.search(rf"^{tag} (.*)$", text, re.M)
    assert m, f"gate printed no {tag} line"
    return json.loads(m.group(1))


def _lua_to_py(mon: dict) -> dict:
    """Shape the gate's Lua decode like codec.decode_party output for comparison."""
    out = dict(mon)
    for k in ("ot_name_bytes", "nickname_bytes"):
        out[k] = bytes(out[k])
    return out


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("rom", ROMS)
def test_inspect_gate_and_hardware_differential(rom, target, emuhawk):
    import gen1_playthrough as play
    from run_gb_gate import run_gate
    if not os.path.exists(os.path.join(REPO, play.ROMS[rom])) and \
            not os.path.exists(os.path.join(play.BUILD, f"gen1_{rom}.gb{'c' if rom == 'yellow' else ''}")):
        pytest.skip(f"{rom} cartridge dump not present")
    passed, path, text = run_gate(GATE, rom_key=rom, target=target, timeout=240, quiet=True)
    assert passed, f"gate FAILED on {rom}/{target}: {text[-1500:]}"

    raw = bytes.fromhex(re.search(r"^PARTY_RAW ([0-9A-F]+)$", text, re.M).group(1))
    lua_party = _lua_json(text, "PARTY_LUA")
    py_party = codec.decode_party(raw)
    assert len(lua_party) == len(py_party) >= 1
    for lua_mon, py_mon in zip(lua_party, py_party, strict=True):
        lua_mon = _lua_to_py(lua_mon)
        for field, want in py_mon.items():
            assert lua_mon.get(field) == want, (rom, target, field, lua_mon.get(field), want)

    hello = _lua_json(text, "HELLO")
    from tests.unit import protocol_schema as ps
    assert ps.validate_event(hello) == []
    assert hello["party"][0]["key"] == codec.key(py_party[0])
    assert "write-safe overworld checkpoint reached" in text and "[ok] write-safe" in text
