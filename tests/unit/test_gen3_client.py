"""lua/gen3/client.lua (P4 C4-2b): the Gen 3 driver over lua/core, built by the PRODUCTION
lua/gen3/entry.lua and driven by tests/unit/gen3_world.py (fake GBA + fake server; every sent
line is schema-checked there).

First falsifiers:
  * an injected faint signal for a party mon yields exactly one schema-valid faint event with
    the right key;
  * no hello is sent before the checkpoint predicate holds;
  * a force_faint on the active battler holds, then lands on a simulated switch-out.
"""
from __future__ import annotations

import json
import re

import pytest

from tests.unit.gen3_world import ARTIFACTS, REPO, World, key_of, lua_to_py, mon_record

OT = 0x0000ABCD
A, B, C = 0x11111111, 0x22222222, 0x33333333
KA, KB, KC = key_of(A, OT), key_of(B, OT), key_of(C, OT)
FOE = mon_record(0x77777777, 0x1234, species=19, level=3)


def party(*pids, hp=20):
    return [mon_record(p, OT, species=4 + i, nickname=f"MON{i}", hp=hp) for i, p in enumerate(pids)]


def live(pack="gen3_frlg", title="firered", kind="clean", pids=(A, B), frames=60):
    """A connected client past its first validation: hello sent, writes enabled."""
    w = World(pack, title, kind)
    w.set_party(party(*pids))
    w.step_to(frames)
    assert w.client.writes_enabled is True
    return w


def write_reasons(w):
    return [str(r.reason) for r in lua_to_py_list(w.parts.writes.log)]


def lua_to_py_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


# ── falsifiers ────────────────────────────────────────────────────────────────────────────

def test_falsifier_a_faint_signal_yields_exactly_one_faint_with_the_right_key():
    w = live()
    w.set_party([mon_record(A, OT, species=4), mon_record(B, OT, species=5, hp=0)])
    w.fire("faint")
    w.step()
    (faint,) = w.events("faint")
    assert faint["key"] == KB and faint["area_id"] == "route_1"
    w.fire("faint")                                          # the same faint again: no repeat
    w.step()
    assert len(w.events("faint")) == 1


def test_falsifier_no_hello_out_of_battle_before_the_checkpoint_predicate_holds():
    w = World()
    w.set_party(party(A))
    w.break_checkpoint()
    w.step(200)
    assert w.events("hello") == [] and w.sent == []
    w.overworld_safe()
    w.step()
    assert len(w.events("hello")) == 1


def test_in_battle_hello_does_not_wait_for_the_checkpoint():
    """PLAN's rule is "checkpoint OR battle" (Gen 1 parity): a reconnect mid-battle hellos."""
    w = World()
    w.set_party(party(A))
    w.enter_battle([FOE], fire=False)                         # the in_battle clause fails the checkpoint
    w.step()
    (hello,) = w.events("hello")
    assert hello["in_battle"] is True


def test_falsifier_an_active_battler_force_faint_holds_then_lands_on_switch_out():
    w = live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KA)
    w.step(5)
    assert w.party_hp(0) == 20 and w.writes == []            # held: the active battler
    assert w.client.battle_pending_count(w.client) == 1
    w.set_active([1])                                         # switched out
    w.step()
    assert w.party_hp(0) == 0 and w.client.battle_pending_count(w.client) == 0
    assert write_reasons(w) == ["battle_faint"]


# ── M1: hello and tick schema-valid on both packs ─────────────────────────────────────────

@pytest.mark.parametrize("pack,title,kind", ARTIFACTS)
def test_m1_hello_and_tick_are_schema_valid_on_every_artifact(pack, title, kind):
    w = World(pack, title, kind)
    w.set_party(party(A, B))
    w.set_balls(5)
    w.step_to(90)
    (hello,) = w.events("hello")
    assert hello["rom_type"] == {"firered": "firered", "leafgreen": "leafgreen",
                                 "radical_red": "firered_rr"}[title]
    assert hello["foundation"] == pack and hello["artifact_kind"] == kind
    assert [m["key"] for m in hello["party"]] == [KA, KB]
    assert all(len(m["blob_hex"]) == 200 for m in hello["party"])
    ticks = w.events("tick")
    assert len(ticks) == 3 and ticks[-1]["ball_count"] == 5 and ticks[-1]["has_pokeballs"] is True
    # empty lists go on the wire as arrays (conformance item 1, docs/protocol.md A19)
    assert '"enemy_party":[]' in [line for line in w.lines if '"tick"' in line][0].replace(" ", "")


def test_hello_carries_the_trainer_badges_and_seeded_boxes_on_frlg():
    w = World()
    w.set_party(party(A))
    w.set_badges(0b101)
    w.set_box(0, 3, mon_record(C, OT, species=7))
    w.step()
    (hello,) = w.events("hello")
    assert hello["ot_id"] == OT and hello["trainer_name"] == "RED" and hello["badges"] == 5
    assert [(e["box"], e["slot"], e["key"]) for e in hello["pc_boxes"]] == [(0, 3, KC)]


def test_rr_hello_falls_back_without_the_trainer_read():
    w = World("gen3_rr", "radical_red")
    w.set_party(party(A))
    w.step()
    (hello,) = w.events("hello")
    assert "ot_id" not in hello and "trainer_name" not in hello and hello["party"][0]["key"] == KA


def test_a_pre_game_save_sends_no_hello():
    w = World()
    w.set_trainer(0)
    w.step(100)
    assert w.events("hello") == []


# ── the reducer ─────────────────────────────────────────────────────────────────────────

def test_an_enemy_faint_reports_nothing():
    w = live()
    w.enter_battle([FOE])
    w.fire("faint")
    w.step()
    assert w.events("faint") == []


def test_a_caught_mon_is_one_capture_not_a_gift():
    w = live()
    w.set_balls(5)
    w.step(30)                                            # the tick latches has_pokeballs
    w.enter_battle([FOE])
    w.set_party(party(A, B, C))
    w.fire("capture_wild")
    w.fire("mon_given")
    w.step()
    (cap,) = w.events("capture")
    assert cap["key"] == KC and cap["area_id"] == "route_1" and "gift" not in cap
    w.leave_battle(outcome=7)
    w.step()
    assert w.events("no_catch") == []


def test_a_catch_the_client_could_not_attribute_never_dead_zones_the_area():
    w = live()
    w.set_balls(5)
    w.step(30)
    w.enter_battle([FOE])
    w.step(30)
    w.fire("capture_wild")                                     # caught, but no new key is readable
    w.step()
    w.leave_battle(outcome=4)
    w.step()
    assert w.events("capture") == [] and w.events("no_catch") == []


def test_a_gift_is_a_capture_with_gift_true():
    w = live()
    w.set_party(party(A, B, C))
    w.fire("mon_given")
    w.step()
    (cap,) = w.events("capture")
    assert cap["key"] == KC and cap["gift"] is True


FULL_STATS = {"level": 5, "maxHP": 20, "attack": 11, "defense": 12, "speed": 13, "spAtk": 14,
              "spDef": 15, "pp1": 35, "pp2": 30, "pp3": 0, "pp4": 0}


def test_a_catch_with_a_full_party_is_a_boxed_capture():
    w = live(pids=(A, B))
    w.enter_battle([mon_record(C, OT, species=19)])            # the wild mon, as caught
    w.set_box(1, 0, mon_record(C, OT, species=19))
    w.fire("capture_wild")
    w.fire("pc_move")
    w.step()
    (cap,) = w.events("capture")
    assert cap["key"] == KC and cap["in_box"] is True and cap["species_id"] == 19
    # MAJOR 4 (C4-2d): the complete stats the server caches and boxes.lua needs on withdraw
    assert cap["stats"] == FULL_STATS and cap["level"] == 5 and cap["maxHP"] == 20


