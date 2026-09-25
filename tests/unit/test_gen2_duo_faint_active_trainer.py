"""MODEL controls for gen2_faint_active_trainer (O-30 review MINOR-5): scenario_gen2_faint_active.lua with
S.TRAINER, gen2_faint_inputs.lua opts.trainer and the Python oracle's trainer mode, under lupa, no emulator.
Authoring evidence only; the PHYSICAL proof is the duo receipt.
"""
from __future__ import annotations

import json

import pytest
from lupa import LuaRuntime

from tests.unit.test_gen2_duo_driver import (
    FAINT,
    FAINT_INPUTS,
    KEY,
    MENU,
    ROOT,
    SCENARIO,
    point,
    press,
    ui,
)
from tests.unit.test_gen2_duo_faint_active import a_lines, b_lines, edit, without
from tools import gen2_duo_oracles as oracles

ACTIVE = ROOT / "lua/tests/duo/scenario_gen2_faint_active.lua"
TRAINER = ROOT / "lua/tests/duo/scenario_gen2_faint_active_trainer.lua"
SCHEMA = "gen2-duo-faint-active-trainer-v1"
YOUNGSTER, JOEY1 = 22, 1   # data/games/gen2_<title>/trainers.json: class 22 YOUNGSTER, id 1 JOEY1 (C/G/S)


def trainer_verdict(lines):
    lua = LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    link = lua.execute(SCENARIO.read_text(encoding="utf-8"))
    faint = lua.execute(FAINT.read_text(encoding="utf-8"))
    active = lua.execute(ACTIVE.read_text(encoding="utf-8"))
    active.TRAINER, active.RECEIPT_SCHEMA = True, SCHEMA   # what scenario_gen2_faint_active_trainer.lua binds
    problems, receipt = active.verdict(lua.table_from(lines), json_codec, link.verdict, faint.verdict)
    return list(problems.values()), receipt


def trainer_b():
    lines = edit(b_lines(), "LINKED_ACTIVE", battle_mode=2, other_trainer_class=YOUNGSTER, other_trainer_id=JOEY1)
    return without(lines, "NEXT_MON")


def test_the_trainer_file_binds_the_active_scenario():
    lua = LuaRuntime(unpack_returned_tuples=True)
    S = lua.execute(TRAINER.read_text(encoding="utf-8"))
    assert S.TRAINER and S.FAINT_INPUTS and S.BATTLE_TRACE and S.RECEIPT_SCHEMA == SCHEMA
    FA = S.active(str(ROOT).replace("\\", "/"))
    assert FA.TRAINER and FA.RECEIPT_SCHEMA == SCHEMA


@pytest.mark.parametrize("lines", [a_lines(), trainer_b()], ids=["a", "b"])
def test_trainer_verdict_passes_each_complete_half(lines):
    problems, receipt = trainer_verdict(lines)
    assert problems == [], problems
    assert receipt["schema"] == SCHEMA and receipt["key"] == KEY


def test_trainer_receipt_names_the_opposing_trainer():
    _, receipt = trainer_verdict(trainer_b())
    assert dict(receipt["trainer"].items()) == {"class": YOUNGSTER, "id": JOEY1}


def no_live_turn():
    return [x for x in trainer_b() if '"what": "enemy_turn"' not in x]


def crit_ko():
    """TRAINER-FAINT-LIVE-TURN (post-RC): the replacement's crit-KO zeros the foe before it ever moves, so no
    `enemy_turn` trace exists; the `enemy_faint` wEnemyMonHP-read trace is still a live turn."""
    out = []
    for line in trainer_b():
        if line.startswith("BATTLE_TRACE ") and '"what": "enemy_turn"' in line:
            line = line.replace('"what": "enemy_turn"', '"what": "enemy_faint"')
        out.append(line)
    return out


def neither_live_witness():
    """Neither an enemy_turn nor an enemy_faint trace after REPLACED: still refused."""
    return [x for x in trainer_b() if '"what": "enemy_turn"' not in x and '"what": "enemy_faint"' not in x]


