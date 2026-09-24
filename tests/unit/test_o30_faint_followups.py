"""O-30 review follow-ups (docs/gen2/reviews/REVIEW_O30_INBATTLE_FAINT_2026-09-24.md).

Owner ruling O-30: every faint happens in battle; link battles are the only exception. These pin
the review's findings on the Gen 2 client and, where the gap is shared, on the Gen 1 client.
Harnesses are reused from tests/unit/test_gen2_client.py and tests/unit/test_gen1_client.py.
"""

import random

import pytest

from tests.unit import test_gen1_client as g1, test_gen2_client as g2
from tests.unit.test_gen2_client import (
    action,
    battle_hold,
    battle_hp,
    codec_key,
    end_battle,
    hold_ram,
    in_battle,
    mon,
)


def hold(world):
    """The battle hold inside a script (no overworld checkpoint): the model's one checkpoint stub stands
    for both holds, so it is open only for the synchronous hold, never for a frame."""
    world.checkpoint_ok = True
    battle_hold(world)
    world.checkpoint_ok = False


def kod(world):
    return [s for s in world.shown() if "KO'd" in s]


def start_battle(world, party, active=0):
    """The next battle starts with no overworld checkpoint in between (wBattleMode set, a turn committed)."""
    world.party(party)
    world.field("wBattleMode", 1)
    world.field("wCurBattleMon", active)
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonSpecies"), world.lua.table_from([party[active]["species"]]))
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonHP"), world.lua.table_from([0, 30]))
    world.emu.poke("System Bus", hold_ram(world, "wBattlePlayerAction"), world.lua.table_from([0]))


# ── MAJOR-1 (Gen 2): a death deferred before the battle lands at the first battle hold ──────────────────
@pytest.mark.parametrize("slot", [0, 1])
def test_gen2_a_death_deferred_before_the_battle_lands_at_the_first_hold(slot):
    """A gym leader's pre-battle text, a trainer walk-up or a wild transition (wBattleMode 0) refuse the
    checkpoint, so the command is deferred; the battle that follows must not run with the mon alive."""
    world = g2.World()
    party = [mon(), mon(species=172, dvs=0x3AAA)]
    in_battle(world, party)
    world.field("wBattleMode", 0)                                    # still the script, not the battle
    world.checkpoint_ok = False
    world.reply({"cmd": "force_faint", "key": codec_key(party[slot]), "nickname": "X"})
    world.frames(2)
    assert world.written() == []
    world.field("wBattleMode", 1)                                    # StartBattle
    hold(world)
    assert world.hp_of(slot) == (0, 0) and world.hp_of(1 - slot) == (30, 0)
    if slot == 0:
        assert battle_hp(world) == 0 and action(world) == 1
    else:
        assert battle_hp(world) == 30 and action(world) == 0
    n = len(world.written())
    hold(world)                                               # the quiet re-zero sees HP 0: nothing more
    assert len(world.written()) == n and kod(world) == ["show:!! X KO'd"]


# ── MAJOR-2 (Gen 2): the Battle Tower revives the dead mon between battles, with no checkpoint ─────────
@pytest.mark.parametrize("active_next", [0, 1])
def test_gen2_a_tower_revival_between_battles_is_re_zeroed_at_the_next_battle_hold(active_next):
    """Script_BattleRoomLoop (pokecrystal maps/BattleTowerBattleRoom.asm:23-63) chains up to 7 battles in
    one script: `special BattleTowerBattle` (:34) -> RunBattleTowerTrainer (engine/events/battle_tower/
    battle_tower.asm:214) runs HealParty (:228), StartBattle (:232), LoadPokemonData (:234, which copies
    wPokemonData back from sPokemonData, engine/menus/save.asm:756) and HealParty (:235) per battle, then
    the heal text (:46) and `sjump Script_BattleRoomLoop` (:63). The player never reaches an overworld
    checkpoint between battles, so the re-zero must land at the next battle's hold."""
    world = g2.World()
    lead = mon(species=1, dvs=0x3AAA)
    in_battle(world, [lead, mon()])
    world.checkpoint_ok = False                                      # the whole challenge is one script
    world.reply({"cmd": "force_faint", "key": codec_key(lead), "nickname": "BULBA"})
    world.frames(2)
    hold(world)                                               # tower battle 1: the death lands
    assert world.hp_of(0) == (0, 0)
    end_battle(world)
    party = [dict(lead, hp=30), mon()]                               # LoadPokemonData + HealParty
    start_battle(world, party, active=active_next)                   # tower battle 2
    hold(world)
    assert world.hp_of(0) == (0, 0)
    if active_next == 0:
        assert battle_hp(world) == 0 and action(world) == 1
    assert kod(world) == ["show:!! BULBA KO'd"]                      # the re-zero is quiet
    end_battle(world)
    start_battle(world, party, active=active_next)                   # tower battle 3: revived again
    hold(world)
    assert world.hp_of(0) == (0, 0) and kod(world) == ["show:!! BULBA KO'd"]