@pytest.mark.parametrize("pack,title", [("gen3_frlg", "firered"), ("gen3_rr", "radical_red")])
def test_major4_party_to_box_carries_the_complete_stats_on_both_packs(pack, title):
    w = live(pack, title, pids=(A, B))
    w.set_party(party(A))
    w.set_box(0, 0, mon_record(B, OT, species=5))
    w.fire("pc_deposit")
    w.step()
    assert w.events("party_to_box")[0]["stats"] == FULL_STATS


def test_a_failed_wild_encounter_sends_one_no_catch():
    w = live()
    w.set_balls(3)
    w.step(30)
    w.enter_battle([FOE])
    w.step(30)                                                # a tick notes the foe
    w.leave_battle(outcome=4)
    w.step()
    (nc,) = w.events("no_catch")
    assert nc == {**nc, "area_id": "route_1", "species_id": 19, "level": 3}
    w.step(31)
    assert len(w.events("safe")) == 1


def test_a_trainer_battle_sends_trainer_battle_start_once_and_no_no_catch():
    w = live()
    w.set_balls(3)
    w.enter_battle([FOE], trainer_id=42)
    w.step(61)
    assert [e["trainer_id"] for e in w.events("trainer_battle_start")] == [42]
    tick = [t for t in w.events("tick") if t["in_battle"]][-1]
    assert tick["is_trainer_battle"] is True and tick["trainer_id"] == 42
    assert tick["enemy_party"][0]["species_id"] == 19
    w.leave_battle()
    w.step()
    assert w.events("no_catch") == []


def test_whiteout_is_sent_once_per_whiteout():
    w = live()
    w.fire("whiteout")
    w.fire("whiteout")
    w.step()
    assert len(w.events("whiteout")) == 1
    w.fire("whiteout")
    w.step()
    assert len(w.events("whiteout")) == 2


def test_a_pc_deposit_and_withdraw_are_party_to_box_and_box_to_party():
    w = live(pids=(A, B))
    w.set_party(party(A))
    w.set_box(0, 0, mon_record(B, OT, species=5))
    w.fire("pc_deposit")
    w.step()
    (dep,) = w.events("party_to_box")
    assert dep["key"] == KB and dep["stats"] == FULL_STATS
    w.set_box(0, 0, None)
    w.set_party(party(A, B))
    w.fire("pc_withdraw")
    w.step()
    assert [e["key"] for e in w.events("box_to_party")] == [KB]


def test_a_mon_picked_up_in_the_pc_is_reported_only_when_placed():
    w = live(pids=(A, B))
    w.set_party(party(A))
    w.fire("pc_withdraw")                                      # carried in the cursor
    w.step()
    assert w.events("party_to_box") == []
    w.set_box(2, 5, mon_record(B, OT, species=5))
    w.fire("pc_box_place")
    w.step()
    assert [e["key"] for e in w.events("party_to_box")] == [KB]


def test_map_load_sends_area_enter():
    w = live()
    w.set_location(1, 0)
    w.fire("map_load")
    w.step()
    (area,) = w.events("area_enter")
    assert area["area_id"] == "viridian_forest"


def test_the_save_site_flushes_the_battery():
    w = live()
    w.fire("save")
    w.step()
    assert w.saveram_calls == 1


def test_a_borrowed_party_freezes_the_diff_and_the_tick_party():
    w = live(pids=(A, B))
    w.enter_battle([FOE])
    w.set_party([mon_record(0x99999999, 0x5555, hp=0)])        # a partner's party in RAM
    w.fire("faint")
    w.step(30)
    assert w.events("faint") == []
    assert "party" not in [t for t in w.events("tick") if t["in_battle"]][-1]
    w.set_party(party(A, B))
    w.step(30)
    assert "party" in w.events("tick")[-1]


def test_open_kind_trade_done_reports_a_key_change_with_the_npc_trade_reason():
    w = live(pids=(A, B))
    w.fire("trade_begin")
    w.step()
    w.set_party([mon_record(A, OT), mon_record(C, 0x9999, species=122)])
    w.fire("trade_done")
    w.step()
    (kc,) = w.events("key_change")
    assert kc["old_key"] == KB and kc["new_key"] == key_of(C, 0x9999) and kc["reason"] == "npc_trade"


# ── in-battle writes (owner ruling 2026-09-23) ────────────────────────────────────────────

def test_a_bench_faint_lands_immediately_and_its_faint_is_not_reported():
    w = live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KB)
    w.step()
    assert w.party_hp(1) == 0 and write_reasons(w) == ["battle_faint"]
    assert set(w.battle_checks) == {"battle_faint"}      # pre-check, arm, per-write re-check
    w.step(30)                                            # a tick sees hp 0 before the engine's faint
    w.fire("faint")
    w.step()
    assert w.events("faint") == []                            # commanded: suppressed
    assert any(h[0] == "show" and "KO'd" in h[1] for h in w.hud)


def test_a_refused_battle_faint_check_holds_and_writes_nothing():
    w = live()
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KB)
    w.step(3)
    assert w.writes == [] and w.client.battle_pending_count(w.client) == 1
    held = lua_to_py_list(w.client.battle_pending)[0]
    assert "forbidden state" in str(held.why)                # the REAL battle clause set refused
    w.battle_ok = True
    w.step()
    assert w.party_hp(1) == 0 and w.client.battle_pending_count(w.client) == 0


def test_doubles_battler_two_is_active_and_held():
    w = live(pids=(A, B, C))
    w.battle_ok = True
    w.enter_battle([FOE, FOE], doubles=True, active=(0, 2))
    w.command(cmd="force_faint", key=KC)
    w.step(3)
    assert w.party_hp(2) == 20 and w.client.battle_pending_count(w.client) == 1


def test_a_held_battler_at_battle_end_lands_at_the_overworld_checkpoint():
    w = live()
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KA)
    w.step(3)
    w.leave_battle()
    w.step()
    assert w.client.battle_pending_count(w.client) == 0
    w.step(2)
    assert w.party_hp(0) == 0 and write_reasons(w) == ["overworld"]


def test_frlg_force_explode_on_the_active_battler_is_a_held_faint():
    w = live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_explode", key=KA)
    w.step(3)
    assert w.writes == [] and w.client.battle_pending_count(w.client) == 1


def _explode_world():
    w = live("gen3_rr", "radical_red")
    w.battle_ok = True
    w.poke_int(w.ram["BATTLE_STRUCT_PTR_ADDR"], 0x02020000, 4)
    w.enter_battle([FOE], active=(0,))
    base = w.ram["BATTLE_MONS_ADDR"]
    w.poke_int(base + 0x28, 20, 2)                              # battler 0 hp
    return w, base


def test_rr_force_explode_commits_the_menu_skip_under_battle_commit():
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    assert set(write_reasons(w)) == {"battle_commit"}
    assert w._read(base + 0x0C, 2) == 153 and w._read(base + 0x24, 1) == 5
    assert w._read(w.ram["CHOSEN_ACTION_ADDR"], 1) == 0
    assert w._read(w.ram["CHOSEN_MOVE_ADDR"], 2) == 153
    assert w._read(w.ram["BATTLE_COMM_ADDR"], 1) == 3
    assert w._read(0x02020000 + w.d["BATTLE_STRUCT_MOVE_TARGET_OFF"], 1) == 1
    held = lua_to_py_list(w.client.battle_pending)[0]
    assert str(held.why) == "explosion committed"


