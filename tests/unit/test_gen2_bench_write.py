"""O-32 (card gen2-bench-write): a Gen 2 BENCH death lands on receipt, like Gen 1's battle_bench write.

Owner 2026-09-24: "Lets match gen1. Death should be immediate if possible." The client lands the death at
the frame end after the command arrives (lua/gen2/client.lua land_bench_deaths), under the receipt-time
write kind battle_bench (lua/gen2_write_safety.lua evaluate_frame / battle_bench_problem). The active
battler still dies at the battle hold (W-2), and link battles never write. Harnesses are reused from
tests/unit/test_gen2_client.py and tests/unit/test_gen2_write_safety.py.
"""

import copy
import json

import pytest

from tests.unit import test_gen2_client as g2
from tests.unit.test_gen2_client import (
    ROOT,
    action,
    battle_hold,
    battle_hp,
    codec_key,
    end_battle,
    hold_ram,
    in_battle,
    mon,
)
from tests.unit.test_gen2_write_safety import Candidate


def kod(world):
    return [s for s in world.shown() if "KO'd" in s]


def only(world, *kinds):
    """The stub checkpoint authorizes only `kinds` (while checkpoint_ok): a production frame end in battle is
    never the overworld checkpoint, so party_hp must not stand in for battle_bench."""
    world.parts.checkpoint.check = world.lua.eval(
        "function(f) return function(_, kind) return f(kind) end end")(
        lambda kind: (world.checkpoint_ok and kind in kinds, "stub checkpoint"))


def bench_world(**battle):
    world = g2.World()
    party = [mon(), mon(species=172, dvs=0x3AAA)]
    in_battle(world, party, **battle)
    return world, party


# ── the client ───────────────────────────────────────────────────────────────────────────────────────
def test_a_bench_death_lands_the_frame_it_arrives_without_a_hold():
    world, party = bench_world()
    only(world, "battle_bench", "battle_faint")
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(1)                                                  # no battle hold fired
    assert world.hp_of(1) == (0, 0) and world.hp_of(0) == (30, 0)
    assert battle_hp(world) == 30 and action(world) == 0             # the active battler is untouched
    assert kod(world) == ["show:!! PICHU KO'd"]
    battle_hold(world)                                               # the hold has nothing more to do
    assert world.hp_of(0) == (30, 0) and battle_hp(world) == 30 and kod(world) == ["show:!! PICHU KO'd"]


@pytest.mark.parametrize("battle_type", [0, 6])                     # NORMAL, CONTEST: every kind but link
def test_the_active_battler_still_waits_for_the_battle_hold(battle_type):
    world, party = bench_world(battle_type=battle_type)
    world.reply({"cmd": "force_faint", "key": codec_key(party[0]), "nickname": "PIKA"})
    world.frames(3)
    assert world.written() == [] and battle_hp(world) == 30
    battle_hold(world)
    assert battle_hp(world) == 0 and world.hp_of(0) == (0, 0) and action(world) == 1


def test_a_link_battle_bench_death_never_lands_on_receipt():
    world, party = bench_world(link=1)
    world.reply({"cmd": "force_faint", "key": codec_key(party[1])})
    world.frames(3)
    assert world.written() == [] and world.hp_of(1) == (30, 0)


def test_a_refused_frame_retries_on_the_next_one():
    """A battle animation selects SVBK 5 (the evaluation refuses): the write waits one frame, not a turn."""
    world, party = bench_world()
    world.checkpoint_ok = False
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(2)
    assert world.written() == []
    world.checkpoint_ok = True
    world.frames(1)
    assert world.hp_of(1) == (0, 0) and kod(world) == ["show:!! PICHU KO'd"]


