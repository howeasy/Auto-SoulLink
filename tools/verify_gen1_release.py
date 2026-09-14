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
    9. live-gates         — real engine behaviour on real cartridges, incl. the panel
                            on a randomized+injected ROM
   10. live-new-gates     — the rewritten Gen 1 modules on all three cartridges
   11. live-trade-gates   — the SLINK TRADE receptionist on the patched cartridges
   12. duo-pairs          — every scenario on both pairings, through the real server

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

import argparse
import os
import re
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY = sys.executable

# Lanes that need an emulator, and therefore minutes rather than seconds.
_SLOW = {"live-gates", "live-new-gates", "live-trade-gates", "duo-pairs"}

# ── Skips that are allowed, each with the reason it is allowed ──────────────────────────
# The gate's whole point is that a skip is a failure, so an exception has to be argued for
# by name. These fragments are matched against pytest's own `-rs` reason lines; anything
# NOT matched fails the lane, which is what stops a newly-disabled test reading as green.
#
# Every entry is out of Gen 1's scope, not merely inconvenient. There are deliberately no
# Gen 1 entries: a Gen 1 test that skips is a defect in this gate's inputs.
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
    ("not built — `python tools/gen1_ap_rom.py`",
     "Archipelago is DEFERRED for this release by scope, and its ROMs are built from a "
     "third-party apworld that is not ours to ship. The AP gate exists and passes when "
     "those ROMs are present; it is not part of the vanilla Gen 1 verdict. This is the "
     "one Gen 1 entry on this list, and it is here because of scope rather than "
     "convenience — if Archipelago is ever un-deferred, delete this line first."),
]


class Lane:
    def __init__(self, name, argv, env=None, why=""):
        self.name, self.argv, self.env, self.why = name, argv, env or {}, why

    @property
    def is_pytest(self) -> bool:
        return "pytest" in self.argv


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
    Lane("statics-generated", [_PY, "tools/gen_gen1_statics.py", "--check"],
         why="static_encounters.json is exactly what pret's scripts/objects say"),
    Lane("fixtures", [_PY, "tools/gen1_fixtures.py", "--qualify"],
         why="every committed battery save is a real game state the codec qualifies "
             "(Yellow legacy pinned by name)"),
    Lane("patch-build", [_PY, "patch/gen1/tools/build.py", "--verify-only"],
         why="the clean dumps still hold what the manifest expects to displace"),
    Lane("live-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_gates.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_LIVE": "1"},
         why="real engine behaviour on real cartridges, including the panel on a "
             "randomized+injected ROM"),
    Lane("live-new-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_new_gates.py", "-q", "-p",
          "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1"},
         why="the rewritten Gen 1 modules on all three cartridges: pinned engine sites "
             "present, hooks armed, live party decoded identically in Lua and Python, "
             "overworld write checkpoint reached (docs/gen1_requirements.md R-1, S, W-7, "
             "F-6)"),
    Lane("live-trade-gates",
         [_PY, "-m", "pytest", "tests/live/test_gen1_trade_gates.py", "-q", "-p",
          "no:randomly", "-rs"],
         env={"SLINK_LIVE": "1"},
         why="the SLINK TRADE receptionist on the patched Red/Blue cartridges: menu, offer, "
             "refusal and acceptance texts, every client line schema-valid "
             "(docs/gen1_requirements.md T-1, T-2)"),
    Lane("duo-pairs",
         [_PY, "-m", "pytest", "tests/e2e/test_duo_gen1.py", "-q", "-p", "no:randomly",
          "-rs"],
         env={"SLINK_E2E": "1"},
         why="every scenario on both pairings, through the real server"),
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
    "statics-generated": ["F-5", "S-8"],
    "fixtures": ["F-6"],
    "patch-build": ["T-1"],
    "live-gates": ["(pre-rewrite gates; retired in Phase 8)"],
    "live-new-gates": ["R-1", "S", "W-7", "F-6"],
    "live-trade-gates": ["T-1", "T-2"],
    "duo-pairs": ["D-1..D-14 (pre-rewrite scenarios; rewritten in Phase 6)"],
}


