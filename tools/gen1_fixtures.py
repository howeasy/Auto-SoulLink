#!/usr/bin/env python3
"""Build tests/fixtures/gen1/<rom>_<target>.SaveRAM from REAL scripted play (F-6).

The previous fixtures were written byte-by-byte by a tool (level 5 with exp 0, OT "RST"):
not game states. This one cold-boots the cartridge in EmuHawk, plays NEW GAME -> starter ->
rival battle -> (chain) -> START/SAVE with ordinary buttons (lua/tests/test_gen1_scripted_gate.lua),
flushes SaveRAM, copies it into the fixture slot and qualifies it with the Python codec: the
game's main checksum, one decodable party mon whose exp matches its level on its growth curve.

    python tools/gen1_fixtures.py red town          # lab -> save (Oak's Lab, encounter-free)
    python tools/gen1_fixtures.py blue town --player b
    python tools/gen1_fixtures.py red battle        # lab -> parcel -> Route 1 (10,35) -> save, a ball in the bag

Red/Blue only: the route modules are the R/B lab route. One emulator lane; nothing else running.

    python tools/gen1_fixtures.py --qualify      # re-check the committed fixtures, no emulator

--qualify never touches EmuHawk: it reads tests/fixtures/gen1/*.SaveRAM, decodes each party
against the matching dump and classifies the result, so the fixture lane can be verified (and
a stale fixture detected) without a 15-minute emulator run. Exit 1 if any fixture is REFUSED.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from server.adapters import gen1_codec as codec, gen1_rom_scan as scan  # noqa: E402

GATE = "lua/tests/test_gen1_scripted_gate.lua"
CHAINS = {"town": "lab,save", "battle": "lab,parcel,route1,save"}
SAVERAM_NAME = {"red": "Pokemon - Red Version (USA, Europe).SaveRAM",
                "blue": "Pokemon - Blue Version (USA, Europe).SaveRAM"}
DUMP = {"red": "patch/build/gen1_red.gb", "blue": "patch/build/gen1_blue.gb",
        "yellow": "patch/build/gen1_yellow.gbc"}
FIXTURES = os.path.join(REPO, "tests", "fixtures", "gen1")

# Fixtures still holding the OLD harness' bytes: written directly into SaveRAM, so the party
# mon has a level byte and exp 0, which no game state produces (AddPartyMon derives exp from
# the level, engine/pokemon/add_mon.asm:202-207). Named individually so a regenerated fixture
# cannot hide behind a blanket tolerance -- anything not listed here must qualify clean.
LEGACY = {"yellow_town", "yellow_battle"}
_LEGACY_PROBLEM = re.compile(r"^slot \d+: exp 0 is not level \d+ on curve \d+$")


def is_legacy_artefact(problems: list[str]) -> bool:
    """True when EVERY problem is the old harness' exp-0 artefact, and nothing else."""
    return bool(problems) and all(_LEGACY_PROBLEM.match(p) for p in problems)


def qualify(sram: bytes, rom: bytes) -> list[str]:
    """Problems with a candidate fixture (empty = a real, consistent save)."""
    problems = []
    if len(sram) != 0x8000:
        return [f"SaveRAM is {len(sram)} bytes, not 32768"]
    if not codec.verify_bank1(sram):
        problems.append("main data checksum does not validate (the game would not offer CONTINUE)")
    try:
        party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["size"]])
    except ValueError as exc:
        # A blank or torn save makes the decoder refuse rather than return an empty party
        # (gen1_codec._decode_collection checks the species terminator), and a qualifier's
        # job is to NAME that state, not to raise on it.
        problems.append(f"no party mon in the save: the party block is undecodable ({exc})")
        party = []
    if not party and not any("no party mon" in p for p in problems):
        problems.append("no party mon in the save")
    stats = scan.scan_base_stats(rom)
    for slot, mon in enumerate(party):
        entry = stats[codec.internal_to_natdex(mon["species"])]
        if codec.level_from_exp(entry["growth_rate"], mon["exp"]) != mon["level"]:
            problems.append(f"slot {slot}: exp {mon['exp']} is not level {mon['level']} on curve {entry['growth_rate']}")
        got = codec.recompute_stats(mon, entry)
        for k, v in got.items():
            if mon[k] != v:
                problems.append(f"slot {slot}: stored {k}={mon[k]} but recomputed {v}")
    return problems