def test_rr_explosion_that_lands_settles_without_a_faint_report():
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step(30)                                                  # ticks see the battler alive meanwhile
    w.poke_int(base + 0x24, 4, 1)                               # PP dropped: executed
    w.poke_int(base + 0x28, 0, 2)                               # the user fainted
    w.set_party([mon_record(A, OT, hp=0), mon_record(B, OT, species=5)])
    w.fire("faint")
    w.step()
    assert w.client.battle_pending_count(w.client) == 0 and w.events("faint") == []


def _hp_writes(w):
    hp = {w.party_base() + slot * 100 + 0x56 + i for slot in range(6) for i in range(2)}
    hp |= {w.ram["BATTLE_MONS_ADDR"] + b * 0x58 + 0x28 + i for b in range(4) for i in range(2)}
    return [x for x in w.writes if x[0] in hp]


def test_the_full_commit_lands_through_the_real_writes_and_safety_with_the_guard_last():
    """C4-2e item 2: writes.lua re-checks the REAL battle_commit clause set before every byte;
    gBattleCommunication[battler] is that set's battle_comm_0 clause AND its guard, so it must
    be the plan's last write or the rest is refused mid-plan."""
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    comm = w.ram["BATTLE_COMM_ADDR"]
    commit = [x for x in w.writes if x[1] is not None]
    addrs = [x[0] for x in commit]
    assert addrs[-1] == comm and addrs.count(comm) == 1           # the committing byte, last
    assert len(commit) == 4 * 2 + 4 + 1 + 2 + 1 + 1 + 1           # moves, PP, action, move, pos, target, comm
    assert sum(int(r.len) for r in lua_to_py_list(w.parts.writes.log)) == len(commit)


def test_explode_control_a_move_locked_battler_is_held_and_nothing_is_written():
    w, base = _explode_world()
    w.poke_int(w.ram["LOCKED_MOVES_ADDR"], 37, 2)              # Thrash in progress
    w.command(cmd="force_explode", key=KA)
    w.step(5)
    assert w.writes == [] and "move locked" in str(lua_to_py_list(w.client.battle_pending)[0].why)


@pytest.mark.parametrize("model", ["sleep", "flinch"])
def test_explode_control_sleep_or_flinch_rearms_the_commit_and_never_writes_hp(model):
    """The move never executes (PP stays 5) and the turn ends: the commit is re-armed under
    battle_commit, the entry stays held; no HP byte is ever written. Liveness NOT PHYSICAL."""
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    for _ in range(3):                                         # three turns asleep / flinching
        w.poke_int(w.ram["BATTLE_COMM_ADDR"], 1, 1)            # the next turn's input wait
        w.step()
        assert w._read(w.ram["BATTLE_COMM_ADDR"], 1) == 3
    assert _hp_writes(w) == [] and set(write_reasons(w)) == {"battle_commit"}
    assert w.client.battle_pending_count(w.client) == 1


def test_rr_explosion_that_the_battler_survives_degrades_to_a_held_faint():
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    w.poke_int(base + 0x24, 4, 1)                               # executed
    w.poke_int(w.ram["BATTLE_COMM_ADDR"], 1, 1)                 # a new turn's input wait, hp > 0
    n = len(w.writes)
    w.step(3)
    held = lua_to_py_list(w.client.battle_pending)[0]
    assert "explosion failed" in str(held.why) and len(w.writes) == n
    assert _hp_writes(w) == []                                  # Damp: never an active-battler HP write


def test_rr_explosion_commit_is_rewritten_when_the_engine_resets_it():
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    w.poke_int(w.ram["BATTLE_COMM_ADDR"], 1, 1)                 # turn start reset, PP untouched
    w.step()
    assert w._read(w.ram["BATTLE_COMM_ADDR"], 1) == 3


# ── command seams ───────────────────────────────────────────────────────────────────────

def test_apply_trade_on_frlg_writes_nothing_and_replies_nothing():
    w = live()
    n = len(w.sent)
    w.command(cmd="apply_trade", slot=0, blob_hex="00" * 100, old_key=KA, token="t")
    w.step(3)
    assert w.writes == [] and [m["event"] for m in w.sent[n:] if m["event"] != "tick"] == []


@pytest.mark.parametrize("name,extra,event,field,value", [
    ("show_choices", {"options": ["a"], "text": "?"}, "menu_result", "choice", 127),
    ("show_menu", {"text": "?"}, "menu_result", "choice", 0),
    ("choose_mon", {}, "mon_chosen", "slot", 7),
])
def test_prompts_without_a_native_part_get_the_cancel_sentinels(name, extra, event, field, value):
    w = live("gen3_rr", "radical_red")
    w.command(cmd=name, token="tk", **extra)
    w.step()
    (reply,) = w.events(event)
    assert reply["token"] == "tk" and reply[field] == value


def test_rival_swap_without_the_companion_refuses_like_the_old_client():
    w = live("gen3_rr", "radical_red")
    w.command(cmd="replace_rival_team", trainer_id=5, n=1, blobs_hex=["00" * 100])
    w.step()
    assert w.events("rival_team_replaced")[-1]["error"] == "not_in_battle"
    w.enter_battle([FOE], trainer_id=5)
    w.command(cmd="replace_rival_team", trainer_id=5, n=1, blobs_hex=["00" * 100])
    w.step()
    assert w.events("rival_team_replaced")[-1]["error"] == "patch_required"
    assert w.writes == []


def test_a_native_part_takes_the_menu_seam():
    seen = []
    w = World("gen3_rr", "radical_red", "companion",
              native=lambda L: L.table(show_menu=lambda _self, cmd: seen.append(str(cmd.token)) or True))
    w.set_party(party(A))
    w.step_to(60)
    w.command(cmd="show_menu", token="tk", text="?")
    w.step()
    assert seen == ["tk"] and w.events("menu_result") == []


# ── deferred checkpoint executors ─────────────────────────────────────────────────────────

class FakeBoxes:
    """A box mover with boxes.lua's contract (true | nil, reason). boxes.lua itself is the C4-3
    card's (tests/unit/test_gen3_boxes.py) and today needs rom.PP_UP_GET_MASK_ADDR, which no
    pack carries yet, so the executor wiring is proven against this double."""

    def __init__(self, results=None, effect=None):
        self.calls, self.results, self.effect = [], list(results or []), effect

    def table(self, L):
        def call(name):
            def fn(_self, key, *_rest):
                self.calls.append((name, str(key)))
                if self.effect:
                    self.effect(name, str(key))
                return self.results.pop(0) if self.results else (True, None)
            return fn
        return L.table(deposit=call("deposit"), withdraw=call("withdraw"),
                       memorialize=call("memorialize"), memorial_box=13)


def boxed_live(results=None, effect=None):
    fake = FakeBoxes(results, effect)
    w = World("gen3_frlg", "firered", boxes=fake.table)
    w.set_party(party(A, B))
    w.step_to(60)
    return w, fake


def test_a_deferred_box_mon_deposits_at_the_checkpoint_and_acks_stats_after():
    w, fake = boxed_live()
    w.command(cmd="box_mon", key=KB)
    w.step()
    assert fake.calls == [("deposit", KB)]
    (cache,) = w.events("stats_cache")
    assert cache["key"] == KB and cache["stats"]["level"] == 5 and cache["stats"]["spAtk"] == 14
    assert w.events("box_mon_failed") == []


def test_a_refused_deferred_deposit_is_box_mon_failed_without_stats_cache():
    w, _ = boxed_live([(None, "last party mon")])
    w.command(cmd="box_mon", key=KB)
    w.step()
    assert w.events("stats_cache") == []
    assert w.events("box_mon_failed")[0]["reason"] == "last party mon"


def test_memorialize_done_names_the_memorial_box():
    w, fake = boxed_live()
    w.command(cmd="memorialize", key=KB)
    w.step()
    (done,) = w.events("memorialize_done")
    assert done["key"] == KB and done["box"] == 13 and fake.calls == [("memorialize", KB)]


