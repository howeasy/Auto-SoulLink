#!/usr/bin/env python3
"""The Gen 1 release gate. Fail-closed, and a skip is a failure.

WHY THIS IS NOT "RUN PYTEST". A skip reads exactly like a pass, and this generation kept
hitting that: fifteen randomized-ROM proofs disabled by a missing jar, nine duo scenarios
disabled by an unset environment variable, three more disabled by a comment that turned out
to be false. Every one of those looked green. So the rule here is that a lane which did not
RUN did not PASS — a missing ROM, emulator or UPR jar is a hard failure of the gate, not a
reason to shrug.

Order matters, cheapest-and-most-diagnostic first, because a failure early on usually
explains a failure later:

    1. unit               — the source oracles and the rules, against the decomps
    2. rom-layout         — every flat ROM offset and patch span, against the dumps
    3. lua-parse          — every client and gate file parses
    4. profile-addresses  — WRAM/SRAM symbols, against pret
    5. profile-generated  — profile.json is what the pinned .sym files generate
    6. statics-generated  — static_encounters.json is what pret's scripts/objects say
    7. fixtures           — every committed battery save qualifies as a real game state
    8. patch-build        — the clean dumps still hold what the manifest displaces
    9. live-gates         — the companion patch on real cartridges: hook, mailbox, START-menu
                            row, and the panel on a randomized+injected ROM
   10. live-new-gates     — the rewritten Gen 1 modules on all three cartridges
   11. inspect-purergb    — the same inspect gate on the three built pureRGB cartridges
   12. apex-purergb       — the APEX CHIP identity contract on the real PureRed cartridge
   13. live-trade-gates   — the SLINK TRADE receptionist on the patched cartridges
   14. duo-pairs          — every gen1_new scenario, Red (A) against Blue (B), through the real server

GIVE IT THE MACHINE. The emulator lanes are wall-clock sensitive: the duo scenarios drive
two EmuHawk instances against a real server and wait on real frame counts. Running anything
heavy alongside them does not merely slow the gate down, it FAILS it — a `deadzone` run that
finishes in 65 seconds idle has been observed timing out at its 1500-second budget with a
unit-test run competing for the same cores. That is the emulator being starved, not a
defect, but the gate cannot tell the two apart and should not pretend to.

    python tools/verify_gen1_release.py                # everything
    python tools/verify_gen1_release.py --quick        # stop before the emulator lanes
    python tools/verify_gen1_release.py --list         # show the lanes and exit
    python tools/verify_gen1_release.py --lane unit --lane lua-parse   # only these lanes
"""
from __future__ import annotations

import os
import subprocess  # noqa: F401  (re-exported: tests monkeypatch gate.subprocess.run)
import sys

import release_lanes
from release_lanes import Lane

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY = sys.executable

# Lanes that need an emulator, and therefore minutes rather than seconds.
_SLOW = {"live-gates", "live-new-gates", "inspect-purergb", "apex-purergb", "live-trade-gates",
         "duo-pairs", "inspect-purergb-overlay", "live-trade-gates-purergb", "apex-refusal-purergb",
         "duo-pairs-purergb"}

# ── Skips that are allowed, each with the reason it is allowed ──────────────────────────
# The gate's whole point is that a skip is a failure, so an exception has to be argued for
# by name. These fragments are matched against pytest's own `-rs` reason lines; anything
# NOT matched fails the lane, which is what stops a newly-disabled test reading as green.
#
# Every entry is out of Gen 1's scope, not merely inconvenient. There are deliberately no Gen 1
# INPUT entries: a Gen 1 test that skips because its cartridge, fixture or emulator is missing is
# a defect in this gate's inputs, and those reasons ("cartridge dump not present", "SaveRAM not
# present", "EmuHawk not found") stay unexcused. The one Gen 1 entry below is a lane-SELECTION
# skip: it says a test belongs to a different lane, not that an input is missing.
ALLOWED_SKIPS = [
    ("boots from a battery save",
     "the Gen 1/Gen 2 duo configs load a .SaveRAM rather than a savestate, and this test "
     "asserts the SAVESTATE table, so those rows have nothing to check"),
    ("pokecrystal not cloned",
     "Gen 2 decomp; not required for a Gen 1 release"),
    ("pokegold not cloned",
     "Gen 2 decomp; not required for a Gen 1 release"),
    ("is a partial",
     "template fragments have no <svg> root of their own, by design"),
    ("stream/memorial.html not present",
     "optional OBS overlay template"),
    ("is not one of this lane's cartridges",
     "a lane names the cartridges it runs (SLINK_GEN1_ROMS), so a test for a cartridge the lane "
     "did not select is not part of it — the lane-selection counterpart of the input skips above, "
     "which stay unexcused. Only the selection reason matches this fragment; a lane that names "
     "purered still fails if purered's dump or fixture is missing."),
]