@pytest.mark.parametrize("lines,match", [
    (edit(trainer_b(), "LINKED_ACTIVE", battle_mode=1), "trainer-battle"),
    (edit(trainer_b(), "LINKED_ACTIVE", other_trainer_class=0), "no opposing trainer"),
    (b_lines(), "trainer-battle"),                                   # the wild half is not a trainer half
    (edit(b_lines(), "LINKED_ACTIVE", battle_mode=2, other_trainer_class=YOUNGSTER, other_trainer_id=JOEY1),
     "NEXT_MON in a trainer battle"),
    (no_live_turn(), "no live enemy turn"),
    (neither_live_witness(), "no live enemy turn"),
    (without(trainer_b(), "REPLACED"), "missing REPLACED"),
], ids=["wild-mode", "no-trainer", "wild-lines", "next-mon", "no-live-turn", "no-live-turn-or-faint", "no-replacement"])
def test_trainer_verdict_refuses_a_wild_or_incomplete_half(lines, match):
    problems, receipt = trainer_verdict(lines)
    assert receipt is None and any(match in p for p in problems), problems


def test_trainer_verdict_passes_a_crit_ko_with_no_enemy_turn():
    """A crit-KO sequence (no enemy_turn, an enemy faint witnessed instead) still passes."""
    problems, receipt = trainer_verdict(crit_ko())
    assert problems == [], problems
    assert receipt["schema"] == SCHEMA


# --- gen2_faint_inputs.lua opts.trainer ------------------------------------------------------------------

def trainer_driver():
    lua = LuaRuntime(unpack_returned_tuples=True)
    FI = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    walk = lua.eval("{walk_direction=function() return 'Left' end}")
    return lua, FI.driver(walk, lua.table_from({}), lua.table_from({"target": 1, "trainer": True, "any_move": True}))


def test_the_trainer_route_refuses_a_wild_battle():
    lua, d = trainer_driver()
    buttons, why = d.step(point(lua, ui=ui("battle_menu", MENU, 1, 2)))
    assert buttons is None and why == "not a trainer battle"


def test_after_the_faint_the_replacement_fights_and_declines_the_switch_offer():
    lua, d = trainer_driver()
    t = {"battle_mode": 2}
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **t)[0] == ["Right"]          # PKMN: switch the catch in
    after = {"fainted": True, "active_slot": 1, "party_hp": {0: 17, 1: 0}, **t}
    assert press(lua, d, ui=ui("battle_party"), party_cursor=1, **after)[0] == ["Up"]   # ForcePlayerMonChoice
    assert press(lua, d, ui=ui("battle_party"), party_cursor=0, **after)[0] == ["A"]
    after["active_slot"] = 0
    assert press(lua, d, ui=ui("battle_menu", MENU, 1, 2), **after)[0] == ["A"]         # FIGHT, never RUN
    assert press(lua, d, ui=ui("move_menu", ["LEER", "SCRATCH"]), **after)[0] == ["Down"]   # damaging, not LEER
    assert press(lua, d, ui=ui("move_menu", ["LEER", "SCRATCH"], 2), **after)[0] == ["A"]
    assert press(lua, d, ui=ui("yes_no", ["YES", "NO"]), **after)[0] == ["Down"]          # "change #MON?" NO
    del after["active_slot"]
    buttons, phase = d.step(point(lua, battle_mode=0, overworld_ready=True, **{k: v for k, v in after.items()
                                                                                 if k != "battle_mode"}))
    assert phase == "fainted" and not any(buttons.values())


# --- the Python oracle's trainer mode --------------------------------------------------------------------

def test_the_route30_youngsters_resolve_from_every_title_pack():
    for title in ("crystal", "gold", "silver"):
        pack = json.loads((ROOT / f"data/games/gen2_{title}/trainers.json").read_text(encoding="utf-8"))
        cls = next(k for k, v in pack["class_constants"].items() if v == oracles.ROUTE30_TRAINERS[0])
        found = {row["constant"] for row in pack["parties"][cls].values()}
        assert set(oracles.ROUTE30_TRAINERS[1]) <= found, title