def test_a_switch_in_that_beat_the_write_dies_at_the_hold_before_it_acts():
    """TryPlayerSwitch passed CheckIfCurPartyMonIsFitToFight, then the write landed, then InitBattleMon copied
    the dead mon in (C engine/battle/core.asm:5176-5271): the entry stays queued, so W-2 kills it at the hold."""
    world, party = bench_world()
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(1)
    assert world.hp_of(1) == (0, 0)
    world.field("wCurBattleMon", 1)                                  # the switch completed
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonSpecies"), world.lua.table_from([172]))
    battle_hold(world)
    assert battle_hp(world) == 0 and action(world) == 1              # dies before it acts
    assert kod(world) == ["show:!! PICHU KO'd"]                      # announced once

def test_a_switch_before_the_command_dies_at_the_active_hold():
    """PlayerSwitch selects the incoming slot before InitBattleMon replaces the outgoing battle view."""
    world, party = bench_world()
    only(world, "battle_bench", "battle_faint")
    world.field("wCurBattleMon", 1)                                  # PlayerSwitch selected Pichu
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(1)
    assert world.written() == [] and world.hp_of(1) == (30, 0)      # active slot: no bench write
    assert battle_hp(world) == 30 and kod(world) == []
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonSpecies"), world.lua.table_from([172]))
    battle_hold(world)                                               # InitBattleMon has copied Pichu
    assert battle_hp(world) == 0 and world.hp_of(1) == (0, 0)       # battle view and party mirror
    assert world.hp_of(0) == (30, 0) and action(world) == 1
    assert kod(world) == ["show:!! PICHU KO'd"]                      # one active-path KO

def test_a_revived_bench_mon_is_re_zeroed_quietly_at_the_next_hold():
    """GiveExperiencePoints tests HP before the exp text and adds the level-up HP gain after it
    (C core.asm:7004, :7121-7240): a write landing in between is undone; the quiet re-zero catches it."""
    world, party = bench_world()
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(1)
    world.party([party[0], dict(party[1], hp=3)])                   # the level-up gain revived it
    battle_hold(world)
    assert world.hp_of(1) == (0, 0) and kod(world) == ["show:!! PICHU KO'd"]


def test_a_death_deferred_before_the_battle_lands_at_the_first_battle_frame():
    world, party = bench_world()
    world.field("wBattleMode", 0)                                    # the trainer's pre-battle text
    world.checkpoint_ok = False
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(2)
    assert world.written() == []
    world.field("wBattleMode", 1)
    world.checkpoint_ok = True
    only(world, "battle_bench")                                      # no checkpoint, no hold: a battle frame
    world.fire("wild_ready")
    world.frames(1)
    assert world.hp_of(1) == (0, 0) and kod(world) == ["show:!! PICHU KO'd"]


def test_a_landed_bench_death_is_re_zeroed_quietly_at_the_checkpoint():
    world, party = bench_world()
    world.reply({"cmd": "force_faint", "key": codec_key(party[1]), "nickname": "PICHU"})
    world.frames(1)
    world.checkpoint_ok = False
    end_battle(world)
    world.party([party[0], dict(party[1], hp=5)])                   # EvolveAfterBattle's max-HP gain
    world.checkpoint_ok = True
    world.frames(3)
    assert world.hp_of(1) == (0, 0) and kod(world) == ["show:!! PICHU KO'd"]


def test_without_the_bench_kind_the_death_waits_for_the_hold():
    """Production before a battle_bench receipt: the client composes no receipt-time write."""
    world = g2.World(swaps=g2.mutant("lua/gen2/entry.lua", (
        'battle_bench=(not production or (checkpoint:covers("battle_faint") and checkpoint:covers("battle_bench"))),',
        "battle_bench=false,")))
    party = [mon(), mon(species=172, dvs=0x3AAA)]
    in_battle(world, party)
    world.reply({"cmd": "force_faint", "key": codec_key(party[1])})
    world.frames(2)
    assert world.written() == []
    battle_hold(world)
    assert world.hp_of(1) == (0, 0)


