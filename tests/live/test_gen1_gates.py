"""The Gen 1 headless gates, as pytest.

    SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q
    SLINK_LIVE=1 pytest tests/live -q -k menu_row

Gen 1 had unit tests and a Lua client but had never executed against a running cartridge.
That gap hid real bugs that no static check could reach — a deferred-command queue that
crashed on first use (valid Lua, so the syntax gate passed), a box level read from an
offset past the end of the box struct, PP reported without its PP-Up mask. These gates
close it.

DIFFERENT FROM tests/live/test_lua_gates.py (Gen 3), which loads a version-locked
`slink_*.State` and therefore needs tools/mkstates.py to rebuild states after every BizHawk
upgrade. Gen 1 boots from `tests/fixtures/gen1/*.SaveRAM` — battery saves are plain SRAM,
never version-locked — so nothing here goes stale. Booting to CONTINUE costs ~640 frames.

What is left here is the companion-patch half: the VBlank hook and mailbox, the START-menu
SLINK row and the panel behind it, and that same panel gate on a randomized+injected ROM. The
pre-rewrite cartridge gates (memory, writes, box round trip, stat rebuild, evolution) and the
Archipelago gate were retired with their Lua in Phase 8; the rewrite's own lanes — R-1
(tests/live/test_gen1_new_gates.py), T-1/T-2 (test_gen1_trade_gates.py) and the duo pairs —
carry those rows now.

Each gate is skipped, never hung, when a prerequisite is missing: no EmuHawk, no cartridge
dump (they are gitignored), or no fixture.

SLINK_GEN1_CAPTURE_RECEIPTS=1 makes test_gen1_sfx_matrix stamp a fresh, provenance-headed copy of its result over
the committed tests/fixtures/gen1/receipts/test_gen1_sfx_gate_*_result.txt (GEN1-GATE-REWRITES-RECEIPTS,
post-RC). Without it, an ordinary `SLINK_LIVE=1` run never touches those files, so a ROM/route change under
review can be gated without clobbering the committed receipts' `# lane HEAD=.../# cmd:` header.
"""
import datetime
import os
import subprocess
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

# The companion-patch spike, which only exists for Red and Blue — Yellow has no free WRAM
# for a mailbox (pret's map: WRAM0 TOTAL EMPTY $0000). purered_overlay is the M3 companion
# OVERLAY (PLAN P4): the same two gates, run against the pureRGB cartridge instead of the
# vanilla one, reusing the clean purered_town fixture (A4).
PATCH_ROMS = ("red_patched", "blue_patched")
OVERLAY_ROMS = ("purered_overlay",)
GATE_ROMS = PATCH_ROMS + OVERLAY_ROMS


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def receipt_header(cmd):
    """`# lane HEAD=<sha> git-status=clean|dirty at=<iso>` + `# cmd: <cmd>`: the provenance header the committed
    tests/fixtures/gen1/receipts/*_result.txt copies carry (GEN1-GATE-REWRITES-RECEIPTS, post-RC)."""
    head = _git("rev-parse", "HEAD")
    status = "clean" if not _git("status", "--porcelain") else "dirty"
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    return f"# lane HEAD={head} git-status={status} at={stamp}\n# cmd: {cmd}\n"


def capture_receipt(kept, cmd, text):
    """Stamp and write a fresh committed receipt copy. A live-gates lane run must never do this on its own — an
    ordinary run's `text` carries no provenance header, and would silently drop the committed one (the same trap
    as the Gen 2 attestation, 44f6fb97/SLINK_GEN2_NO_ATTEST). Capture is a separate, explicit opt-in step."""
    with open(kept, "w", encoding="utf-8") as f:
        f.write(receipt_header(cmd) + text)


@pytest.fixture(scope="session")
def emuhawk():
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


def _skip_unless_ready(rom):
    """Skip with a reason unless `rom`'s fixture and cartridge are both ready to launch.

    An overlay key has no fixed build path (`rom_rel is None`): its cartridge is staged on
    demand by g1.staged_rom, which applies the UPS to the clean build and sha1-verifies the
    result (tools/gen1_playthrough.purergb_overlay_dump, PLAN M3 A4) rather than failing a
    plain os.path.exists on a path that was never going to exist.
    """
    from run_gb_gate import PATCHED
    base_key, rom_rel, _ = PATCHED[rom]
    if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_town.SaveRAM")):
        pytest.skip("missing fixture — `python tools/gen1_fixtures.py`")
    if rom_rel is not None:
        if not os.path.exists(os.path.join(REPO, rom_rel)):
            pytest.skip(f"{rom_rel} not built — `python patch/gen1/tools/build.py`")
        return
    try:
        play.staged_rom(rom)
    except Exception as exc:  # noqa: BLE001 - any staging failure just skips a live gate
        pytest.skip(f"{rom}: overlay cartridge unavailable ({exc})")


