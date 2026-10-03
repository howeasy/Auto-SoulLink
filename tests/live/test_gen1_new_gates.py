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
# The SLink companion is REQUIRED for Red/Blue/pureRGB (owner 2026-10-02): the gate harness
# refuses a clean Red/Blue/pureRGB cartridge, so these cases boot the companion builds -- the
# vanilla patch (red_patched/blue_patched, slink_*.gb) and the pureRGB overlays (the pinned clean
# build + patch/dist/SLink-Pure*.ups). Yellow has no companion and runs clean. Every key seeds the
# CLEAN title's fixture (run_gb_gate.PATCHED base; the companion moves no SRAM, A4).
VANILLA_ROMS = ("red_patched", "blue_patched", "yellow")
PURE_ROMS = ("purered_overlay", "pureblue_overlay", "puregreen_overlay")
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


def _red_blue_params() -> list:
    """A Red/Blue-only gate stays collected on every lane (an empty parametrize is an unexplained
    skip to the release runner) and skips with the lane-selection reason where the lane did not
    name that cartridge. A skipif MARK, not pytest.skip() from a helper: the runner wants one
    SKIPPED line per skip and pytest folds same-location/same-reason skips into one line."""
    return [pytest.param(rom, marks=pytest.mark.skipif(
                rom not in ROMS,
                reason=f"{rom} is not one of this lane's cartridges (SLINK_GEN1_ROMS)"))
            for rom in ("red_patched", "blue_patched")]


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


def _base(rom: str) -> str:
    """The clean title a key's cartridge and fixture derive from: red_patched -> red,
    purered_overlay -> purered, yellow -> yellow."""
    from run_gb_gate import PATCHED
    return PATCHED[rom][0] if rom in PATCHED else rom


def _skip_if_dump_absent(rom: str) -> None:
    """Skip when the cartridge is not in the tree; FAIL when it is there but wrong.

    The companion builds resolve exactly as run_gb_gate launches them: a vanilla build is the file
    patch/gen1/tools/build.py writes, an overlay is staged by g1.staged_rom (the UPS applied to the
    sha1-pinned clean build, the result sha1-checked against admission_overlay.json). Only a
    FileNotFoundError is absence; a sha1 mismatch raises ValueError and fails the case. In a
    release lane a skip is a lane failure anyway -- the lane's inputs have to be there.
    """
    import gen1_playthrough as play
    from run_gb_gate import PATCHED
    if rom in PATCHED:
        rom_rel = PATCHED[rom][1]
        if rom_rel is not None:
            if not os.path.exists(os.path.join(REPO, rom_rel)):
                pytest.skip(f"{rom} cartridge dump not present ({rom_rel}; "
                            "`python patch/gen1/tools/build.py`)")
            return
        try:
            play.staged_rom(rom)
        except FileNotFoundError as exc:
            pytest.skip(f"{rom} cartridge dump not present ({exc})")
        return
    ext = "gbc" if rom == "yellow" else "gb"
    if not (os.path.exists(os.path.join(REPO, play.ROMS[rom]))
            or os.path.exists(os.path.join(play.BUILD, f"gen1_{rom}.{ext}"))):
        pytest.skip(f"{rom} cartridge dump not present")


def _skip_if_absent(rom: str, target: str) -> None:
    """Skip when this cartridge or its battery save is not in the tree.

    Both facts are checked because the inspect gate boots a fixture, and the fixture is the CLEAN
    title's (`_base`): a companion build can be present with no SaveRAM built yet
    (tools/gen1_fixtures.py builds those per title).
    """
    import gen1_playthrough as play
    _skip_if_dump_absent(rom)
    base = _base(rom)
    if not os.path.exists(play.fixture_path(base, target)):
        pytest.skip(f"{base}_{target}.SaveRAM not present (build it with tools/gen1_fixtures.py)")


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


# (The separate overlay round-trip test is gone: with the overlays in ROMS, the case above IS the
# A4 round trip -- a clean pure SaveRAM booted on the overlay build, decoded identically.)


SCRIPTED_GATE = "lua/tests/test_gen1_scripted_gate.lua"


@pytest.mark.parametrize("rom", ROMS)
def test_new_game_lab_route_emits_the_engine_sequence(rom, emuhawk, monkeypatch):
    """S-1 PHYSICAL: a cold cartridge, NEW GAME -> starter -> rival battle by buttons only, with
    the signals layer armed. The engine-site sequence must be the one pret's scripts imply.
    `{rom}_cold` is the same cartridge with no save (red_patched_cold, purered_overlay_cold, ...)."""
    from run_gb_gate import run_gate
    _skip_if_dump_absent(rom)
    monkeypatch.setenv("SLINK_SCRIPT_CHAIN", "lab")
    # Bulbasaur on the A side (the R/B lab driver's slot 8), Charmander otherwise -- the pure
    # titles take the shared R/B lab driver (their OaksLab script rows are SAME).
    monkeypatch.setenv("SLINK_SCRIPT_PLAYER", "a" if _base(rom) in ("red", "purered") else "b")
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


APEX_ROM = "purered_overlay"


