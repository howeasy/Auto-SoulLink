#!/usr/bin/env python3
"""Build the FRLG checkpoint-probe savestates (card C4-PROBE) from the committed party batteries.

Cold-boots tests/fixtures/gen3/<title>_party_<kind>.sav through gen3_fixtures.py's per-run
SaveRAM plumbing (no developer battery touched) and drives lua/tests/mkstates_gen3.lua with
scripted normal inputs. Kinds: town -> slink_overworld/slink_door/slink_script; battle ->
slink_preintro/slink_prebattle/slink_postbattle; trainer (seeded from the town battery) ->
slink_pretrainer/slink_prefaint (the Route 22 early rival). Point the probe at the output with
SLINK_STATE_DIR.

    python tools/mkstates_gen3.py --title firered --kind town --out-dir patch/build/gen3_probe_states/firered
    python tools/mkstates_gen3.py --title leafgreen --kind battle --out-dir patch/build/gen3_probe_states/leafgreen
    python tools/mkstates_gen3.py --title emerald --kind town --out-dir C:/slink-wt/emerald-e2/states

Emerald (card E2-CKPT) boots tests/fixtures/gen3/emerald_<kind>.sav under the Emerald pack: town ->
slink_overworld/slink_door (Oldale heal tile, one step S of the Center door), slink_pokecenter
(Center 1F arrival), slink_script (below the nurse); battle -> Route 102 grass; trainer -> the
Youngster Calvin battle parked at the action menu (slink_pretrainer only).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen3_fixtures as fx  # noqa: E402

LUA = "lua/tests/mkstates_gen3.lua"
# kind -> the party battery it cold-boots from
FIXTURE_KIND = {"town": "town", "battle": "battle", "trainer": "town"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--title", choices=sorted(fx.PARTY_TITLES), default="firered")
    ap.add_argument("--kind", choices=sorted(FIXTURE_KIND), required=True)
    ap.add_argument("--out-dir", required=True, help="where the .State files land")
    ap.add_argument("--rom", default=None, help="default: the title's dump at the checkout root")
    ap.add_argument("--saveram-name", default=None, help="default: the title's gamedb battery name")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    rom = fx.resolve_rom(args.title, args.rom)
    meta = fx.PARTY_TITLES[args.title]
    # E2-CKPT: emerald names its fixtures emerald_<kind>.sav, one per kind (trainer included),
    # and runs under its own checkpoint pack; FR/LG keep <title>_party_<FIXTURE_KIND>.sav
    if "fixture" in meta:
        fixture = fx.FIXTURES_DIR / str(meta["fixture"]).format(kind=args.kind)
    else:
        fixture = fx.FIXTURES_DIR / f"{args.title}_party_{FIXTURE_KIND[args.kind]}.sav"
    extra_env = {"SLINK_STATE_KIND": args.kind}
    if "checkpoint" in meta:
        extra_env["SLINK_GEN3_CHECKPOINT"] = str(Path(fx.REPO) / str(meta["checkpoint"]))
    seed = fx.codec.split_rtc(fixture.read_bytes())[0]
    saveram = args.saveram_name or str(meta["saveram"])
    rom_rel, run_dir, _ = fx._prepare_run(f"mkstates_{args.title}_{args.kind}", rom,
                                          seed=seed, saveram_name_override=saveram)
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"seeded {run_dir / saveram} from {fixture}; states -> {out}")
    passed, text = fx._launch(LUA, rom_rel, run_dir, rr=False, timeout=args.timeout,
                              title=args.title,
                              extra_env={**extra_env, "SLINK_STATE_DIR": out.as_posix()})
    print(text.rstrip())
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
