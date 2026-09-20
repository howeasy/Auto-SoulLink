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


SCRIPTED_GATE = "lua/tests/test_gen1_scripted_gate.lua"


@pytest.mark.parametrize("rom", ("red", "blue", "yellow"))
def test_new_game_lab_route_emits_the_engine_sequence(rom, emuhawk, monkeypatch):
    """S-1 PHYSICAL: a cold cartridge, NEW GAME -> starter -> rival battle by buttons only, with
    the signals layer armed. The engine-site sequence must be the one pret's scripts imply."""
    from run_gb_gate import run_gate
    monkeypatch.setenv("SLINK_SCRIPT_CHAIN", "lab")
    monkeypatch.setenv("SLINK_SCRIPT_PLAYER", "a" if rom == "red" else "b")
    monkeypatch.delenv("SLINK_SCRIPT_FLUSH", raising=False)
    passed, path, text = run_gate(SCRIPTED_GATE, rom_key=f"{rom}_cold", target="town", timeout=600, quiet=True)
    assert passed, f"scripted lab route FAILED on {rom}: {text[-1500:]}"
    kinds = [tok.split("@")[0] for tok in re.search(r"^SIGNALS (.*)$", text, re.M).group(1).split()]
    if rom == "yellow":
        # Yellow opens with Oak's Pikachu DEMONSTRATION battle (BATTLE_TYPE_PIKACHU, wCurOpponent
        # $54) before the gift, so its sequence is battle/wild first and the starter second; the
        # rival battle still follows through AddPartyMon (a0349b8's driver expectations).
        assert kinds[:3] == ["battle_begin", "wild_begin", "battle_end"], kinds[:6]
        assert kinds[3:6] == ["starter_begin", "add_party_mon", "starter_end"], kinds[:6]
        assert kinds[6:8] == ["battle_begin", "add_party_mon"], kinds[6:9]
        assert kinds.count("battle_faint") >= 1 and kinds[-1] == "battle_end", kinds[-4:]
        assert "blackout" not in kinds and "capture_box" not in kinds
    else:
        # gift starter, then the rival battle: its enemy party is built through AddPartyMon too
        assert kinds[:3] == ["starter_begin", "add_party_mon", "starter_end"], kinds[:6]
        assert kinds[3:5] == ["battle_begin", "add_party_mon"], kinds[3:6]
        assert kinds.count("battle_faint") >= 1 and kinds[-1] == "battle_end", kinds[-4:]
        assert kinds.count("battle_loop_head") >= 3
        assert "blackout" not in kinds and "wild_begin" not in kinds and "capture_box" not in kinds
    raw = bytes.fromhex(re.search(r"^PARTY_RAW ([0-9A-F]+)$", text, re.M).group(1))
    (mon,) = codec.decode_party(raw)
    # a real L5 starter (add_mon.asm stores exp_for_level): 135 on Bulbasaur/Charmander's
    # curves, 125 on Pikachu's MEDIUM_FAST (data/pokemon/base_stats/pikachu.asm:13).
    assert mon["level"] == 5 and mon["exp"] == (125 if rom == "yellow" else 135)


# Red and Blue only: on Yellow the starter is Pikachu, whose only damaging move (Thundershock)
# is super-effective against Route 1's Pidgey and KOs it on the hunt's weakening turn before
# the throw (three straight runs, 2026-09-20: 'unexpected no_catch (foe KO)'). A driver limit
# of the shared hunt module, not the client: the Yellow client code path is identical.
@pytest.mark.parametrize("rom", [r for r in ROMS if r != "yellow"])
def test_slow_name_capture_survives_2400_idle_frames(rom, emuhawk):
    """FIX-ACQ PHYSICAL: production TX after 40 seconds on the nickname alphabet."""
    from run_gb_gate import run_gate
    passed, path, text = run_gate(
        "lua/tests/test_gen1_slow_name_gate.lua", rom_key=rom,
        target="battle", timeout=600, quiet=True,
    )
    assert passed, f"slow_name FAILED on {rom}; receipt {path}: {text[-2500:]}"
    tx = [json.loads(line[3:]) for line in text.splitlines() if line.startswith("TX ")]
    captures = [msg for msg in tx if msg.get("event") == "capture"]
    assert len(captures) == 1
    assert not any(msg.get("event") == "no_catch" for msg in tx)
    cap = captures[0]
    assert cap["area_id"] == "route_1" and cap["in_box"] is False
    assert cap["nickname"] == "AAA"
    from tests.unit import protocol_schema as ps
    assert ps.validate_event(cap) == []
    receipt = re.search(
        r"^SLOW_NAME_RECEIPT acquire_frame=(\d+) capture_frame=(\d+) gap=(\d+) "
        r"hold=(\d+) captures=1 no_catch=0 name=AAA$", text, re.M,
    )
    assert receipt, "missing measured naming receipt"
    acquired, captured, gap, hold = map(int, receipt.groups())
    assert captured - acquired == gap and gap >= hold == 2400
    begin = re.search(r"^NAMING_HOLD_BEGIN frame=(\d+) input_hits=(\d+)$", text, re.M)
    end = re.search(r"^NAMING_HOLD_END frame=(\d+) frames=2400 input_hits=(\d+)$", text, re.M)
    assert begin and end
    assert int(end[1]) - int(begin[1]) == 2400 and int(end[2]) > int(begin[2])
