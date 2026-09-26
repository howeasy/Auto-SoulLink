#!/usr/bin/env python3
"""Build slink_oldman.State + slink_pokedude.State (card 2B-TUTORIAL-STATES) by normal inputs.

One session per title: cold-boot tests/fixtures/gen3/<title>_party_town.sav through
gen3_fixtures.py's per-run SaveRAM plumbing (the committed fixture is only read) and drive
lua/tests/mkstates_gen3_tutorials.lua: Viridian (24,39) -> the old-man trigger (22,8) ->
the demo battle -> TEACHY TV -> TTVSCR_BATTLE -> the Pokedude demo.

    python tools/mkstates_gen3_tutorials.py --title firered
    python tools/mkstates_gen3_tutorials.py --title leafgreen

States land in patch/build/gen3_probe_states/<title>/ unless --out-dir says otherwise.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen3_fixtures as fx  # noqa: E402

LUA = "lua/tests/mkstates_gen3_tutorials.lua"
VAR_OLD_MAN, ITEM_TEACHY_TV = 0x4051, 366
SB1_VARS, SB1_KEY_ITEMS, KEY_ITEMS = 0x1000, 0x3B8, 30   # pret include/global.h:779,791


def precondition(sb1: bytes) -> list[str]:
    """Why this SaveBlock1 cannot start the tutorial (empty = it can). Read-only."""
    var = int.from_bytes(sb1[SB1_VARS + (VAR_OLD_MAN - 0x4000) * 2:][:2], "little")
    keys = [int.from_bytes(sb1[SB1_KEY_ITEMS + 4 * i:][:2], "little") for i in range(KEY_ITEMS)]
    problems = []
    if var != 1:
        problems.append(f"var 0x4051 is {var}, the old-man trigger needs 1")
    if ITEM_TEACHY_TV in keys:
        problems.append("TEACHY TV is already in the key pocket")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", choices=["firered", "leafgreen"], required=True)
    ap.add_argument("--out-dir", default=None, help="default: patch/build/gen3_probe_states/<title>")
    ap.add_argument("--rom", default=None, help="default: the title's dump at the checkout root")
    ap.add_argument("--saveram-name", default=None, help="default: the title's gamedb battery name")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    fixture = fx.FIXTURES_DIR / f"{args.title}_party_town.sav"
    image = fixture.read_bytes()
    problems = precondition(fx.codec.parse_flash(image)["sb1"])
    if problems:
        print(f"{fixture}: " + "; ".join(problems), file=sys.stderr)
        return 1
    rom = fx.resolve_rom(args.title, args.rom)
    saveram = args.saveram_name or str(fx.PARTY_TITLES[args.title]["saveram"])
    rom_rel, run_dir, _ = fx._prepare_run(f"mkstates_tutorials_{args.title}", rom,
                                          seed=fx.codec.split_rtc(image)[0],
                                          saveram_name_override=saveram)
    out = Path(args.out_dir or fx.REPO + f"/patch/build/gen3_probe_states/{args.title}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"seeded {run_dir / saveram} from {fixture}; states -> {out}")
    passed, text = fx._launch(LUA, rom_rel, run_dir, rr=False, timeout=args.timeout,
                              title=args.title, extra_env={"SLINK_STATE_DIR": out.as_posix()})
    print(text.rstrip())
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