LANES = [
    Lane("unit",
         [_PY, "-m", "pytest", "tests/unit", "-q", "-p", "no:randomly", "-rs"],
         why="the source oracles, the rules, and every table generated from the decomps"),
    Lane("rom-layout", [_PY, "tools/verify_gen1_rom_layout.py"],
         why="every flat ROM offset and companion-patch span, against the real dumps"),
    Lane("lua-parse", [_PY, "tools/lua_syntax_check.py"],
         why="every Lua file parses under the runtime the clients actually use"),
    Lane("profile-addresses", [_PY, "tools/verify_profile_addresses.py"],
         why="WRAM/SRAM symbols against pret"),
    Lane("profile-generated", [_PY, "tools/gen_gen1_profile.py", "--check"],
         why="data/games/gen1_rby/profile.json is exactly what the pinned pret .sym files "
             "generate"),
    Lane("profile-generated-purergb",
         [_PY, "tools/gen_gen1_profile.py", "--check", "--foundation", "purergb"],
         why="data/games/gen1_purergb/profile.json is exactly what the pinned pureRGB .sym files "
             "generate (the M1 pack; needs the pinned source checkout, see gen1_foundation)"),
    Lane("statics-generated", [_PY, "tools/gen_gen1_statics.py", "--check"],
         why="static_encounters.json is exactly what pret's scripts/objects say"),
    Lane("fixtures", [_PY, "tools/gen1_fixtures.py", "--qualify"],
         # The "(Yellow legacy pinned by name)" clause went when the last LEGACY entry did
         # (tools/gen1_fixtures.py:58 is now empty); the pin below keeps the two in step.
         why="every committed battery save is a real game state the codec qualifies"),
    Lane("patch-build", [_PY, "patch/gen1/tools/build.py", "--verify-only"],
         why="the clean dumps still hold what the manifest expects to displace"),
    Lane("live-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_gates.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_LIVE": "1"},
         why="the companion patch on real cartridges: VBlank hook, mailbox, START-menu row, "
             "and the panel on a randomized+injected ROM"),
    Lane("live-new-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_new_gates.py", "-q", "-p",
          "no:randomly", "-rs"],
         # The vanilla three, named: the module also carries the pureRGB cases now, and this lane's
         # coverage must not grow by accident (inspect-purergb is the lane for those).
         env={"SLINK_LIVE": "1", "SLINK_GEN1_ROMS": " ".join(("red", "blue", "yellow"))},
         why="the rewritten Gen 1 modules on all three cartridges: pinned engine sites "
             "present, hooks armed, live party decoded identically in Lua and Python, "
             "overworld write checkpoint reached (docs/gen1_requirements.md R-1, S, W-7, "
             "F-6)"),
    Lane("inspect-purergb",
         [_PY, "-m", "pytest", "tests/live/test_gen1_new_gates.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_LIVE": "1", "SLINK_GEN1_ROMS": " ".join(("purered", "pureblue", "puregreen"))},
         why="the rewritten client on the three built pureRGB cartridges: pinned engine sites "
             "present, hooks armed, live party decoded identically in Lua and Python, overworld "
             "write checkpoint reached -- skip = lane failure, so the staged .gbc files and the "
             "per-title fixtures have to be in the tree"),
    Lane("apex-purergb",
         [_PY, "-m", "pytest",
          "tests/live/test_gen1_new_gates.py::test_apex_chip_contract_on_a_pure_cartridge",
          "-q", "-p", "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1", "SLINK_GEN1_ROMS": "purered"},
         why="the APEX CHIP identity contract on the real PureRed cartridge (PLAN T1/T3): a "
             "predicted key collision restores the two DV bytes and sends no key_change, a real "
             "use sends one key_change{apex_chip} whose alias the ack clears. Selected by node "
             "id, so nothing is collected-then-deselected; skip = lane failure, so the staged "
             ".gbc and purered_town.SaveRAM have to be in the tree"),
    Lane("live-trade-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_trade_gates.py", "-q", "-p",
          "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1"},
         why="the SLINK TRADE receptionist on the patched Red/Blue cartridges AND the pureRGB "
             "companion overlay: menu, offer, refusal and acceptance texts, every client line "
             "schema-valid (docs/gen1_requirements.md T-1, T-2; PLAN M3 for the overlay case)"),
    Lane("inspect-purergb-overlay",
         [_PY, "-m", "pytest",
          "tests/live/test_gen1_new_gates.py::test_inspect_gate_overlay_round_trip",
          "-q", "-p", "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1"},
         why="A4 live: the three pureRGB companion-overlay cartridges (patch/dist/SLink-Pure*.ups "
             "applied to the sha1-verified clean build) boot the CLEAN pure town/battle fixtures "
             "unchanged, decode identically in Lua and Python -- the overlay adds ROM code, it "
             "does not move SRAM. Selected by node id (parametrised over the three titles x two "
             "targets), so nothing is collected-then-deselected; skip = lane failure, so the UPS "
             "artifacts, the clean pure builds and the pure fixtures have to be in the tree"),
    Lane("live-trade-gates-purergb",
         [_PY, "-m", "pytest",
          "tests/live/test_gen1_trade_gates.py::test_receptionist_query_offer_and_native_notices"
          "[purered_overlay-purered-None]",
          "-q", "-p", "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1"},
         why="the SLINK TRADE receptionist on the pureRGB companion-overlay PureRed cartridge "
             "(PLAN M3 P4): trade_query within the ABI window, the native SLINK TRADE/CABLE "
             "CLUB/CANCEL menu, offer/refusal/acceptance notices, CABLE CLUB falling through to "
             "vanilla pureRGB text, every client line schema-valid. Selected by the exact "
             "parametrized node id -- red/blue stay live-trade-gates' job"),
    Lane("apex-refusal-purergb",
         [_PY, "tools/run_gb_gate.py", "lua/tests/test_gen1_apex_refusal_gate.lua",
          "--rom", "purered_overlay", "--target", "town", "--timeout", "600"],
         why="the M3 overlay's ROM-level APEX CHIP collision guard (SlinkApexGuard, retargeted "
             "onto ItemUseMedicine.setDVs): a cross-mon same-species/same-OT DVs-$FFFF collision "
             "refuses BEFORE the DV store (pureRGB's own .alreadyUsedApex text, chip not "
             "consumed, DVs unchanged, no key_change sent), then the same chip on the same slot "
             "goes through normally once the collision is removed. Not a pytest lane -- "
             "run_gb_gate.py itself fails closed (raises on a missing ROM/fixture, exit 1 on a "
             "FAIL result), so a missing artifact cannot read as green here either"),
    Lane("duo-pairs",
         [_PY, "-m", "pytest", "tests/e2e/test_duo_gen1_new.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_E2E": "1", "SLINK_LIVE": "1"},
         why="the rewritten client on two real cartridges through the real server: encounter "
             "link, dead zone, in-game SLINK trade (docs/gen1_requirements.md D-1, D-3, T-3, T-4)"),
    Lane("duo-pairs-purergb",
         [_PY, "-m", "pytest", "tests/e2e/test_duo_gen1_pure.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_E2E": "1", "SLINK_LIVE": "1"},
         why="the same scenarios on the pureRGB foundation (docs/purergb/PLAN.md §13 P3b/P4/P5): "
             "PureRed vs PureBlue on the clean builds (rules, PC/save, reconnect, whiteout, poison, "
             "rival swap, randomized admission on the fork jar), the companion overlay pairing "
             "(native trade YES/NO, Explode Mode) and PureRed vs PureGreen; a deferred scenario is "
             "not collected, so every skip here is a missing artifact"),
]