def test_our_own_deposit_is_not_reported_as_the_players():
    world = {}

    def move(name, key):                                       # the mover's effect on the save
        if name == "deposit":
            world["w"].set_party(party(A))
            world["w"].set_box(0, 0, mon_record(B, OT, species=5))
    w, _ = boxed_live(effect=move)
    world["w"] = w
    w.command(cmd="box_mon", key=KB)
    w.step()
    w.fire("pc_deposit")                                       # any later PC signal
    w.step()
    assert w.events("party_to_box") == []                      # rescan re-baselined after the move


def test_every_byte_written_went_through_the_armed_sink():
    w = live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.command(cmd="force_faint", key=KB)
    w.step()
    logged = sum(int(r.len) for r in lua_to_py_list(w.parts.writes.log))
    assert logged == len(w.writes) > 0


# ── C4-2d review findings ─────────────────────────────────────────────────────────────────

RR_PACK = json.loads((REPO / "data" / "games" / "gen3_rr" / "profile.json").read_text(encoding="utf-8"))
NATIVE = RR_PACK["native"]




def attach_real_native(w, present=True):
    """The REAL lua/gen3/native.lua instance Entry built for this RR companion World (the one
    the client, Safety's native_idle and the write policy share); present = its beacon is up."""
    assert w.parts.native is not None, "Entry builds native for the RR companion artifact"
    if present:
        w.poke_int(NATIVE["BASE"], NATIVE["SIG"], 4)
        w.poke_int(NATIVE["BASE"] + 4, NATIVE["ABI"], 2)
    return w.parts.native


def native_writes(w):
    lo, hi = NATIVE["BASE"], NATIVE["BASE"] + 0x200
    return [x for x in w.writes if lo <= x[0] < hi]


def rr_live():
    w = live("gen3_rr", "radical_red", "companion")
    w.battle_ok = True                                         # the fake predicate admits "native"
    return w


def test_blocker_control_an_eligible_session_posts_the_native_sound():
    w = rr_live()
    attach_real_native(w)
    w.command(cmd="play_sound", sound=25)
    w.step(3)
    assert native_writes(w), "positive control: the real native.lua must post while eligible"
    # published, not merely begun: the opcode is the post's last byte
    assert w._read(NATIVE["BASE"] + 6, 2) == NATIVE["OP_PLAY_SE"]


def test_blocker_a_paused_session_posts_nothing_through_the_real_native_part():
    w = rr_live()
    attach_real_native(w)
    w.command(cmd="play_sound", sound=25)
    w.step()                                                  # received: queued in native.lua
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.step(20)
    assert native_writes(w) == [] and w.writes == []
    w.client.writes_enabled, w.client.gate_revoked = True, False
    w.step(2)
    assert native_writes(w), "the queued job survives the pause and posts once eligible"


def test_blocker_a_paused_session_stages_no_rival_swap():
    w = rr_live()
    attach_real_native(w)
    w.enter_battle([FOE], trainer_id=5)
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.command(cmd="replace_rival_team", trainer_id=5, n=1, blobs_hex=["00" * 100])
    w.step(5)
    assert w.writes == [] and w.events("rival_team_replaced") == []
    w.client.writes_enabled, w.client.gate_revoked = True, False
    w.step(3)
    assert native_writes(w) == [], "nothing was queued while paused, so nothing stale posts later"


def test_minor1_a_native_owned_prompt_is_answered_exactly_once():
    w = rr_live()
    attach_real_native(w, present=False)                       # native refuses: its callback answers
    w.command(cmd="show_menu", token="tk", text="?")
    w.step()
    assert [r["token"] for r in w.events("menu_result")] == ["tk"]


def test_major1_a_capture_before_hello_is_sent_after_it():
    w = World()
    w.set_party(party(A))
    w.break_checkpoint()                                       # no hello yet (out of battle)
    w.step()
    w.set_party(party(A, B))
    w.fire("mon_given")
    w.step(3)
    assert w.sent == []
    w.overworld_safe()
    w.step()
    assert w.names()[:2] == ["hello", "capture"]
    # R4 (C4-2e): exactly the acquired mon -- A was there before the first frame
    assert [c["key"] for c in w.events("capture")] == [KB]


def test_r4_a_party_loaded_without_a_signal_is_never_an_acquisition():
    """The save is live at the main menu with an empty party; CONTINUE brings A and B in with
    no engine acquisition signal; a later gift reports only the gift."""
    w = World()
    w.step(2)                                                  # live, empty party: the baseline
    w.set_party(party(A, B))                                   # CONTINUE, no signal
    w.step(3)
    w.set_party(party(A, B, C))
    w.fire("mon_given")
    w.step()
    assert [c["key"] for c in w.events("capture")] == [KC]


def test_r4_a_gift_straddling_a_frame_end_is_still_an_acquisition():
    """The party grows at a frame end whose return hook fires on the NEXT frame: the quiet
    frame must not absorb the new key before the signal settles it."""
    w = live(pids=(A,))
    w.set_party(party(A, B))
    w.step()                                                   # party written, hook not yet fired
    w.fire("mon_given")
    w.step()
    assert [c["key"] for c in w.events("capture")] == [KB]


def test_r1_a_mover_that_throws_on_byte_two_is_uncertain_with_the_production_counter():
    """The client's own write_count over the real writes.lua: byte 1 lands, byte 2 throws."""
    w, _ = boxed_live()
    L, landed = w.lua, []
    real = w.io.write_u8

    def sink(addr, value, *rest):
        landed.append(int(addr))
        if len(landed) == 2:
            raise RuntimeError("sink died on byte 2")
        return real(addr, value, *rest)
    w.io.write_u8 = sink
    w.client.deferred.exec.deposit = L.eval(
        "function(w) return function(key, hint) w:arm('overworld', function() return true end); "
        "w:write_bytes(0x02030000, {1, 2}); return true end end")(w.parts.writes)
    w.command(cmd="box_mon", key=KB)
    w.step(5)
    assert w._read(0x02030000, 1) == 1 and len(landed) == 2      # RAM changed; never retried
    (fail,) = w.events("box_mon_failed")
    assert fail["reason"].startswith("uncertain: partial write")


def _raise_alias(w, old_key, new_key):
    """What the reducer does when it sends key_change old->new: the alias over the record."""
    party = w.client.driver.read_party()
    w.client.identity.begin_alias(w.client.identity, old_key, new_key, party[1], party)


def test_r3_a_replayed_ack_lands_the_queued_faint_on_the_renamed_mon():
    """faint(A) queued, the cartridge's A became B and THIS client raised the A->B alias; the
    server's ACK is a replay (migrated:false). The faint lands on B through the retained alias."""
    w = live(pids=(A, C))
    w.break_checkpoint()
    w.command(cmd="force_faint", key=KA)
    w.step()
    w.set_party([mon_record(B, OT, species=4), mon_record(C, OT, species=5)])
    _raise_alias(w, KA, KB)
    w.command(cmd="key_change_ack", old_key=KA, new_key=KB, migrated=False)
    w.step()
    w.overworld_safe()
    w.step(2)
    assert w.party_hp(0) == 0


def test_r3_without_our_alias_a_replayed_ack_never_retargets_the_faint():
    """C4-2g: the same frames with NO alias (the B in slot 0 is unrelated to A): the faint stays
    on A and is dropped by name at the checkpoint; B keeps its HP."""
    w = live(pids=(A, C))
    w.break_checkpoint()
    w.command(cmd="force_faint", key=KA)
    w.step()
    w.set_party([mon_record(B, OT, species=4), mon_record(C, OT, species=5)])
    w.command(cmd="key_change_ack", old_key=KA, new_key=KB, migrated=False)
    w.step()
    w.overworld_safe()
    w.step(2)
    assert w.party_hp(0) == 20
    assert any("force_faint dropped at the checkpoint" in line and KA in line for line in w.logs)