def _plain(t):
    try:
        items = list(t.items())
    except AttributeError:
        return t
    if items and all(isinstance(k, int) for k, _ in items):
        return [_plain(v) for _, v in sorted(items)]
    return {k: _plain(v) for k, v in items}


def _spans():
    """The four permit rows the Python oracle expects of a Crystal battle-hold write on slot 1 (its own inputs)."""
    from server.adapters import gen2_codec as codec

    layout = codec.for_foundation("crystal")
    hold = json.loads((ROOT / "data/games/gen2_crystal/write_checkpoint.json").read_text())["titles"]["crystal"]["battle_hold"]
    targets, base = hold["write"]["targets"], layout.addresses["wPartyMon1"] + layout.party_size
    profile = layout.profile["titles"]["crystal"]
    spans = ((targets["wBattleMonHP"]["address"], 2), (base + layout.constants["MON_STATUS"], 1),
             (base + layout.constants["MON_HP"], 2), (targets["wBattlePlayerAction"]["address"], 1))
    return [{"domain": "System Bus", "addr": a, "n": n, "why": "battle_hold", "status": "written", "completed": n,
             "attempted": n, "batch_index": i, "batch_size": 4, "site": "lua/gen2/entry.lua production",
             "evidence": "U2 PHYSICAL receipt", "title": "crystal", "artifact": profile["artifact"],
             "rom_sha1": profile["rom_sha1"]} for i, (a, n) in enumerate(spans, 1)], hold


def oracle_results(b, scenario="gen2_faint_active_trainer"):
    spans, hold = _spans()
    b = edit(b, "BATTLE_HOLD_WRITE", log=spans, pc=hold["execution_before"]["pc"], hrom_bank=hold["execution_before"]["bank"])
    out = {}
    for side, lines in (("a", a_lines()), ("b", b)):
        lines = edit(lines, "DUO_GEN2", scenario=scenario)
        _, receipt = trainer_verdict(lines)
        out[side] = "\n".join(lines +["RECEIPT " + json.dumps(_plain(receipt)), "RESULT: PASS (x)"])
    return out


def validate(results):
    return oracles.validate_faint_active_markers(results, title_b="crystal", key_a=KEY, key_b=KEY, species_b=16,
                                                 trainer=True)


def dead_turn():
    """A Lua-PASS trainer proof whose enemy_turn trace is removed after the fact (the Python check alone); no
    enemy_faint trace either, so neither live-turn witness is seen."""
    results = oracle_results(trainer_b())
    results["b"] = "\n".join(x for x in results["b"].splitlines() if '"what": "enemy_turn"' not in x)
    return results


def test_the_python_validator_accepts_a_route30_trainer_proof():
    proof = validate(oracle_results(trainer_b()))
    assert proof["active"]["battle_mode"] == 2 and proof["replaced"]["active_slot"] == 0


def test_the_python_validator_accepts_a_crit_ko_trainer_proof():
    """TRAINER-FAINT-LIVE-TURN: a crit-KO sequence (no enemy_turn, an enemy_faint witnessed instead) passes."""
    proof = validate(oracle_results(crit_ko()))
    assert proof["replaced"]["active_slot"] == 0


@pytest.mark.parametrize("results,match", [
    (oracle_results(trainer_b(), scenario="gen2_faint_active"), "scenario/schema"),
    (oracle_results(edit(trainer_b(), "LINKED_ACTIVE", other_trainer_id=3)), "not a Route 30 youngster"),
    (oracle_results(edit(trainer_b(), "LINKED_ACTIVE", other_trainer_class=5)), "not a Route 30 youngster"),
    (dead_turn(), "no live enemy turn"),
], ids=["wild-scenario", "other-youngster", "other-class", "no-live-turn"])
def test_the_python_validator_refuses_a_foreign_or_dead_trainer_proof(results, match):
    with pytest.raises(RuntimeError, match=match):
        validate(results)
