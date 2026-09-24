"""Client findings of the independent Soul Link invariant review
(docs/gen2/reviews/REVIEW_SOULLINK_INVARIANTS_2026-09-24.md): MAJOR-1, MINOR-7, MINOR-9, both GB clients.
Harnesses are reused from tests/unit/test_gen2_client.py and tests/unit/test_gen1_client.py.
"""

import random

import pytest

from tests.unit import test_gen1_client as g1, test_gen2_client as g2
from tests.unit.test_gen2_client import codec_key, mon
from tests.unit.test_o30_faint_followups import g1_kod, hold, kod, start_battle


# ── MAJOR-1: a post-DONE report is owed until the server has answered its line ────────────────────────
def ack_all(sent_before, world_lines, reply):
    """server.py answers every line with exactly one {"commands"} line, in order."""
    for _ in range(world_lines() - sent_before):
        reply()


def g2_done(cart, g2_up):
    g2.proposer_ready(cart)
    cart.w.reply(g2.apply_cmd())
    cart.w.frames(1)
    cart.pick_up("SlinkTradeApplyPickup")
    cart.w.party([g2.PARTNER])                     # REMOVE+compact then APPEND
    cart.done(0)
    cart.w.net.up = g2_up
    cart.w.frames(2)


def g2_received(world):
    return [(d["new_key"], d["new_species"]) for d in world.sent("trade_done")]


def test_gen2_a_done_report_while_the_socket_is_down_reaches_the_server_after_the_hello():
    cart = g2.TradeCart()
    g2_done(cart, g2_up=False)
    assert cart.w.sent("trade_done") == []
    cart.w.net.up = True
    cart.w.frames(3)
    assert g2_received(cart.w) == [(codec_key(g2.PARTNER), 19)]
    last_hello = max(i for i, m in enumerate(cart.w.sent()) if m["event"] == "hello")
    assert [m["event"] for m in cart.w.sent()].index("trade_done") > last_hello


def test_gen2_a_done_report_whose_line_died_with_the_socket_is_sent_again_until_answered():
    cart = g2.TradeCart()
    g2_done(cart, g2_up=True)
    assert len(g2_received(cart.w)) == 1           # queued, never answered: the connection died
    cart.w.net.up = False
    cart.w.frames(2)
    cart.w.net.up = True
    before = len(cart.w.sent())                    # the reconnect: hello, then the owed report
    cart.w.frames(3)
    assert g2_received(cart.w) == [(codec_key(g2.PARTNER), 19)] * 2
    ack_all(before, lambda: len(cart.w.sent()), lambda: cart.w.reply())
    cart.w.frames(1)
    cart.w.net.up = False
    cart.w.frames(2)
    cart.w.net.up = True
    cart.w.frames(3)
    assert len(g2_received(cart.w)) == 2, "answered: never sent again"


def test_gen2_a_nothing_changed_report_while_the_socket_is_down_is_owed():
    cart = g2.TradeCart()
    g2.proposer_ready(cart)
    cart.w.reply(g2.apply_cmd())
    cart.w.frames(1)
    cart.w.net.up = False
    cart.close()                                   # the cartridge left before the pickup
    cart.w.frames(2)
    assert cart.w.sent("trade_done") == []
    cart.w.net.up = True
    cart.w.frames(3)
    assert g2.nothing_changed(cart.w)


def g1_apply(w, up):
    rng = random.Random(12)
    incoming = g1._mon(rng, 0xB1, level=7, nick="PIDGEY")
    blob = g1.codec.encode_party_mon(incoming) + g1.codec.encode_name("BLUE") + g1.codec.encode_name("PIDGEY")
    base = w.ram["wSerialPartyMonsPatchList"]
    w.reply({"cmd": "apply_trade", "slot": 0, "blob_hex": blob.hex().upper(), "old_key": g1.codec.key(w.party()[0]),
             "token": "t8", "partner_name": "BLUE"})
    w.step()
    gen = g1._overlay(w)[6]
    w.seed_party([incoming])
    w.bus[w.ram["wRemoveMonFromBox"]] = 0
    w.bus[w.ram["wWhichPokemon"]] = 0
    w.fire("remove_pokemon")
    w.step()
    w.connected = up
    w.bus[base + 5], w.bus[base + 8], w.bus[base + 7] = 7, 0, gen   # DONE, result 0
    w.step()
    w.overworld_safe()


def test_gen1_a_done_report_while_the_socket_is_down_reaches_the_server_after_the_hello():
    w = g1._patched_world()
    g1_apply(w, up=False)
    assert w.events("trade_done") == []
    w.connected = True
    w.step(3)
    td = w.events("trade_done")
    assert [(d["token"], d["new_key"]) for d in td] == [("t8", g1.codec.key(w.party()[0]))]
    events = [m["event"] for m in w.sent]
    assert events.index("trade_done") > max(i for i, e in enumerate(events) if e == "hello")


def test_gen1_a_done_report_whose_line_died_with_the_socket_is_sent_again_until_answered():
    w = g1._patched_world()
    g1_apply(w, up=True)
    assert len(w.events("trade_done")) == 1
    w.connected = False
    w.step(2)
    w.connected = True
    before = len(w.sent)
    w.step(3)
    assert len(w.events("trade_done")) == 2
    ack_all(before, lambda: len(w.sent), lambda: w.reply())
    w.step()
    w.connected = False
    w.step(2)
    w.connected = True
    w.step(3)
    assert len(w.events("trade_done")) == 2, "answered: never sent again"


