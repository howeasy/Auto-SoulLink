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
VANILLA_ROMS = ("red", "blue", "yellow")
# The built pureRGB cartridges (P3b-e). They are ordinary rom keys here: gen1_playthrough stages
# them from data/purergb_sources.lock.json, run_gb_gate carries their SaveRAM names and fixtures,
# and gen1_gate admits them by sha1, so a pure title boots exactly like a vanilla one.
PURE_ROMS = ("purered", "pureblue", "puregreen")
ALL_ROMS = VANILLA_ROMS + PURE_ROMS
TARGETS = ("town", "battle")


def _selected_roms() -> tuple:
    """Which cartridges this run boots, from SLINK_GEN1_ROMS (space/comma separated).

    The release gate's `inspect-purergb` lane selects the pure titles through this rather than
    pytest's `-k`: the lane scorer counts a deselection as a failure, so a subset has to be built,
    not filtered out. Unset means every cartridge -- the vanilla lane pins the vanilla three so
    its coverage does not silently grow, and the pure lane pins the pure three.
    """
    wanted = tuple(part for part in re.split(r"[,\s]+", os.environ.get("SLINK_GEN1_ROMS", "")) if part)
    unknown = [rom for rom in wanted if rom not in ALL_ROMS]
    if unknown:
        raise ValueError(f"unknown SLINK_GEN1_ROMS entries {unknown}; known: {ALL_ROMS}")
    return wanted or ALL_ROMS


ROMS = _selected_roms()


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


def _skip_if_absent(rom: str, target: str) -> None:
    """Skip when this cartridge or its battery save is not in the tree.

    Both facts are checked because the inspect gate boots a fixture: a pure title can have its
    staged .gbc and no SaveRAM yet (tools/gen1_fixtures.py builds those per title), and a vanilla
    title can have the dump and no fixture. In a release lane a skip is a lane failure, which is
    the point -- the lane's inputs have to be there.
    """
    import gen1_playthrough as play
    if rom in PURE_ROMS:
        dump_ok = os.path.exists(os.path.join(play.BUILD, f"gen1_{rom}.gbc"))
    else:
        ext = "gbc" if rom == "yellow" else "gb"
        dump_ok = (os.path.exists(os.path.join(REPO, play.ROMS[rom]))
                   or os.path.exists(os.path.join(play.BUILD, f"gen1_{rom}.{ext}")))
    if not dump_ok:
        pytest.skip(f"{rom} cartridge dump not present")
    if not os.path.exists(play.fixture_path(rom, target)):
        pytest.skip(f"{rom}_{target}.SaveRAM not present (build it with tools/gen1_fixtures.py)")


def _assert_inspect_gate_agrees(text: str, rom: str, target: str) -> None:
    """Lua's PARTY_RAW/PARTY_LUA/HELLO dump, cross-checked against the Python codec on the SAME
    bytes. Shared by the vanilla/clean-pure lane and the overlay lane (A4): an overlay-admitted
    cartridge decodes the identical party record, because the overlay adds ROM code and does not
    move SRAM."""
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


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("rom", ROMS)
def test_inspect_gate_and_hardware_differential(rom, target, emuhawk):
    from run_gb_gate import run_gate
    _skip_if_absent(rom, target)
    passed, path, text = run_gate(GATE, rom_key=rom, target=target, timeout=240, quiet=True)
    assert passed, f"gate FAILED on {rom}/{target}: {text[-1500:]}"
    _assert_inspect_gate_agrees(text, rom, target)


# The pureRGB companion OVERLAY (PLAN M3/P4): the clean build + the SLink UPS, admitted on its
# own sha1 (admission_overlay.json). Selected independently of ROMS/SLINK_GEN1_ROMS so a default
# full run of this file does not silently pull the overlay cartridges into the vanilla/clean-pure
# lab-route test above, which has no overlay wiring.
OVERLAY_ROMS = ("purered_overlay", "pureblue_overlay", "puregreen_overlay")


def _selected_overlay_roms() -> tuple:
    wanted = tuple(part for part in re.split(r"[,\s]+", os.environ.get("SLINK_GEN1_OVERLAY_ROMS", "")) if part)
    unknown = [rom for rom in wanted if rom not in OVERLAY_ROMS]
    if unknown:
        raise ValueError(f"unknown SLINK_GEN1_OVERLAY_ROMS entries {unknown}; known: {OVERLAY_ROMS}")
    return wanted or OVERLAY_ROMS


