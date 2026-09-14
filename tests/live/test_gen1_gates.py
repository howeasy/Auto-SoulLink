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
from run_gb_gate import run_gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 1 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

# gate script -> which fixture it needs. Both currently want an encounter-free save; a gate
# that needs a wild battle would ask for "battle" instead.
GATES = {
    # test_gen1_memory_gate / test_gen1_writes_gate drove the PRE-REWRITE client against the
    # old harness-written fixtures ("starting from a healthy mon"); on the real fixtures built
    # from scripted play they fail on their own assumptions. Their rows are proven by the
    # rewrite's lanes instead: R-1 (inspect gate, live-new-gates), W-1/D-9 (duo-pairs).
    # Retired here rather than in Phase 8 so the release runner stays fail-closed and honest.
    # The withdraw half of party sync.
    "lua/tests/test_gen1_boxroundtrip_gate.lua": "town",
    # The stat formula behind the withdraw rebuild, checked against the GAME's own numbers:
    # every party mon carries both the inputs and the answer, so recomputing and comparing
    # is a real control rather than a self-consistency check.
    "lua/tests/test_gen1_stat_rebuild.lua": "town",
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
    from run_gb_gate import PATCHED
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


@pytest.mark.parametrize("rom", PATCH_ROMS)
def test_gen1_menu_row(rom, emuhawk):
    """The SLINK row the companion patch appends to the START menu.

    Separate from the companion-patch gate because it tests a different thing: that gate
    covers the VBlank hook and its mailbox, this one covers a structural edit to a menu the
    player uses constantly. The row is INERT in this increment -- selecting it falls through
    to CloseStartMenu exactly as EXIT does -- so what is under test is that it draws inside
    a resized box, that the cursor can reach it, and that no existing menu index moved.
    """
    from run_gb_gate import PATCHED
    base_key, rom_rel, _ = PATCHED[rom]
    if not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python patch/gen1/tools/build.py`")
    if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_town.SaveRAM")):
        pytest.skip("missing fixture — `python tools/gen1_playthrough.py`")

    passed, result_path, text = run_gate("lua/tests/test_gen1_menu_row_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"START-menu row gate on {rom} did not PASS\n"
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
    from run_gb_gate import PATCHED
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


def test_gen1_panel_on_a_randomized_cartridge(emuhawk):
    """THE structural injector's only real question, answered on hardware.

    build.py is gated on the two pinned clean SHA-1s, which is right for a build tool and
    useless for a randomized ROM: every seed is a different file, so there is no hash to
    check and a UPS -- which embeds its source's CRC32 -- cannot apply at all. The injector
    therefore verifies STRUCTURE: every span holds the bytes the manifest expects, the hook
    site is untouched, bank $3F is empty, the header is protected.

    That reasoning is only as good as the cartridge it produces, and the failure it would
    hide is one no byte comparison can see: a ROM that patches "successfully" and then does
    not boot. So this randomizes Red for real, injects, and runs the whole panel gate --
    row, open, staging, page turn, close, walk away -- on the result.

    The artifact is rebuilt rather than committed, because a randomized ROM is a ROM.
    """
    import subprocess

    from run_gb_gate import PATCHED
    _base, rom_rel, _sav = PATCHED["red_rand_patched"]
    rom_path = os.path.join(REPO, rom_rel)

    if not os.path.exists(rom_path):
        proc = subprocess.run([sys.executable,
                               os.path.join(REPO, "tools", "make_randomized_patched.py")],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(rom_path):
            pytest.skip(f"could not build a randomized+patched ROM: "
                        f"{(proc.stderr or '').strip()[-200:]}")

    passed, result_path, text = run_gate("lua/tests/test_gen1_menu_row_gate.lua",
                                         rom_key="red_rand_patched", target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"the panel gate failed on a randomized+injected cartridge\n"
                    f"result: {result_path}\n{text[-3000:]}")