def test_r4_codex1_a_capture_in_the_first_hello_frame_is_reported_after_the_hello():
    """C4-2g (Codex REV3): A present, checkpoint unsafe, a quiet frame baselines A; then B is
    added, mon_given fires and the checkpoint turns safe before the next step: that one frame
    sends the hello AND settles B. Exactly [hello, capture(B)]."""
    w = World()
    w.set_party(party(A))
    w.break_checkpoint()
    w.step()                                                   # the quiet baseline of A
    w.set_party(party(A, B))
    w.fire("mon_given")
    w.overworld_safe()
    w.step()
    assert w.names()[:2] == ["hello", "capture"]
    assert [c["key"] for c in w.events("capture")] == [KB]


def test_r4_codex2_a_reconnect_between_the_party_write_and_its_hook_still_captures():
    """C4-2g (Codex REV3): B's party write lands while disconnected; the connection returns
    and the hello is built on the frame whose mon_given hook fires. Exactly one capture(B)."""
    w = live(pids=(A,))
    w.connected = False
    w.step()
    w.set_party(party(A, B))                                    # written, hook not yet fired
    w.step()
    w.connected = True
    w.fire("mon_given")
    n = len(w.sent)
    w.step()
    assert [m["event"] for m in w.sent[n:]][:2] == ["hello", "capture"]
    assert [c["key"] for c in w.events("capture")] == [KB]


def test_rev5_r4_a_mon_added_one_frame_after_the_first_hello_is_still_captured():
    """Codex REV5: A -> the first hello step (its baseline) -> add B -> one quiet step ->
    mon_given -> step. The quiet interval started at hello's count, so B is not absorbed."""
    w = World()
    w.set_party(party(A))
    w.step()                                                   # the first hello baselines A
    assert w.names() == ["hello"]
    w.set_party(party(A, B))
    w.step()                                                   # quiet: B's hook is not in yet
    w.fire("mon_given")
    w.step()
    assert [c["key"] for c in w.events("capture")] == [KB]


def test_rev5_r4_a_count_change_inside_the_quiet_interval_restarts_it():
    w = live(pids=(A,))
    w.set_party(party(A, B))
    w.step()                                                   # a count change: interval starts
    w.set_party(party(A, B, C))
    w.step()                                                   # changed again before it was due
    w.fire("mon_given")
    w.step()
    assert [c["key"] for c in w.events("capture")] == [KB, KC]


def test_r4_control_the_first_hello_still_baselines_a_party_it_has_never_seen():
    """The first-ever baseline is still taken by hello when no quiet frame preceded it: a
    later acquisition reports only the new mon."""
    w = World()
    w.set_party(party(A, B))
    w.step()                                                   # hello on the very first frame
    w.set_party(party(A, B, C))
    w.fire("mon_given")
    w.step()
    assert [c["key"] for c in w.events("capture")] == [KC]


def test_major1_a_reconnect_hello_has_no_area_enter_before_it():
    w = live()
    w.connected = False
    w.step()
    w.set_location(1, 0)                                       # moved while offline
    w.connected = True
    n = len(w.sent)
    w.step()
    assert [m["event"] for m in w.sent[n:]][:1] == ["hello"]
    assert w.events("area_enter") == [] and w.sent[n]["area_id"] == "viridian_forest"


def test_major2_a_mid_battle_reconnect_with_a_borrowed_party_hellos_an_empty_party():
    w = live()
    w.enter_battle([FOE], active=(0,))
    w.step()
    w.set_party([mon_record(0x99999999, 0x5555, species=7)])
    w.fire("map_load")
    w.step()
    w.connected = False
    w.step()
    w.connected = True
    w.step()
    assert w.events("hello")[-1]["party"] == []


def test_major3_a_force_faint_during_a_borrowed_party_is_held_and_lands_after_restore():
    w = live()
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.step()
    w.set_party([mon_record(0x99999999, 0x5555, species=7)])  # the partner's party
    w.command(cmd="force_faint", key=KB)
    w.step(3)
    assert w.client.battle_pending_count(w.client) == 1 and w.writes == []
    w.set_party(party(A, B))                                   # restored
    w.step()
    assert w.party_hp(1) == 0 and w.client.battle_pending_count(w.client) == 0


def _checkpoint_sound(w):
    return json.loads((REPO / "data" / "games" / w.pack / "write_checkpoint.json")
                      .read_text(encoding="utf-8"))[w.title]["sound"]


TRACK0 = 0x03006300


def _m4a_world(title="firered", ident_ok=True, track=TRACK0):
    """An m4a SE1 player at the pack's own gMPlayInfo_SE1 (FR/LG sound block), its track in
    IWRAM, and SE 26's song header in ROM. The REAL writes.lua + safety.lua decide."""
    w = live("gen3_frlg", title)
    snd = _checkpoint_sound(w)
    player = snd["player_se1"]["address"]
    w.poke_int(player + snd["ident_off"], snd["ident_magic"] if ident_ok else 0, 4)
    w.poke_int(player + snd["tracks_off"], track, 4)
    hdr = w.profile["rom"]["SE_SONG_HEADERS"]["26"] - 0x08000000
    for i, b in enumerate([1, 0, 5, 0, 0, 0, 0, 0, 0x10, 0x20, 0x30, 0x08]):
        w.rom[hdr + i] = b
    return w, snd, player


def _sound_writes(w):
    return [r for r in lua_to_py_list(w.parts.writes.log) if str(r.reason) == "sound"]


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_sound_on_frlg_arms_sound_and_writes_exactly_the_pack_fields(title):
    """POSITIVE (C4-2f): through the real writes.lua ("sound" reason) and the real sound clause
    set, a play_sound lands every byte inside a field of the pack's sound block, logged."""
    w, snd, player = _m4a_world(title)
    w.command(cmd="play_sound", sound=26)
    w.step()
    logged = _sound_writes(w)
    assert logged and sum(int(r.len) for r in logged) == len(w.writes)   # every byte logged
    fields = [((player if f["on"] == "player" else TRACK0) + f["offset"], f["size"]) for f in snd["fields"]]
    for addr, _value, _frame in w.writes:
        assert any(base <= addr < base + size for base, size in fields), hex(addr)
    hdr = w.profile["rom"]["SE_SONG_HEADERS"]["26"]
    assert w._read(player + 0, 4) == hdr                                   # songHeader
    assert w._read(player + 4, 4) == 1                                     # status: 1 track
    assert w._read(TRACK0 + 0, 1) == 0xC0                                  # flags EXIST|START
    assert w._read(TRACK0 + 64, 4) == 0x08302010                           # cmdPtr from the header
    assert w._read(player + snd["ident_off"], 4) == snd["ident_magic"]     # never locked
    assert int(logged[-1].address) == player + 4                           # status published last


def test_sound_with_an_uninitialised_driver_writes_nothing():
    """NEGATIVE: the real sound_player_ready clause fails (ident is not the m4a magic)."""
    w, _snd, _player = _m4a_world(ident_ok=False)
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == []
    assert any("sound refused" in line and "not initialised" in line for line in w.logs)


def test_sound_with_a_track_outside_iwram_writes_nothing():
    """NEGATIVE: the real sound_addresses_in_iwram clause fails."""
    w, _snd, _player = _m4a_world(track=0x02000000)
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == [] and any("outside IWRAM" in line for line in w.logs)