def _count_outcomes(text: str) -> dict:
    """pytest's own summary line, parsed. Anything that is not a pass is a problem."""
    out = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0,
           "error": 0, "deselected": 0}
    for key in out:
        m = re.search(rf"(\d+) {key}", text)
        if m:
            out[key] = int(m.group(1))
    return out


def _unexplained_skips(text: str) -> list[str]:
    """Skip reasons with no entry in ALLOWED_SKIPS.

    Read from pytest's `-rs` summary, which every pytest lane here asks for — a skip whose
    reason was never printed is itself unexplained, and fails.
    """
    out = []
    for line in text.splitlines():
        if not line.startswith("SKIPPED"):
            continue
        if not any(frag in line for frag, _why in ALLOWED_SKIPS):
            out.append(line.strip())
    return out


def run_lane(lane: Lane, quiet: bool) -> tuple[bool, str]:
    env = dict(os.environ)
    env.update(lane.env)
    started = time.time()
    proc = subprocess.run(lane.argv, cwd=_REPO, env=env, capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    took = time.time() - started

    ok = proc.returncode == 0
    detail = f"exit {proc.returncode}  ({took:.0f}s)"

    if lane.is_pytest:
        counts = _count_outcomes(text)
        unexplained = _unexplained_skips(text)
        detail = (f"{counts['passed']} passed, {counts['skipped']} skipped "
                  f"({len(unexplained)} unexplained), {counts['failed']} failed, "
                  f"{counts['xfailed']} xfailed, {counts['deselected']} deselected  "
                  f"({took:.0f}s)")
        # Deselection counts too: a test filtered out by -k or a marker is a test that did
        # not run, and this gate cannot tell the difference between that and not existing.
        if (unexplained or counts["xfailed"] or counts["xpassed"]
                or counts["deselected"] or counts["error"] or counts["failed"]):
            ok = False
        if unexplained and not quiet:
            print("  skips with no entry in ALLOWED_SKIPS:")
            for line in unexplained:
                print(f"    - {line}")

    if not ok and not quiet:
        print(text[-4000:])
    return ok, detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true",
                    help="stop before the lanes that need an emulator")
    ap.add_argument("--list", action="store_true", help="show the lanes and exit")
    ap.add_argument("--lane", action="append", metavar="NAME",
                    help="run only this lane (repeatable); see --list for the names")
    ap.add_argument("--quiet", action="store_true", help="do not dump failing output")
    args = ap.parse_args()

    names = [lane.name for lane in LANES]
    if args.lane:
        unknown = [name for name in args.lane if name not in names]
        if unknown:
            print(f"unknown lane(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"lanes: {', '.join(names)}", file=sys.stderr)
            return 2

    if args.list:
        for lane in LANES:
            mark = "slow" if lane.name in _SLOW else "fast"
            print(f"  {lane.name:<18} [{mark}]  {lane.why}")
            print(f"    requirements: {', '.join(REQUIREMENTS[lane.name])}")
        return 0

    wanted = set(args.lane) if args.lane else set(names)
    lanes = [x for x in LANES
             if x.name in wanted and not (args.quick and x.name in _SLOW)]
    print(f"Gen 1 release gate — {len(lanes)} lanes\n")
    failed = []
    for lane in lanes:
        print(f"[ .. ] {lane.name}", flush=True)
        ok, detail = run_lane(lane, args.quiet)
        print(f"[{'PASS' if ok else 'FAIL'}] {lane.name:<18} {detail}")
        if not ok:
            failed.append(lane.name)

    print()
    if failed:
        print(f"GATE FAILED — {', '.join(failed)}")
        print("A skipped, xfailed or deselected test counts as a failure here: it did not "
              "run, and 'did not run' is not 'passed'.")
        return 1
    if args.quick:
        print("Fast lanes passed. The emulator lanes were NOT run, so this is not a "
              "release verdict — re-run without --quick.")
        return 0
    print("GATE PASSED — every lane ran and every lane passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