def qualify_all() -> int:
    """One line per committed fixture; exit 1 if any of them is REFUSED.

    OK       -- qualify() found nothing wrong: these bytes are a real, consistent save.
    LEGACY   -- the only problem is the old harness' exp-0 artefact AND the fixture is
                named in LEGACY, i.e. it is a known un-regenerated file rather than a
                regression in the codec or the dump.
    REFUSED  -- anything else, including a missing dump: the fixture cannot be trusted.
    """
    refused = 0
    for name in sorted(os.listdir(FIXTURES)):
        if not name.endswith(".SaveRAM"):
            continue
        stem = name[:-len(".SaveRAM")]
        rom_rel = DUMP.get(stem.split("_")[0])
        if rom_rel is None or not os.path.exists(os.path.join(REPO, rom_rel)):
            print(f"{stem}: NO-ROM")
            refused += 1
            continue
        with open(os.path.join(FIXTURES, name), "rb") as f:
            sram = f.read()
        with open(os.path.join(REPO, rom_rel), "rb") as f:
            rom = f.read()
        problems = qualify(sram, rom)
        if not problems:
            party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["size"]])
            print(f"{stem}: OK party={[(m['species'], m['level'], m['exp']) for m in party]}")
        elif stem in LEGACY and is_legacy_artefact(problems):
            print(f"{stem}: LEGACY {'; '.join(problems)}")
        else:
            print(f"{stem}: REFUSED {'; '.join(problems)}")
            refused += 1
    return 1 if refused else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="?", choices=sorted(SAVERAM_NAME))
    ap.add_argument("target", nargs="?", choices=sorted(CHAINS))
    ap.add_argument("--qualify", action="store_true",
                    help="check tests/fixtures/gen1/*.SaveRAM against the dumps and exit "
                         "(no emulator, no writes)")
    ap.add_argument("--player", choices=("a", "b"), default=None, help="a = Bulbasaur, b = Charmander (default: red a, blue b)")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    if args.qualify:
        return qualify_all()
    if args.rom is None or args.target is None:
        ap.error("rom and target are required unless --qualify")
    player = args.player or ("a" if args.rom == "red" else "b")

    import gen1_playthrough as play
    from run_gb_gate import run_gate
    env = dict(os.environ, SLINK_SCRIPT_CHAIN=CHAINS[args.target], SLINK_SCRIPT_PLAYER=player, SLINK_SCRIPT_FLUSH="1")
    os.environ.update(env)
    passed, path, text = run_gate(GATE, rom_key=f"{args.rom}_cold", target="town", timeout=args.timeout)
    print(text[-2500:])
    if not passed:
        print("scripted play did not reach its terminals; no fixture written", file=sys.stderr)
        return 1
    src = os.path.join(play.SAVERAM_DIR, SAVERAM_NAME[args.rom])
    if not os.path.exists(src):
        print(f"EmuHawk left no SaveRAM at {src}", file=sys.stderr)
        return 1
    with open(src, "rb") as f:
        sram = f.read()
    with open(os.path.join(REPO, DUMP[args.rom]), "rb") as f:
        rom = f.read()
    problems = qualify(sram, rom)
    if problems:
        print("candidate fixture refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    dest = os.path.join(REPO, "tests", "fixtures", "gen1", f"{args.rom}_{args.target}.SaveRAM")
    shutil.copyfile(src, dest)
    party = codec.decode_party(sram[codec.SRAM_LAYOUT["sPartyData"]:codec.SRAM_LAYOUT["sPartyData"] + 404])
    print(f"wrote {os.path.relpath(dest, REPO)}: party={[(m['species'], m['level'], m['exp']) for m in party]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