def test_rr_sound_is_refused_by_name_when_no_player_can_be_resolved():
    w = live("gen3_rr", "radical_red")
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == []
    assert len([line for line in w.logs if "names no SE1 player" in line]) == 1


def test_sound_is_refused_while_the_session_is_ineligible():
    w, _snd, _player = _m4a_world()
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == [] and "sound" not in w.battle_checks


# ── C5-6a: the RR PC trade (apply_trade) over the REAL native.lua ─────────────────────────

PARTNER = mon_record(0x55555555, 0x00009999, species=25, nickname="PIKA")
KP = key_of(0x55555555, 0x00009999)
MB = {"opcode": 6, "seq": 8, "status": 10, "ack": 12, "result": 48}
OK_, FAIL_ = 2, 3


def mb_op(w):
    return w._read(NATIVE["BASE"] + MB["opcode"], 2)


def mb_ack(w, status=OK_, result=0):
    """What the companion patch does when it finishes the posted op."""
    base = NATIVE["BASE"]
    w.poke_int(base + MB["ack"], w._read(base + MB["seq"], 2), 2)
    w.poke_int(base + MB["status"], status, 2)
    w.poke_int(base + MB["opcode"], 0, 2)
    w.poke_int(base + MB["result"], result, 1)


def trade_world(present=True):
    w = rr_live()
    attach_real_native(w, present)
    return w, w.encode(PARTNER).hex().upper()


def swap_in_partner(w):
    """The patch's scene / silent swap: slot 1 now holds the partner's mon."""
    w.set_party([mon_record(A, OT, species=4, nickname="MON0"), PARTNER])


def apply(w, blob, old_key=KB, slot=1, token="tr1"):
    w.command(cmd="apply_trade", slot=slot, blob_hex=blob, old_key=old_key, token=token)


def trade_writes_are_native_only(w):
    reasons = set(write_reasons(w))
    assert reasons <= {"native"}, reasons
    lo, hi = NATIVE["BASE"], NATIVE["BASE"] + 0x800
    assert all(lo <= a < hi for a, _v, _f in w.writes), "a trade byte landed outside the mailbox arena"


def test_rival_swap_posts_through_the_real_native_path_and_reports_the_refresh_refusal():
    """The rival swap's OP_SET_ENEMY_PARTY posts through writes:arm("native") and the real native
    clauses; Entry refuses refresh_enemy by name (no write reason covers the battle's first
    frames), so the reply names that refusal instead of claiming a swap."""
    w, _blob = trade_world()
    w.enter_battle([FOE], trainer_id=5)
    w.command(cmd="replace_rival_team", trainer_id=5, n=1, blobs_hex=[w.encode(PARTNER).hex().upper()])
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"]
    w.poke(w.ram["ENEMY_BASE"], w.encode(PARTNER))              # the patch copied gEnemyParty
    w.poke_int(w.ram["ENEMY_COUNT_ADDR"], 1, 1)
    mb_ack(w)
    w.step()
    (reply,) = w.events("rival_team_replaced")
    assert reply["error"] == "refresh_failed"
    trade_writes_are_native_only(w)


def test_trade_happy_path_stages_runs_the_scene_and_reports_the_received_mon():
    w, blob = trade_world()
    apply(w, blob)
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"]
    staged = bytes(w._read(NATIVE["BLOB_BUF"] + i, 1) for i in range(100))
    assert staged.hex().upper() == blob                        # the partner mon, byte for byte
    mb_ack(w)
    w.step()
    assert mb_op(w) == NATIVE["OP_TRADE_SCENE"]
    w.fire("trade_begin")                                        # TradeMons fires inside the scene
    swap_in_partner(w)
    w.fire("trade_done")
    mb_ack(w)
    w.step()
    (done,) = w.events("trade_done")
    assert done == {**done, "token": "tr1", "slot": 1, "new_key": KP, "new_species": 25}
    w.fire("mon_given")
    w.step(40)
    # protocol §6.5: no key_change, no capture of the received mon, no party_to_box of the old one
    assert w.events("key_change") == [] and w.events("capture") == [] and w.events("party_to_box") == []
    trade_writes_are_native_only(w)


def test_trade_relocates_the_offered_mon_by_key_when_the_party_was_reordered():
    w, blob = trade_world()
    w.set_party([mon_record(B, OT, species=5, nickname="MON1"), mon_record(A, OT, species=4, nickname="MON0")])
    w.step()
    apply(w, blob, slot=1)                                      # the snapshot said slot 1; B is in 0 now
    w.step(2)
    mb_ack(w)
    w.step()
    assert w._read(NATIVE["BASE"] + 16, 1) == 0                 # OP_TRADE_SCENE args: slot 0
    w.set_party([PARTNER, mon_record(A, OT, species=4, nickname="MON0")])
    mb_ack(w)
    w.step()
    assert w.events("trade_done")[0]["slot"] == 0 and w.events("trade_done")[0]["new_key"] == KP


def test_trade_scene_refused_before_the_swap_falls_back_to_the_silent_swap():
    w, blob = trade_world()
    apply(w, blob)
    w.step(2)
    mb_ack(w)
    w.step()
    mb_ack(w, status=FAIL_)                                     # the scene failed; slot untouched
    w.step()
    assert mb_op(w) == NATIVE["OP_SET_PARTY_MON"]
    swap_in_partner(w)
    mb_ack(w)
    w.step()
    assert [d["new_key"] for d in w.events("trade_done")] == [KP]
    trade_writes_are_native_only(w)


def test_trade_scene_failure_after_the_swap_reconciles_without_an_overwrite():
    w, blob = trade_world()
    apply(w, blob)
    w.step(2)
    mb_ack(w)
    w.step()
    swap_in_partner(w)                                           # the scene DID swap, then failed
    mb_ack(w, status=FAIL_)
    n = len(w.writes)
    w.step(3)
    assert mb_op(w) == 0 and len(w.writes) == n                  # no silent swap on top
    assert [d["new_key"] for d in w.events("trade_done")] == [KP]


def test_trade_lost_scene_ack_waits_the_backstop_then_reconciles_from_the_slot():
    w, blob = trade_world()
    w.client.state.trade_limits.backstop = 120
    apply(w, blob)
    w.step(2)
    mb_ack(w)
    w.step()
    w.poke_int(NATIVE["BASE"] + MB["seq"], 0xBEEF, 2)           # the ACK channel is lost
    w.step()
    assert w.events("trade_done") == []                          # never an early claim
    swap_in_partner(w)                                           # the scene finished natively
    w.step(120)
    assert [d["new_key"] for d in w.events("trade_done")] == [KP]
    assert mb_op(w) == NATIVE["OP_TRADE_SCENE"]                  # nothing posted after the loss


def test_trade_stage_timeout_sends_no_trade_done_and_is_left_unresolved():
    """C5-6b: the real native.lua timeout (1800 frames) poisons the mailbox, so the silent swap
    cannot post either. The trade failed: NO trade_done, nothing fabricated, nothing purged; the
    FSM is unresolved (the server watchdog settles it) and says so."""
    w, blob = trade_world()
    w.break_checkpoint()                                         # queue a box move behind it first
    w.command(cmd="box_mon", key=KB)
    apply(w, blob)
    w.step()
    w.overworld_safe()
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"]
    w.step(1801)
    assert w.events("trade_done") == []
    assert w.client.state.trade_apply is None and w.client.state.trade_unresolved["tr1"].phase == "unresolved"
    assert any(h[0] == "show" and "TRADE UNRESOLVED" in h[1] for h in w.hud)
    assert not any("trade: purged" in line for line in w.logs)    # the queued move was not purged