# ── the write kind (lua/gen2_write_safety.lua) ─────────────────────────────────────────────────────────
def frame(title="crystal"):
    """A battle frame end: the candidate CPU is anywhere (not a hold), wBattleMode 1, wLinkMode 0."""
    c = Candidate(title)
    c.registers["PC"] = 0x0150
    mode = next(r for r in c.data["primary"]["state_predicates"] if r["symbol"] == "wBattleMode")
    c.memory["System Bus", mode["address"]] = 1
    return c


def bench_run(title="crystal"):
    write = {"ok": True, "where": "frame_end", "seq": 1, "battle_mode": 1, "slot": 1, "active_slot": 0,
             "hp_before_hex": "000e", "hp_after_hex": "0000", "status_after_hex": "00",
             "battle_hp_before_hex": "0011", "battle_hp_after_hex": "0011",
             "action_before_hex": "00", "action_after_hex": "00"}
    refused = {"refused": True, "reason": "not in a battle", "before_hex": "00000e", "after_hex": "00000e"}
    return {"catch": {"party_before": 1, "party_after": 2}, "bench_write": write,
            "refusals": {"overworld": refused, "active": dict(refused, reason="active faint timing is not qualified")},
            "trace": [{"seq": 2, "what": "pkmn_loop"}, {"seq": 3, "what": "fit_check", "party_mon": 1},
                      {"seq": 4, "what": "pkmn_loop"}]}


def receipt_with_bench(title="crystal"):
    """The committed PHYSICAL receipt with its battle_bench run replaced by one shaped like its battle_faint run
    (a test forgery of the run's raw records, only to exercise M.qualified's acceptance)."""
    receipt = json_receipt(title)
    run = copy.deepcopy(receipt["runs"]["battle_faint"])
    for key in ("battle_hold", "battle_writes"):
        run.pop(key, None)
    run.update(bench_run(title), mode="battle_bench", attempt_id=run["attempt_id"] + "-bench",
               harness_write_scopes=["u2-battle-bench"])
    receipt["runs"]["battle_bench"] = run
    return receipt


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_battle_bench_is_checked_at_a_battle_frame_only_behind_its_receipt(title):
    owner = "gold" if title == "silver" else title
    c = frame(title)
    binder = c.binder(copy.deepcopy(receipt_with_bench(owner)))
    assert binder.covers(binder, "battle_bench") is True
    accepted, why = binder.check(binder, "battle_bench")
    assert accepted is True, why
    mode = next(r for r in c.data["primary"]["state_predicates"] if r["symbol"] == "wBattleMode")
    c.memory["System Bus", mode["address"]] = 0
    assert binder.check(binder, "battle_bench") == (False, "not in a battle")
    c.memory["System Bus", mode["address"]] = 1
    link = c.data["battle_hold"]["state_predicates"][0]
    c.memory["System Bus", link["address"]] = 1
    assert binder.check(binder, "battle_bench")[0] is False           # a link battle
    c.memory["System Bus", link["address"]] = 0
    c.wram_bank = 5                                                    # an animation's SVBK
    assert binder.check(binder, "battle_bench")[0] is False
    c.wram_bank = 1
    assert binder.check(binder, "battle_faint")[0] is False           # the hold kind still needs its hold
    without = json_receipt(owner)
    del without["runs"]["battle_bench"]                                # a receipt from before O-32
    plain = c.binder(without)
    assert plain.covers(plain, "battle_bench") is False and plain.check(plain, "battle_bench")[0] is False


def json_receipt(title):
    return json.loads((ROOT / f"tests/fixtures/gen2/receipts/{title}.write_window.json").read_text())


@pytest.mark.parametrize("fault", [None, "no_catch", "at_hold", "active_slot", "not_zero", "touched_battle",
                                   "overworld_written", "active_not_refused", "switched_in", "never_checked",
                                   "not_sent_back", "hook_never_fired"])
