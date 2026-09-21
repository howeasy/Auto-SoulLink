#!/usr/bin/env python3
"""The Gen 3 release gate. Same fail-closed core as verify_gen1_release.py (release_lanes.py):
a lane which did not RUN did not PASS, and a skip is a failure unless ALLOWED_SKIPS excuses it.

This is a P2 skeleton (docs/gen3/PLAN.md §6 P2 / §5.5): the cheap SOURCE-facts lanes run today,
the emulator lanes are placeholders that the P1/P3+ cards fill in. A placeholder lane whose
script does not exist yet still fails closed -- it is not skipped, `python <missing>.py` exits
nonzero on its own.

    python tools/verify_gen3_release.py                # everything
    python tools/verify_gen3_release.py --quick        # stop before the emulator lanes
    python tools/verify_gen3_release.py --list         # show the lanes and exit
"""
from __future__ import annotations

import os
import pathlib
import subprocess  # noqa: F401  (re-exported for symmetry with verify_gen1_release.py)
import sys

import release_lanes
from release_lanes import Lane

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY = sys.executable

# Lanes that need an emulator.
_SLOW = {"probe-gates", "duo-pairs-gen3"}

# The lane-selection counterpart of Gen 1's ALLOWED_SKIPS -- no input-missing excuses here
# either: a missing ROM, fixture or generated artifact is a hard failure of this gate.
ALLOWED_SKIPS = [
    ("is not one of this lane's cartridges",
     "a lane names the cartridges/pack it runs, so a test for one the lane did not select is "
     "not part of it -- the lane-selection counterpart of input-missing skips, which stay "
     "unexcused here, same as Gen 1's"),
]

_UNIT_FILES = [
    *pathlib.Path("tests/unit").glob("test_gen3_*.py"),
    pathlib.Path("tests/unit/test_protocol_conformance.py"),
    pathlib.Path("tests/unit/test_e2e_duo_wire_log.py"),
    pathlib.Path("tests/unit/test_verify_gen3_release_lanes.py"),
]

LANES = [
    # Select by FILE, never by -k: the fail-closed core counts every deselected test as
    # "did not run", so a -k selector can never produce a passing lane.
    Lane("unit",
         [_PY, "-m", "pytest", "-q", "-p", "no:randomly", "-rs",
          *sorted(str(x).replace("\\", "/") for x in _UNIT_FILES)],
         why="the Gen 3 source oracles, protocol conformance, and the pin inventory"),
    Lane("lua-parse", [_PY, "tools/lua_syntax_check.py"],
         why="every Lua file parses under the runtime the clients actually use"),
    Lane("pins", [_PY, "tools/gen3_pins.py", "--json"],
         why="the BizHawk/ROM/companion-patch hash inventory runs and emits its pins"),
    Lane("profile-generated", [_PY, "tools/gen_gen3_profile.py", "--check"],
         why="data/games/gen3_frlg/profile.json and gen3_rr/profile.json are exactly what the "
             "pinned pret .sym files generate -- not yet written (P2 C2-2); the lane fails "
             "closed, not skips, until it lands"),
    Lane("probe-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen3_probe_gates.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_LIVE": "1"},
         why="P1's exec/write hook probe matrix on real ROM dumps -- not yet written; fails "
             "closed until the P1 card lands"),
    Lane("duo-pairs-gen3",
         [_PY, "-m", "pytest", "tests/e2e/test_duo_gen3.py", "-q", "-p", "no:randomly", "-rs"],
         env={"SLINK_E2E": "1", "SLINK_LIVE": "1"},
         why="the Gen 3 duo scenarios through the real server -- not yet written; fails closed "
             "until the P5 card lands"),
]

# docs/gen3_requirements.md row ids each lane is evidence for.
REQUIREMENTS = {
    "unit": ["F-1", "C-0"],
    "lua-parse": ["C-4"],
    "pins": ["F-1"],
    "profile-generated": ["F-1"],
    "probe-gates": ["S-1", "S-13"],
    "duo-pairs-gen3": ["D-1", "D-3"],
}


def run_lane(lane: Lane, quiet: bool) -> tuple[bool, str]:
    """Gen 3's ALLOWED_SKIPS bound in; the mechanism itself lives in release_lanes."""
    return release_lanes.run_lane(lane, quiet, ALLOWED_SKIPS)


def main() -> int:
    return release_lanes.run_gate(
        title="Gen 3 release gate",
        lanes=LANES,
        requirements=REQUIREMENTS,
        slow=_SLOW,
        run_lane=run_lane,
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())
