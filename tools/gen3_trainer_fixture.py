"""Build tests/fixtures/gen3/{firered,leafgreen}_party_trainer{,_b}.sav (card G4-SYNTH-TRAINER).

CACHED-NATIVE, not SYNTH: one duo run per title plays linked_faint_active_trainer_gen3's own T2
preparation (lua/tests/gen3_routes.lua, scripted normal input, the production client connected)
from the title's town fixture on side B, stops one tile west of Bug Catcher Rick 102's sight line
(Viridian Forest 1.0 (41,45)) and saves in-game there
(lua/tests/duo/scenario_gen3_trainer_fixture.lua). The flushed battery is imported as-is; the
`_b` file is `derive-b` over it (OT identity only, PLAN §11). Nothing is poked or staged.

    python tools/gen3_trainer_fixture.py --title leafgreen   # B of gen3_frlg
    python tools/gen3_trainer_fixture.py --title firered     # B of gen3_lgfr
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_duo  # noqa: E402
import gen3_fixtures  # noqa: E402

codec = gen3_fixtures.codec
SCENARIO = "trainer_fixture_gen3"
GAME_FOR = {"leafgreen": "gen3_frlg", "firered": "gen3_lgfr"}   # the pairing with the title on B
STOP = (1, 0, 41, 45)   # Viridian Forest; Rick 102 at (47,45) facing west, sight 5 -> 42..46
FLOOR = 13              # gen3_routes.lua's preparation level floor

e2e_duo.SCENARIOS[SCENARIO] = {
    "flags": [], "timeout": 7200, "games": ("gen3_frlg",), "frames": 8000000,
    "target": {"a": "battle", "b": "town"}, "scenario_module": "trainer_fixture",
    "active_faint_case": "trainer",   # duo_gen3_main.lua binds the T2 route seams on this
}


def fixture_problems(body: bytes) -> list[str]:
    """What makes a flash body a usable trainer fixture: qualifies, saved on STOP, two mons, the
    lead at the floor with full HP and no status."""
    ok, msg = codec.qualify_flash(body)
    if not ok:
        return [f"qualify_flash: {msg}"]
    sb1 = codec.parse_flash(body)["sb1"]   # SaveBlock1: pos (s16 x, s16 y), location group/num
    where = (sb1[4], sb1[5], int.from_bytes(sb1[0:2], "little", signed=True),
             int.from_bytes(sb1[2:4], "little", signed=True))
    problems = [] if where == STOP else [f"saved at {where}, not {STOP}"]
    party = codec.party_from_save(body)
    if len(party) < 2:
        return problems + [f"party of {len(party)}, the route needs a lead and a bench"]
    lead = party[0]
    if lead["level"] < FLOOR:
        problems.append(f"lead Lv{lead['level']} < {FLOOR}")
    if lead["hp"] != lead["max_hp"] or lead["status"] != 0:
        problems.append(f"lead hp {lead['hp']}/{lead['max_hp']} status {lead['status']}")
    return problems


class TrainerFixtureRun(e2e_duo.DuoRun):
    out: Path

    def orchestrate(self):
        self._gen3_prelude()          # MYKEY + both hellos; no link, nothing staged
        self._gen3_area_control()     # the live row's own server-only write-window control
        self.go()

    def _run_oracle(self, results):
        self._gen3_flush_boundary()
        problems = e2e_duo.gen3_receipt_problems(
            "b", results["b"], required=[r"(?m)^TRAINER_FIXTURE ", r"(?m)^SAVE_WITNESS trainer_fixture ",
                                         r"(?m)^WRITES 0$"])
        body = gen3_fixtures.import_savedata(self._gen3_flushed("b"), rr=False)
        problems += fixture_problems(body)
        if problems:
            raise RuntimeError("trainer fixture refused: " + "; ".join(problems))
        b_body, _ = gen3_fixtures.derive_b(body)
        for path, data in ((self.out, body), (self.out.with_name(self.out.stem + "_b.sav"), b_body)):
            path.write_bytes(data)
            print(f"[fixture] wrote {path} sha256={gen3_fixtures.sha256_hex(data)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", required=True, choices=sorted(GAME_FOR))
    ap.add_argument("--out", help="default tests/fixtures/gen3/<title>_party_trainer.sav")
    ap.add_argument("--lane", default="trainer-fixture")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run_args = argparse.Namespace(game=GAME_FOR[args.title], lane=args.lane, idle_jitter=0,
                                  keep_alive=False, keep_data=False, server_flags=[],
                                  wrong_save=None, wire_log=False, scenario=SCENARIO)
    run = TrainerFixtureRun(SCENARIO, run_args)
    run.out = Path(args.out or os.path.join(e2e_duo.GEN3_FIXTURES, f"{args.title}_party_trainer.sav"))
    return 0 if run.run() else 1


if __name__ == "__main__":
    sys.exit(main())