OVERLAY_SELECTED = _selected_overlay_roms()


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("rom", OVERLAY_SELECTED)
def test_inspect_gate_overlay_round_trip(rom, target, emuhawk):
    """A4 live: a clean pure SaveRAM loads on the overlay build unchanged. fixture_path resolves
    an overlay key to the CLEAN pure fixture (g1.fixture_path); staged_rom applies the UPS and
    sha1-verifies the result against admission_overlay.json."""
    import gen1_playthrough as play
    from run_gb_gate import run_gate
    if not os.path.exists(play.fixture_path(rom, target)):
        pytest.skip(f"{rom}_{target}.SaveRAM not present (build it with tools/gen1_fixtures.py)")
    try:
        play.staged_rom(rom)
    except Exception as exc:  # noqa: BLE001 - any staging failure just skips a live gate
        pytest.skip(f"{rom}: overlay cartridge unavailable ({exc})")
    passed, path, text = run_gate(GATE, rom_key=rom, target=target, timeout=240, quiet=True)
    assert passed, f"gate FAILED on {rom}/{target}: {text[-1500:]}"
    _assert_inspect_gate_agrees(text, rom, target)


SCRIPTED_GATE = "lua/tests/test_gen1_scripted_gate.lua"


@pytest.mark.parametrize("rom", ROMS)
def test_new_game_lab_route_emits_the_engine_sequence(rom, emuhawk, monkeypatch):
    """S-1 PHYSICAL: a cold cartridge, NEW GAME -> starter -> rival battle by buttons only, with
    the signals layer armed. The engine-site sequence must be the one pret's scripts imply."""
    import gen1_playthrough as play
    from run_gb_gate import run_gate
    if rom in PURE_ROMS and not os.path.exists(os.path.join(play.BUILD, f"gen1_{rom}.gbc")):
        pytest.skip(f"{rom} cartridge dump not present")
    monkeypatch.setenv("SLINK_SCRIPT_CHAIN", "lab")
    # Bulbasaur on the A side (the R/B lab driver's slot 8), Charmander otherwise -- the pure
    # titles take the shared R/B lab driver (their OaksLab script rows are SAME).
    monkeypatch.setenv("SLINK_SCRIPT_PLAYER", "a" if rom in ("red", "purered") else "b")
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


APEX_GATE = "lua/tests/test_gen1_apex_gate.lua"
# The four checks the APEX CHIP contract must print (lua/tests/test_gen1_apex_gate.lua:121-145).
# Both halves are asserted: a predicted key collision must restore the two DV bytes and send NO
# key_change, and a real use must send exactly one key_change{apex_chip} whose alias the server's
# ack clears.
_APEX_OK_LINES = (
    "collision: DVs restored (unchanged)",
    "apex: DVs are FFFF",
    "apex: one key_change sent",
    "apex: alias cleared by key_change_ack",
)


@pytest.mark.skipif("purered" not in ROMS,
                    reason="purered is not one of this lane's cartridges (SLINK_GEN1_ROMS)")
def test_apex_chip_contract_on_a_pure_cartridge(emuhawk):
    """T1/T3 PHYSICAL: the APEX CHIP identity contract on a real pureRGB cartridge.

    purered only: the gate needs the one-mon town fixture (a starter and an empty bag) and it
    refuses a vanilla cartridge outright (vanilla has no APEX CHIP). The release gate's
    apex-purergb lane names this test by node id and pins SLINK_GEN1_ROMS=purered, so the lane
    cannot pass by skipping: a missing dump or fixture skips with its own reason, and only the
    lane-SELECTION reason is in ALLOWED_SKIPS.
    """
    from run_gb_gate import run_gate
    _skip_if_absent("purered", "town")
    passed, path, text = run_gate(APEX_GATE, rom_key="purered", target="town", timeout=600,
                                  quiet=True)
    assert passed, f"APEX gate FAILED on purered/town: {text[-1500:]}"
    for line in _APEX_OK_LINES:
        assert f"[ok] {line}" in text, f"APEX gate did not report {line!r}:\n{text[-1500:]}"