@pytest.mark.parametrize("rom", GATE_ROMS)
def test_gen1_companion_patch(rom, emuhawk):
    """The companion-patch spike: is the injected code reached, every frame, everywhere?

    Asserts the 'SLNK' beacon, a frame counter that advances in the overworld AND with a menu
    open (VBlank is an interrupt, which is why that hook site was chosen), that the displaced
    TrackPlayTime still runs, that the capability bits and the ABI byte say what this build
    really ships, and that the game still plays.

    The in-battle half of the VBlank claim is NOT here: proving it used to mean writing
    wIsInBattle, and a faked battle is not a battle. It is the A3 scenario's
    PANEL_COUNTER_IN_BATTLE marker, taken inside a real wild encounter, instead.
    """
    _skip_unless_ready(rom)

    passed, result_path, text = run_gate("lua/tests/test_gen1_patch_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"companion patch gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


@pytest.mark.parametrize("rom", PATCH_ROMS)
@pytest.mark.parametrize("target", ("town", "battle"))
def test_gen1_sfx_matrix(rom, target, emuhawk):
    """The native-sound state matrix (lua/tests/test_gen1_sfx_gate.lua): the cases the ABI-2
    VBlank build got wrong, each asserting the exact id that lands on CHAN5.

    town fixture (Oak's Lab, audio bank $1F): the shipped client's play_sound path; a second
    request held while the first still owns CHAN5; the START menu (the Joypad site, since a
    menu loop never reaches DelayFrame); the lab-door fade with its $1F -> $02 bank change.
    battle fixture (Route 1 grass): a real wild battle in bank $08 (LEVEL_UP / TINK rows),
    RUN, and a request held through the battle-end fade that plays in $02 as GET_ITEM_2 --
    the id it would not have been in $08. Overlay cartridges join once their overlay carries
    the service.
    """
    _skip_unless_ready(rom)
    if target == "battle":
        from run_gb_gate import PATCHED
        base_key = PATCHED[rom][0]
        if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_battle.SaveRAM")):
            pytest.skip("missing battle fixture -- `python tools/gen1_fixtures.py <rom> battle`")
    passed, result_path, text = run_gate("lua/tests/test_gen1_sfx_gate.lua",
                                         rom_key=rom, target=target,
                                         timeout=600, quiet=True)
    # GEN1-GATE-REWRITES-RECEIPTS (post-RC): run_gate already left the plain result under patch/build
    # (result_path); the committed tests/fixtures/gen1/receipts/*_result.txt copy carries its own provenance
    # header and must not be silently overwritten by an ordinary lane run. Capturing a fresh receipt is a
    # separate, explicit step.
    if os.environ.get("SLINK_GEN1_CAPTURE_RECEIPTS") == "1":
        kept = os.path.join(REPO, "tests", "fixtures", "gen1", "receipts",
                            f"test_gen1_sfx_gate_{rom}_{target}_result.txt")
        cmd = f"tools/run_gb_gate.py lua/tests/test_gen1_sfx_gate.lua --rom {rom} --target {target} --timeout 600"
        capture_receipt(kept, cmd, text)
    assert passed, (f"SFX matrix gate on {rom}/{target} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


@pytest.mark.parametrize("rom", GATE_ROMS)
def test_gen1_menu_row(rom, emuhawk):
    """The SLINK row the companion patch appends to the START menu, and the panel behind it.

    Separate from the companion-patch gate because it tests a different thing: that gate
    covers the VBlank hook and its mailbox, this one covers a structural edit to a menu the
    player uses constantly plus the full open/stage/page/close handshake.

    The gate drives the REWRITTEN client (lua/gen1/panel.lua through lua/gen1/client.lua):
    rows arrive as a real `link_panel` reply and the client decides whether it may paint, so
    what is under test is the shipped module and not a stand-in for it.
    """
    _skip_unless_ready(rom)

    passed, result_path, text = run_gate("lua/tests/test_gen1_menu_row_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"START-menu row gate on {rom} did not PASS\n"
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
