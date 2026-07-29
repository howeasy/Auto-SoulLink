"""The Gen 1 headless gates, as pytest.

    SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q
    SLINK_LIVE=1 pytest tests/live -q -k memory

Gen 1 had unit tests and a Lua client but had never executed against a running cartridge.
That gap hid real bugs that no static check could reach — a deferred-command queue that
crashed on first use (valid Lua, so the syntax gate passed), a box level read from an
offset past the end of the box struct, PP reported without its PP-Up mask. These gates
close it.

DIFFERENT FROM tests/live/test_lua_gates.py (Gen 3), which loads a version-locked
`slink_*.State` and therefore needs tools/mkstates.py to rebuild states after every BizHawk
upgrade. Gen 1 boots from `tests/fixtures/gen1/*.SaveRAM` — battery saves are plain SRAM,
never version-locked — so nothing here goes stale. Booting to CONTINUE costs ~640 frames.

Each gate is skipped, never hung, when a prerequisite is missing: no EmuHawk, no cartridge
dump (they are gitignored), or no fixture.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as play  # noqa: E402
from run_gen1_gate import run_gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 1 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

# gate script -> which fixture it needs. Both currently want an encounter-free save; a gate
# that needs a wild battle would ask for "battle" instead.
GATES = {
    "lua/tests/test_gen1_memory_gate.lua": "town",
    "lua/tests/test_gen1_writes_gate.lua": "town",
    # The withdraw half of party sync. test_gen1_writes_gate only deposits.
    "lua/tests/test_gen1_boxroundtrip_gate.lua": "town",
    # Evolution: a Gen 1 key is DVs:OTID:SPECIES, so evolving rewrites it. Drives a real
    # Moon Stone through the real bag menus — no battle, no encounter RNG, and
    # uncancellable (wForceEvolution). Needs the town save, not the battle one:
    # ItemUseEvoStone refuses outright while wIsInBattle is set.
    "lua/tests/test_gen1_evolution_gate.lua": "town",
}
ROMS = ("red", "blue", "yellow")

# The companion-patch spike, which only exists for Red and Blue — Yellow has no free WRAM
# for a mailbox (pret's map: WRAM0 TOTAL EMPTY $0000).
PATCH_ROMS = ("red_patched", "blue_patched")


@pytest.fixture(scope="session")
def emuhawk():
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


@pytest.mark.parametrize("gate", sorted(GATES))
@pytest.mark.parametrize("rom", ROMS)
def test_gen1_gate(gate, rom, emuhawk):
    """Run one gate against one ROM.

    Parametrised over all three cartridges on purpose: Yellow shifts nearly every WRAM
    address by -1, so a Red-only run would not exercise the profile that is most likely to
    be wrong.
    """
    if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
        pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
    target = GATES[gate]
    fixture = os.path.join(play.FIXTURES, f"{rom}_{target}.SaveRAM")
    if not os.path.exists(fixture):
        pytest.skip(f"missing fixture — build with "
                    f"`python tools/gen1_playthrough.py --rom {rom} --target {target}`")

    passed, result_path, text = run_gate(gate, rom_key=rom, target=target,
                                         timeout=300, quiet=True)
    assert passed, (f"{os.path.basename(gate)} on {rom}/{target} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


@pytest.mark.parametrize("rom", PATCH_ROMS)
def test_gen1_companion_patch(rom, emuhawk):
    """The companion-patch spike: is the injected code reached, every frame, everywhere?

    Asserts the 'SLNK' beacon, a frame counter that advances in the overworld AND in battle
    AND with a menu open (VBlank is an interrupt, which is why that hook site was chosen),
    that the displaced TrackPlayTime still runs, and that the game still plays.
    """
    from run_gen1_gate import PATCHED
    base_key, rom_rel, _ = PATCHED[rom]
    if not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python patch/gen1/tools/build.py`")
    if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_town.SaveRAM")):
        pytest.skip("missing fixture — `python tools/gen1_playthrough.py`")

    passed, result_path, text = run_gate("lua/tests/test_gen1_patch_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"companion patch gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


# The Archipelago builds and their negative control. `red_cold`/`blue_cold` run the SAME
# gate on the VANILLA cartridge, where every AP assertion has to come out the other way —
# without that pair, a detection function stuck at "yes" would pass on its own.
AP_ROMS = ("red_ap", "blue_ap", "red_cold", "blue_cold")


@pytest.mark.parametrize("rom", AP_ROMS)
def test_gen1_archipelago(rom, emuhawk):
    """Does SLink read an Archipelago cartridge, and only when it is one?

    Needs no fixture: the fork's save block is 4 bytes longer than vanilla's
    (sMainDataCheckSum 0xB523 -> 0xB527), so no committed .SaveRAM is loadable by it and the
    gate asserts against the ROM and the intro instead. See the gate's own header.
    """
    from run_gen1_gate import PATCHED
    _, rom_rel, _ = PATCHED[rom]
    if rom_rel is None:                       # the vanilla control: needs only the dump
        base = play.ROMS[rom.rsplit("_", 1)[0]]
        if not os.path.exists(os.path.join(REPO, base)):
            pytest.skip(f"{base} not present (ROMs are gitignored)")
    elif not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python tools/gen1_ap_rom.py` "
                    f"(needs a Pokemon RB apworld and the vanilla dump)")

    passed, result_path, text = run_gate("lua/tests/test_gen1_ap_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"Archipelago gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")
