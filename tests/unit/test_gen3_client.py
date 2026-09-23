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
    assert "refuses" in str(held.why)
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
        w.poke_int(w.ram["BATTLE_COMM_ADDR"], 0, 1)
        w.step()
        assert w._read(w.ram["BATTLE_COMM_ADDR"], 1) == 3
    assert _hp_writes(w) == [] and set(write_reasons(w)) == {"battle_commit"}
    assert w.client.battle_pending_count(w.client) == 1


def test_rr_explosion_that_the_battler_survives_degrades_to_a_held_faint():
    w, base = _explode_world()
    w.command(cmd="force_explode", key=KA)
    w.step()
    w.poke_int(base + 0x24, 4, 1)                               # executed
    w.poke_int(w.ram["BATTLE_COMM_ADDR"], 0, 1)                 # a new turn began, hp > 0
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
    """The REAL lua/gen3/native.lua over this World's production sink, attached late."""
    if present:
        w.poke_int(NATIVE["BASE"], NATIVE["SIG"], 4)
        w.poke_int(NATIVE["BASE"] + 4, NATIVE["ABI"], 2)
    L = w.lua
    N = L.eval(f'dofile("{(REPO / "lua" / "gen3" / "native.lua").as_posix()}")')
    json_mod = L.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    native = N.new(L.table_from(RR_PACK, recursive=True), L.table(
        io=w.io, writes=w.parts.writes, reads=w.parts.reads, send=w.client.send,
        in_battle=lambda: True, refresh_enemy=lambda *_: True, artifact_kind=w.kind,
        array=json_mod.array))
    w.client.attach_native(native)
    return native


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


def _m4a_world(allow):
    """An initialised m4a SE1 player in IWRAM and a pack gSoundInfo pointer."""
    w = live()
    w.battle_ok = allow
    ptr, info, node_a, node_b, track0 = 0x03007FF0, 0x03006000, 0x03006100, 0x03006200, 0x03006300
    w.parts.profile.ram.SOUND_INFO_PTR_ADDR = ptr              # not in the packs yet (reported)
    w.poke_int(ptr, info, 4)
    w.poke_int(info + 0x24, node_a, 4)
    w.poke_int(node_a + 0x3C, node_b, 4)
    w.poke_int(node_a + 0x34, 0x68736D53, 4)
    w.poke_int(node_a + 0x2C, track0, 4)
    hdr = w.profile["rom"]["SE_SONG_HEADERS"]["26"] - 0x08000000
    for i, b in enumerate([1, 0, 5, 0, 0, 0, 0, 0, 0x10, 0x20, 0x30, 0x08]):
        w.rom[hdr + i] = b
    return w


def test_sound_without_the_pack_pointer_is_refused_once_and_writes_nothing():
    w = live()
    w.command(cmd="game_over")
    w.step(2)
    w.command(cmd="play_sound", sound=26)
    w.step(2)
    assert w.writes == []
    assert len([line for line in w.logs if "SOUND_INFO_PTR_ADDR" in line]) == 1


@pytest.mark.parametrize("allow", [False, True])
def test_sound_fallback_arms_the_sound_reason_and_a_refusal_writes_nothing(allow):
    """allow=False: the policy refuses "sound". allow=True: the policy admits it but writes.lua
    has no "sound" reason yet (OMP C4-B2 adds it), so the arm itself refuses. Either way: no
    sound, one log line, never an ungated write."""
    w = _m4a_world(allow)
    w.command(cmd="play_sound", sound=26)
    w.step()
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == []
    assert "sound" in w.battle_checks                           # the arm went through the policy
    assert len([line for line in w.logs if "sound refused" in line]) == 1


def test_sound_is_refused_while_the_session_is_ineligible():
    w = _m4a_world(True)
    w.client.writes_enabled, w.client.gate_revoked = False, True
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == [] and "sound" not in w.battle_checks


# ── static contract ───────────────────────────────────────────────────────────────────────

BIZHAWK = re.compile(r"\b(memory|mainmemory|event|gui|console|emu|client|joypad|comm|gameinfo|bizstring|forms)\s*\.")


def test_the_driver_names_no_bizhawk_global_and_no_title():
    code = "\n".join(line.split("--", 1)[0] for line in
                     (REPO / "lua" / "gen3" / "client.lua").read_text(encoding="utf-8").splitlines())
    assert not BIZHAWK.search(code), BIZHAWK.search(code)
    assert not re.search(r"firered|leafgreen|radical_red|gen3_frlg|gen3_rr", code)
    assert not re.search(r"\bmemory\.write|write_u8\(", code)
    _ = lua_to_py