def test_battle_bench_problem_recomputes_the_controls(fault):
    run = bench_run()
    w = run["bench_write"]
    if fault == "no_catch":
        run["catch"]["party_after"] = 1
    elif fault == "at_hold":
        w["where"] = "battle_hold"
    elif fault == "active_slot":
        w["slot"] = 0
    elif fault == "not_zero":
        w["hp_after_hex"] = "0001"
    elif fault == "touched_battle":
        w["battle_hp_after_hex"] = "0000"
    elif fault == "overworld_written":
        run["refusals"]["overworld"]["after_hex"] = "000000"
    elif fault == "active_not_refused":
        run["refusals"]["active"]["refused"] = False
    elif fault == "switched_in":
        run["trace"].append({"seq": 5, "what": "switch"})
    elif fault == "never_checked":
        run["trace"][1]["party_mon"] = 0
    elif fault == "not_sent_back":
        run["trace"].pop()
    elif fault == "hook_never_fired":
        run["trace"] = [t for t in run["trace"] if t["what"] != "pkmn_loop"]
    c = Candidate()
    problem = c.module.battle_bench_problem(c.lua.table_from(run, recursive=True))
    assert (problem is None) == (fault is None), problem


def test_a_bench_receipt_without_the_battle_faint_run_refuses():
    receipt = receipt_with_bench()
    del receipt["runs"]["battle_faint"]
    c = frame()
    binder = c.binder(receipt)
    accepted, why = binder.check(binder, "party_hp")
    assert accepted is False and "needs the battle_faint run" in why


# ── the U2 gate's driver (lua/tests/gen2_write_windows.lua U.battle_bench_driver) ────────────────────────
def test_the_gate_driver_waits_for_the_write_then_tries_the_switch_once_and_runs():
    from tests.unit.test_gen2_write_safety import gate
    lua, U = gate()
    driver = U.battle_bench_driver(lua.table_from({}), lua.table_from({}))
    driver.phase = "battle"
    menu = {"kind": "battle_menu", "items": ["FIGHT", "PKMN", "PACK", "RUN"], "cursor": 1, "columns": 2}

    def step(ui, **kw):
        point = {"battle_mode": 1, "input_ready": True, "ui": ui, "bench_slot": 1, **kw}
        buttons, _ = driver.step(lua.table_from(point, recursive=True))
        pressed = sorted(k for k, v in (buttons or {}).items() if v)
        for _ in range(12):                                          # the 12-frame hold and its release
            driver.step(lua.table_from({"battle_mode": 1}, recursive=True))
        return pressed
    assert step(menu, bench_dead=False) == []                         # the harness writes first
    assert step(menu, bench_dead=True) == ["Right"]                   # PKMN, by position
    assert step(dict(menu, cursor=2), bench_dead=True) == ["A"]
    assert step({"kind": "battle_party"}, party_cursor=0, bench_dead=True) == ["Down"]
    assert step({"kind": "battle_party"}, party_cursor=1, bench_dead=True) == ["A"]
    mon_menu = {"kind": "battle_mon_menu", "items": ["SWITCH", "STATS", "CANCEL"], "cursor": 2, "columns": 1}
    assert step(mon_menu, bench_dead=True) == ["Up"]                  # not tried yet: never backs out here
    assert step(dict(mon_menu, cursor=1), bench_dead=True) == ["A"]
    assert step(dict(mon_menu, cursor=1), bench_dead=True) == ["A"]   # an early press was dropped: again
    assert step({"kind": "text"}, bench_dead=True, bench_checked=True) == ["A"]   # There's no will to battle!
    assert step(dict(mon_menu, cursor=1), bench_dead=True) == ["B"]   # the check ran: back out
    assert step({"kind": "battle_party"}, party_cursor=1, bench_dead=True) == ["B"]
    assert step(dict(menu, cursor=2), bench_dead=True) == ["Down"]    # then RUN