# ── MINOR-3 (Gen 2): the contest mask windows defer a hidden mon's death, never drop it ──────────────────
@pytest.mark.parametrize("window", ["drop_off", "results"])
def test_gen2_a_contest_hidden_death_in_a_mask_window_dies_at_contest_return_mons(window):
    """Entry: `special ContestDropOffMons` (maps/Route35NationalParkGate.asm:96/:140) masks the party two
    text boxes before `setflag ENGINE_BUG_CONTEST_TIMER` (:99). Exit: BugContestResultsScript clears the
    flag (C engine/events/std_scripts.asm:318) before `special ContestReturnMons` (:352)."""
    world = g2.World()
    lead, hidden = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, hidden])
    world.hello()
    world.frames(60)
    mask = g2.HOLDS[world.title]["contest_mask"]

    def flag(on):
        world.emu.poke("System Bus", mask["address"], world.lua.table_from([(1 << mask["bit"]) if on else 0]))

    world.party([lead])                                              # ContestDropOffMons: count 1
    world.checkpoint_ok = False                                      # a script is running in both windows
    if window == "results":
        flag(True)
        world.checkpoint_ok = True
        world.frames(3)                                              # the contest itself
        world.checkpoint_ok = False
        flag(False)                                                  # BugContestResultsScript: clearflag
    world.reply({"cmd": "force_faint", "key": codec_key(hidden), "nickname": "PICHU"})
    world.frames(2)
    if window == "drop_off":
        flag(True)                                                   # setflag, then the contest
        world.checkpoint_ok = True
        world.frames(3)
        world.checkpoint_ok = False
        flag(False)
    world.party([lead, hidden])                                      # ContestReturnMons
    world.checkpoint_ok = True
    world.frames(2)
    assert world.hp_of(1) == (0, 0) and world.hp_of(0) == (30, 0)
    assert not any("key not in party" in line for line in world.logs.values())


# ── NIT-6 (Gen 2): `commanded` does not outlive the battle ────────────────────────────────────────────
def test_gen2_commanded_is_cleared_at_battle_end():
    world = g2.World()
    active = mon()
    in_battle(world, [active, mon(species=172, dvs=0x3AAA)])
    world.reply({"cmd": "force_faint", "key": codec_key(active)})
    world.frames(2)
    battle_hold(world)
    assert world.client.commanded[codec_key(active)]                 # the echo is expected
    end_battle(world)                                                # it never came (binder refused it)
    assert list(world.client.commanded.keys()) == []


# ── NIT-7 (Gen 2): a hold write on a bench mon already at HP 0 is a no-op ────────────────────────────
def test_gen2_a_bench_death_on_a_mon_already_at_hp_0_writes_and_announces_nothing():
    world = g2.World()
    fainted = mon(species=172, dvs=0x3AAA, hp=0)
    in_battle(world, [mon(), fainted])
    world.reply({"cmd": "force_faint", "key": codec_key(fainted), "nickname": "PICHU"})
    world.frames(2)
    battle_hold(world)
    assert world.written() == [] and kod(world) == []
    assert len(world.client.deferred) == 0 and len(world.client.pending_battle_writes) == 0


# ── MAJOR-1 / MAJOR-2 mirror (Gen 1): the loop head lifts deferred deaths the same way ────────────────
@pytest.fixture
def world1():
    w = g1.World("red")
    rng = random.Random(1)
    w.seed_party([g1._mon(rng, 0x99, nick="BULBA"), g1._mon(rng, 0xB1, nick="PIDGEY")])
    w.set_map(0x0C)
    w.give_poke_ball()
    return w


def g1_kod(world):
    return [h for h in world.hud if h[0] == "show" and "KO'd" in h[1]]


@pytest.mark.parametrize("slot", [0, 1])
def test_gen1_a_death_deferred_before_the_battle_lands_at_the_first_loop_head(world1, slot):
    world1.connect()
    world1.step(60)
    world1.regs["PC"] = 0x1234                                       # a script window: no checkpoint
    key = g1.codec.key(world1.party()[slot])
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "X"})
    world1.step(2)
    assert world1.party()[slot]["hp"] > 0
    world1.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world1.fire("wild_begin")
    world1.step()
    world1.fire("battle_loop_head")
    assert world1.party()[slot]["hp"] == 0 and world1.party()[1 - slot]["hp"] > 0
    if slot == 0:
        assert world1.bus[world1.ram["wBattleMonHP"]] == 0 and world1.bus[world1.ram["wBattleMonHP"] + 1] == 0
    assert len(g1_kod(world1)) == 1 and len(world1.client.deferred) == 0


def test_gen1_a_quiet_re_zero_revived_before_the_next_battle_lands_at_its_loop_head(world1):
    world1.connect()
    world1.step(60)
    world1.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world1.fire("wild_begin")
    world1.step()
    key = g1.codec.key(world1.party()[1])
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world1.step()                                                    # the bench write lands on receipt
    world1.bus[world1.ram["wIsInBattle"]] = 0
    world1.fire("battle_end")
    world1.regs["PC"] = 0x1234                                       # no checkpoint before the next battle
    world1.step()
    hp = world1.ram["wPartyMons"] + 44 + 1
    world1.bus[hp], world1.bus[hp + 1] = 0, 7                        # revived
    world1.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
    world1.fire("wild_begin")
    world1.step()
    world1.fire("battle_loop_head")
    assert world1.party()[1]["hp"] == 0 and len(g1_kod(world1)) == 1