def test_trade_failed_silent_swap_sends_no_trade_done():
    w, blob = trade_world()
    apply(w, blob)
    w.step(2)
    mb_ack(w)
    w.step()
    mb_ack(w, status=FAIL_)                                     # the scene failed, slot untouched
    w.step()
    assert mb_op(w) == NATIVE["OP_SET_PARTY_MON"]
    mb_ack(w, status=FAIL_)                                     # and the silent swap failed too
    w.step(3)
    assert w.events("trade_done") == []
    assert w.client.state.trade_unresolved["tr1"] is not None
    assert any("silent swap failed" in line for line in w.logs)


def test_trade_unreadable_party_at_scene_completion_reports_nothing_then_the_truth():
    w, blob = trade_world()
    apply(w, blob)
    w.command(cmd="box_mon", key=KB)                            # held while the trade is owned
    w.step(2)
    mb_ack(w)
    w.step()
    swap_in_partner(w)
    w.poke_int(w.ram["PARTY_COUNT_ADDR"], 7, 1)                 # the party cannot be read back
    mb_ack(w)
    w.step(3)
    assert w.events("trade_done") == []
    assert w.client.deferred.size(w.client.deferred) == 1      # nothing purged
    assert w.client.state.trade_apply.phase == "readback"
    w.poke_int(w.ram["PARTY_COUNT_ADDR"], 2, 1)                 # readable again
    w.step()
    assert [d["new_key"] for d in w.events("trade_done")] == [KP]
    assert w.client.deferred.size(w.client.deferred) == 0      # purged only now, on the fact


def test_codex_blocker1_a_reorder_after_the_stage_retargets_the_scene():
    """Codex REV4 repro: offer B at slot 1 -> op16 staged -> reorder to B slot 0 / A slot 1 ->
    stage ACK. The scene must post for B's slot 0; bystander A is never traded."""
    w, blob = trade_world()
    apply(w, blob, slot=1)
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"]
    w.set_party([mon_record(B, OT, species=5, nickname="MON1"), mon_record(A, OT, species=4, nickname="MON0")])
    mb_ack(w)
    w.step(2)
    assert mb_op(w) == NATIVE["OP_TRADE_SCENE"]
    assert w._read(NATIVE["BASE"] + 16, 1) == 0                 # args: B's slot now
    w.set_party([PARTNER, mon_record(A, OT, species=4, nickname="MON0")])
    mb_ack(w)
    w.step()
    (done,) = w.events("trade_done")
    assert (done["slot"], done["new_key"]) == (0, KP)


def test_a_reorder_before_the_silent_swap_dispatch_retargets_the_fallback():
    w, blob = trade_world()
    apply(w, blob, slot=1)
    w.step(2)
    mb_ack(w)
    w.step()
    w.set_party([mon_record(B, OT, species=5, nickname="MON1"), mon_record(A, OT, species=4, nickname="MON0")])
    mb_ack(w, status=FAIL_)                                     # scene failed; B moved meanwhile
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SET_PARTY_MON"]
    assert w._read(NATIVE["BASE"] + 16, 1) == 0                 # the silent swap targets B's slot 0


def test_the_offered_mon_leaving_before_the_scene_posts_nothing_for_the_slot():
    w, blob = trade_world()
    apply(w, blob, slot=1)
    w.step(2)
    w.set_party([mon_record(A, OT, species=4, nickname="MON0")])  # B was boxed meanwhile
    mb_ack(w)
    w.step(2)
    assert mb_op(w) == 0                                         # no scene was posted
    (done,) = w.events("trade_done")
    assert (done["new_key"], done["new_species"]) == (KB, 0)     # the authorized "nothing changed"


def _paused_gift(w):
    """The session pauses (native posting refused, zero bytes) and a gift C lands meanwhile."""
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.set_party([mon_record(A, OT, species=4, nickname="MON0"), mon_record(B, OT, species=5, nickname="MON1"),
                 mon_record(C, OT, species=6, nickname="MON2")])
    w.fire("mon_given")
    w.step()


def test_codex_c56c_1_a_queued_but_unposted_trade_does_not_freeze_a_paused_gift():
    """Codex REV6 repro: apply; step (the stage is only QUEUED: opcode 0, no bytes); the session
    pauses, the party gains C, mon_given fires, step. capture(KC) must be reported -- and stays
    the only capture after the trade later completes with [A, PARTNER, C]."""
    w, blob = trade_world()
    apply(w, blob)
    w.step()
    assert mb_op(w) == 0 and w.writes == []
    _paused_gift(w)
    assert [c["key"] for c in w.events("capture")] == [KC]
    assert w.client.state.trade_apply.posted is not True
    w.client.writes_enabled, w.client.gate_revoked = True, False
    w.step()
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"] and w.client.state.trade_apply.posted is True
    mb_ack(w)
    w.step()
    w.set_party([mon_record(A, OT, species=4, nickname="MON0"), PARTNER,
                 mon_record(C, OT, species=6, nickname="MON2")])
    mb_ack(w)
    w.step(3)
    assert [d["new_key"] for d in w.events("trade_done")] == [KP]
    assert [c["key"] for c in w.events("capture")] == [KC]


def test_codex_c57_a_foreign_sink_write_in_the_same_call_does_not_latch_the_trade():
    """REV7's counterexample at the client seam. In one pre_pump call a panel/NPC callback moves
    the sink's byte count while our trade job is held at its arm and its guard has already run --
    exactly the two inputs the old byte-count latch read. The latch must stay unset, because it
    reads the posting job's own dispatch receipt (native.lua sets `job.posted` when it publishes
    that job's opcode, and nothing else does)."""
    w, blob = trade_world()
    w.command(cmd="config", overworld_presence=False, pc_trade_npc=True)
    w.step(3)
    apply(w, blob)
    w.step()                                                    # the stage is queued, nothing posted
    assert w.client.state.trade_apply.posted is not True
    writes = w.parts.writes
    before = writes.attempted
    sends = w.client.send
    def with_a_foreign_byte(*args):
        writes.attempted = writes.attempted + 1                 # a foreign writer's byte, this call
        return sends(*args)
    w.client.send = with_a_foreign_byte
    counter = NATIVE["PI_COUNT"]
    w.poke_int(counter, w._read(counter, 1) + 1, 1)             # the NPC branch sends in this call
    w.client.writes_enabled, w.client.gate_revoked = False, True   # held: the arm refuses
    w.step()
    assert writes.attempted > before, "the counter moved with no trade byte in it"
    posts = w.client.state.trade_apply.posts
    assert posts is not None and posts[1]["posted"] is None     # our job was attempted, not published
    assert w.client.state.trade_apply.posted is not True
    w.client.writes_enabled, w.client.gate_revoked = True, False
    w.step()
    assert mb_op(w) == NATIVE["OP_SET_ENEMY_PARTY"]             # the held job then posts...
    assert w.client.state.trade_apply.posted is True            # ...and the receipt latches it


def test_codex_c56c_1_control_the_same_paused_gift_without_a_trade_is_captured():
    w, _blob = trade_world()
    _paused_gift(w)
    assert [c["key"] for c in w.events("capture")] == [KC]


PARTNER2 = mon_record(0x66666666, 0x00008888, species=26, nickname="RAI")
KP2 = key_of(0x66666666, 0x00008888)


def _unresolve_by_a_stage_seq_overwrite(w, blob, token, old_key=KB, slot=1):
    apply(w, blob, old_key=old_key, slot=slot, token=token)
    w.step(2)
    w.poke_int(NATIVE["BASE"] + MB["seq"], 0xBEEF, 2)           # the stage ACK channel is lost
    w.step(3)
    assert w.client.state.trade_unresolved[token] is not None