# What each lane is the evidence for, printed by --list. Requirement ids are the ones
# docs/gen1_requirements.md carries; the parenthesised entries are lanes whose tests predate
# the rewrite and are replaced later in the plan, so they certify nothing today.
REQUIREMENTS = {
    "unit": ["F-1", "F-2", "F-4", "F-5", "R-1", "R-2", "C-0", "C-4", "W-7"],
    "rom-layout": ["F-2"],
    "lua-parse": ["C-4"],
    "profile-addresses": ["F-1"],
    "profile-generated": ["F-1"],
    "profile-generated-purergb": ["F-1"],
    "statics-generated": ["F-5", "S-8"],
    "fixtures": ["F-6"],
    "patch-build": ["T-1"],
    "live-gates": ["T-1 prerequisites (panel, menu row, randomized+injected panel)"],
    "live-new-gates": ["R-1", "S", "W-7", "F-6"],
    "inspect-purergb": ["R-1", "S", "W-7", "F-6"],
    "apex-purergb": ["T1", "T3"],
    "live-trade-gates": ["T-1", "T-2"],
    "inspect-purergb-overlay": ["R-1", "S", "W-7", "F-6", "A4 (PLAN M3)"],
    "live-trade-gates-purergb": ["T-1", "T-2", "PLAN M3"],
    "apex-refusal-purergb": ["U6 (PLAN M3, ROM-level guard)"],
    "duo-pairs": ["D-1", "D-3", "T-3", "T-4"],
    "duo-pairs-purergb": ["D-1", "D-3", "T-3", "T-4", "C-5", "PLAN M3/M5"],
}


def run_lane(lane: Lane, quiet: bool) -> tuple[bool, str]:
    """Gen 1's ALLOWED_SKIPS bound in; the mechanism itself lives in release_lanes."""
    return release_lanes.run_lane(lane, quiet, ALLOWED_SKIPS)


def main() -> int:
    return release_lanes.run_gate(
        title="Gen 1 release gate",
        lanes=LANES,
        requirements=REQUIREMENTS,
        slow=_SLOW,
        run_lane=run_lane,
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())