@pytest.mark.skipif(APEX_ROM not in ROMS,
                    reason=f"{APEX_ROM} is not one of this lane's cartridges (SLINK_GEN1_ROMS)")
def test_apex_chip_contract_on_a_pure_cartridge(emuhawk):
    """T1/T3 PHYSICAL: the APEX CHIP identity contract on a real pureRGB cartridge.

    PureRed's companion overlay only (the clean build is refused): the gate needs the one-mon
    town fixture (a starter and an empty bag) and it refuses a vanilla cartridge outright (vanilla
    has no APEX CHIP). The release gate's apex-purergb lane names this test by node id and pins
    SLINK_GEN1_ROMS=purered_overlay, so the lane cannot pass by skipping: a missing dump or
    fixture skips with its own reason, and only the lane-SELECTION reason is in ALLOWED_SKIPS.
    """
    from run_gb_gate import run_gate
    _skip_if_absent(APEX_ROM, "town")
    passed, path, text = run_gate(APEX_GATE, rom_key=APEX_ROM, target="town", timeout=600,
                                  quiet=True)
    assert passed, f"APEX gate FAILED on {APEX_ROM}/town: {text[-1500:]}"
    for line in _APEX_OK_LINES:
        assert f"[ok] {line}" in text, f"APEX gate did not report {line!r}:\n{text[-1500:]}"


# Red and Blue only: on Yellow the starter is Pikachu, whose only damaging move (Thundershock)
# is super-effective against Route 1's Pidgey and KOs it on the hunt's weakening turn before
# the throw (three straight runs, 2026-09-20: 'unexpected no_catch (foe KO)'). A driver limit
# of the shared hunt module, not the client: the Yellow client code path is identical.
# Red/Blue only (master 64d9663/9a41d78): the gate's NAMING table carries the vanilla
# DisplayNamingScreen anchors and Yellow's starter KOs the hunt's Pidgey. A pureRGB twin needs the
# pure anchors + the lane facts in lua/tests/test_gen1_slow_name_gate.lua (recorded follow-up,
# docs/purergb/CHANGELOG.md §7); the acquisition-without-a-frame-budget path it proves is shared
# client code, exercised on the pure pairings by every capture scenario.
@pytest.mark.parametrize("rom", _red_blue_params())
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


EVOLUTION_GATE = "lua/tests/test_gen1_evolution_gate.lua"
# Red/Blue only: the forest walker decodes pret/pokered's maps; Yellow's forest differs


@pytest.mark.parametrize("rom", _red_blue_params())
def test_level_up_evolution_emits_one_key_change_from_the_after_battle_path(rom, emuhawk):
    """FIX-EVO PHYSICAL: a Caterpie/Weedle caught in Viridian Forest grows to level 7 in a wild
    battle and EndOfBattle evolves it (predef EvolutionAfterBattle, never TryEvolvingMon); the
    production client reports exactly one key_change reason=evolution with the DV:OT prefix
    kept, and no second capture. The catch's experience is staged by the gate (its header)."""
    from run_gb_gate import run_gate
    passed, path, text = run_gate(EVOLUTION_GATE, rom_key=rom, target="battle", timeout=1800, quiet=True)
    assert passed, f"evolution gate FAILED on {rom}; receipt {path}: {text[-2500:]}"
    tx = [json.loads(line[3:]) for line in text.splitlines() if line.startswith("TX ")]
    captures = [m for m in tx if m.get("event") == "capture"]
    changes = [m for m in tx if m.get("event") == "key_change"]
    assert len(captures) == 1 and len(changes) == 1
    kc = changes[0]
    from tests.unit import protocol_schema as ps
    assert ps.validate_event(kc) == [] and ps.validate_event(captures[0]) == []
    assert kc["reason"] == "evolution"
    assert kc["old_key"] == captures[0]["key"] and kc["old_key"][:10] == kc["new_key"][:10]
    assert codec.internal_to_natdex(kc["new_species"]) in (11, 14)           # Metapod / Kakuna
    assert codec.internal_to_natdex(captures[0]["species_id"]) in (10, 13)   # Caterpie / Weedle
    receipt = re.search(
        r"^EVOLUTION_RECEIPT variant=levelup catch_frame=(\d+) levelup_frame=(\d+) evolve_signal_frame=(\d+) "
        r"key_change_frame=(\d+) after_battle_hits=(\d+) try_hits=0 cancelled_hits=0 old=(\S+) new=(\S+) "
        r"species=([0-9A-F]{2}) dex=(11|14) level=7 nick=\S+ encounters=\d+$", text, re.M)
    assert receipt, "missing evolution receipt"
    catch_f, level_f, evolve_f, change_f = map(int, receipt.groups()[:4])
    assert catch_f < level_f <= evolve_f <= change_f and int(receipt[5]) >= 1
    assert receipt[6] == kc["old_key"] and receipt[7] == kc["new_key"]
    # an un-nicknamed catch is renamed to the evolved species by RenameEvolvedMon
    assert kc["new_nickname"] in ("METAPOD", "KAKUNA")
    assert not re.search(r"^HOOK TryEvolvingMon@", text, re.M)
    assert re.search(r"^SIGNAL evolve@\d+ pc=(6ED5|6F86) which=\d+$", text, re.M)