def test_codex_c56c_2_a_second_unresolved_trade_never_hides_the_first_ones_late_fact():
    """Codex REV6 repro: tr1 goes unresolved (a lost ACK poisons the mailbox), tr2 fails its
    fallback on the poisoned mailbox and is unresolved too; then tr1's real partner mon appears.
    tr1's trade_done must come. Option chosen: per-transaction records, each watched."""
    w, blob = trade_world()
    _unresolve_by_a_stage_seq_overwrite(w, blob, "tr1")
    blob2 = w.encode(PARTNER2).hex().upper()
    # the poisoned mailbox fails the checkpoint's native_idle clause, so tr2 waits out the
    # field-clear limit and then tries its silent swap on the poisoned mailbox
    w.client.state.trade_limits.field_wait = 5
    apply(w, blob2, old_key=KA, slot=0, token="tr2")
    w.step(8)
    assert w.client.state.trade_unresolved["tr2"] is not None
    assert w.events("trade_done") == []
    swap_in_partner(w)                                           # tr1's partner lands after all
    w.step()
    assert [(d["token"], d["new_key"]) for d in w.events("trade_done")] == [("tr1", KP)]
    assert w.client.state.trade_unresolved["tr1"] is None
    assert w.client.state.trade_unresolved["tr2"] is not None    # still watched, not overwritten


def test_codex_c56c_2_control_a_lone_unresolved_trade_reports_its_late_fact():
    w, blob = trade_world()
    _unresolve_by_a_stage_seq_overwrite(w, blob, "tr1")
    assert w.events("trade_done") == []
    swap_in_partner(w)
    w.step()
    assert [(d["token"], d["new_key"]) for d in w.events("trade_done")] == [("tr1", KP)]


def test_codex_major_a_battle_faint_while_an_apply_waits_is_still_reported():
    """Codex REV4: apply during a battle (the apply waits, nothing posted) and a real player
    faint: the faint is reduced normally -- only the owned swap lifecycle freezes diffing."""
    w, blob = trade_world()
    w.enter_battle([FOE])
    apply(w, blob)
    w.step()
    assert w.client.state.trade_apply.phase == "wait"
    w.set_party([mon_record(A, OT, species=4, nickname="MON0", hp=0), mon_record(B, OT, species=5, nickname="MON1")])
    w.fire("faint")
    w.step()
    assert [f["key"] for f in w.events("faint")] == [KA]


def test_trade_partner_declining_the_confirm_writes_no_party_byte_and_completes_nothing():
    w, _blob = trade_world()
    w.command(cmd="show_menu", token="cf", text="Trade your MON1 for PIKA?")
    w.step(2)
    assert mb_op(w) == NATIVE["OP_SHOW_MENU"]
    mb_ack(w, result=0)                                          # NO
    w.step()
    assert [(m["token"], m["choice"]) for m in w.events("menu_result")] == [("cf", 0)]
    assert w.events("trade_done") == [] and w.party_hp(1) == 20
    trade_writes_are_native_only(w)


def test_trade_on_rr_clean_has_no_trade_path_writes_nothing_and_completes_nothing():
    w = live("gen3_rr", "radical_red", "clean")
    assert w.parts.native is None
    apply(w, w.encode(PARTNER).hex().upper())
    w.step(5)
    assert w.writes == [] and w.events("trade_done") == []


def test_trade_with_the_companion_beacon_absent_aborts_with_no_write_and_no_completion():
    w, blob = trade_world(present=False)
    apply(w, blob)
    w.step(5)
    assert w.writes == [] and w.events("trade_done") == []
    assert w.client.state.trade_apply is None and any("trade ABORTED" in line for line in w.logs)


def test_trade_nothing_changed_when_the_offered_mon_left_the_party():
    w, blob = trade_world()
    apply(w, blob, old_key=KC, slot=1)                          # KC was never in the party
    w.step(2)
    (done,) = w.events("trade_done")
    assert (done["new_key"], done["new_species"], done["slot"]) == (KC, 0, 1)
    assert w.writes == []                                        # the bystander in slot 1 untouched


def test_trade_holds_the_checkpoint_queue_then_purges_box_moves_for_the_traded_keys():
    w, blob = trade_world()
    w.break_checkpoint()                                         # the apply waits for a clear field
    apply(w, blob)
    w.command(cmd="box_mon", key=KB)
    w.step(3)
    assert w.client.deferred.size(w.client.deferred) == 1
    w.overworld_safe()
    w.step(2)
    mb_ack(w)
    w.step()
    swap_in_partner(w)
    mb_ack(w)
    w.step(3)
    assert w.events("trade_done")[0]["new_key"] == KP
    assert w.client.deferred.size(w.client.deferred) == 0 and w.events("box_mon_failed") == []


def test_trade_request_is_never_sent_while_an_apply_is_in_flight():
    w, blob = trade_world()
    w.command(cmd="config", overworld_presence=False, pc_trade_npc=True)
    w.step(3)
    counter = NATIVE["PI_COUNT"]
    w.poke_int(counter, w._read(counter, 1) + 1, 1)             # positive control: an NPC talk
    w.step()
    assert len(w.events("trade_request")) == 1
    w.break_checkpoint()
    apply(w, blob)
    w.step()
    w.poke_int(counter, w._read(counter, 1) + 1, 1)
    w.step()
    assert len(w.events("trade_request")) == 1                   # the second one was dropped
    assert any("trade_request dropped" in line for line in w.logs)


def test_a_second_apply_while_one_is_in_flight_is_ignored():
    w, blob = trade_world()
    w.break_checkpoint()
    apply(w, blob, token="t1")
    apply(w, blob, token="t2")
    w.step()
    assert w.client.state.trade_apply.token == "t1"


# ── static contract ───────────────────────────────────────────────────────────────────────

BIZHAWK = re.compile(r"\b(memory|mainmemory|event|gui|console|emu|client|joypad|comm|gameinfo|bizstring|forms)\s*\.")


def test_the_driver_names_no_bizhawk_global_and_no_title():
    code = "\n".join(line.split("--", 1)[0] for line in
                     (REPO / "lua" / "gen3" / "client.lua").read_text(encoding="utf-8").splitlines())
    assert not BIZHAWK.search(code), BIZHAWK.search(code)
    assert not re.search(r"firered|leafgreen|radical_red|gen3_frlg|gen3_rr", code)
    assert not re.search(r"\bmemory\.write|write_u8\(", code)
    _ = lua_to_py


def test_a_pc_withdraw_is_box_to_party_while_the_party_count_is_stale():
    """Live boxsync_gen3 run 1 (FR A): the withdraw sent no box_to_party. pret pokefirered: the
    storage system recounts gPlayerPartyCount only on box exit (pokemon_storage_system_tasks.c
    Task_OnBPressed/Task_OnCloseBoxPressed state 4). A deposit zeroes its slot under the old
    count; a withdraw lands at slot == count, past a count-bounded read."""
    w = live(pids=(A, B))
    base, size = w.party_base(), 100
    w.poke(base + size, bytes(size))                           # deposit: count stays 2
    w.set_box(0, 0, mon_record(B, OT, species=5))
    w.fire("pc_deposit")
    w.step()
    assert [e["key"] for e in w.events("party_to_box")] == [KB]
    w.set_party(party(A))                                      # box exit recounts: 1
    w.fire("map_load")
    w.step()
    w.set_box(0, 0, None)                                      # withdraw: count stays 1
    w.poke(base + size, w.encode(party(A, B)[1]))
    w.fire("pc_withdraw")
    w.step()
    assert [e["key"] for e in w.events("box_to_party")] == [KB]
    w.set_party(party(A, B))                                   # box exit recounts: 2
    w.fire("map_load")
    w.step()
    assert [e["key"] for e in w.events("box_to_party")] == [KB]   # no duplicate