# ── MINOR-7: a landed death stays dead until its burial, whatever heals the party ────────────────────
def g2_landed(world):
    lead, dead = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, dead])
    world.hello()
    world.frames(60)                                          # the writes gate validates
    world.reply({"cmd": "force_faint", "key": codec_key(dead), "nickname": "PICHU"})
    world.frames(2)                                           # the checkpoint lands it
    assert world.hp_of(1) == (0, 0)
    world.frames(5)                                           # later checkpoints see HP 0: no quiet entry left
    return lead, dead


@pytest.mark.parametrize("where", ["checkpoint", "after_reset", "hold_bench", "hold_active"])
def test_gen2_a_landed_death_healed_before_its_burial_dies_again_quietly(where):
    """Review MINOR-7: a Pokecenter heal or the Battle Tower's HealParty before battle 1 (C engine/events/
    battle_tower/battle_tower.asm:226-228) revives a dead mon whose memorialize has not run yet."""
    world = g2.World()
    lead, dead = g2_landed(world)
    healed = [lead, dict(dead, hp=30)]
    if where == "after_reset":
        world.client.boundary(world.client, "reset", "save_reset")   # the client state survives a soft reset
    world.party(healed)                                       # HealParty
    if where in ("checkpoint", "after_reset"):
        world.frames(3)
    else:
        world.checkpoint_ok = False                           # the tower: one script, no checkpoint
        start_battle(world, healed, active=1 if where == "hold_active" else 0)
        hold(world)
    assert world.hp_of(1) == (0, 0) and world.hp_of(0)[0] > 0
    if where == "hold_active":
        assert g2.battle_hp(world) == 0
    assert kod(world) == ["show:!! PICHU KO'd"], "the re-zero is quiet"
    n = len(world.written())
    if where.startswith("hold"):
        hold(world)
    else:
        world.frames(5)
    assert len(world.written()) == n, "idempotent: HP 0 needs nothing more"


def test_gen2_an_o24_re_issue_after_the_client_re_zeroed_is_silent():
    world = g2.World()
    lead, dead = g2_landed(world)
    world.party([lead, dict(dead, hp=30)])
    world.frames(3)
    n = len(world.written())
    world.reply({"cmd": "force_faint", "key": codec_key(dead), "nickname": "PICHU"})   # O-24
    world.frames(3)
    assert kod(world) == ["show:!! PICHU KO'd"] and len(world.written()) == n


@pytest.fixture
def world1():
    w = g1.World("red")
    rng = random.Random(1)
    w.seed_party([g1._mon(rng, 0x99, nick="BULBA"), g1._mon(rng, 0xB1, nick="PIDGEY")])
    w.set_map(0x0C)
    w.give_poke_ball()
    w.connect()
    w.step(60)
    return w


def g1_heal(world1):
    hp = world1.ram["wPartyMons"] + 44 + 1
    world1.bus[hp], world1.bus[hp + 1] = 0, 7


@pytest.mark.parametrize("where", ["checkpoint", "loop_head"])
def test_gen1_a_landed_death_healed_before_its_burial_dies_again_quietly(world1, where):
    key = g1.codec.key(world1.party()[1])
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world1.step(2)                                            # the checkpoint lands it
    assert world1.party()[1]["hp"] == 0
    world1.step(5)
    g1_heal(world1)                                           # a Pokemon Center
    if where == "checkpoint":
        world1.step(3)
    else:
        world1.regs["PC"] = 0x1234                            # no checkpoint before the battle
        world1.in_battle(opponent=0xA5, species=0xA5, level=3, active_slot=0)
        world1.fire("wild_begin")
        world1.step()
        world1.fire("battle_loop_head")
    assert world1.party()[1]["hp"] == 0 and world1.party()[0]["hp"] > 0
    assert len(g1_kod(world1)) == 1, "the re-zero is quiet"
    n = len(world1.writes)
    if where == "checkpoint":
        world1.step(5)
    else:
        world1.fire("battle_loop_head")
    assert len(world1.writes) == n, "idempotent: HP 0 needs nothing more"


# ── MINOR-9: Gen 1 defers a force_faint for a key not in the party, as Gen 2 does (4e6aea39) ───────────
def test_gen1_a_force_faint_for_a_key_not_in_the_party_is_deferred_not_dropped(world1):
    away = g1._mon(random.Random(7), 0x19, nick="PIKA")          # in the Day-Care / a box / a transient party
    key = g1.codec.key(away)
    world1.regs["PC"] = 0x1234                                   # no checkpoint yet
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "PIKA"})
    world1.step()
    assert [e["key"] for e in world1.client.deferred.values()] == [key]
    assert not any("key not in party" in line for line in world1.logs)
    world1.overworld_safe()
    world1.step(2)                                               # the checkpoint decides: still away, dropped
    assert len(world1.client.deferred) == 0
    assert any("dropped at the checkpoint" in line for line in world1.logs)
