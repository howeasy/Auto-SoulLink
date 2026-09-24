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


# ── MAJOR-1 follow-up (OMP review of 15f1e786): a REFUSED reply never retires a report ────────────────
# The identity/admission gate answers a line it did not process with {"cmd": "noop", "refused": ...}.
REFUSED = {"cmd": "noop", "refused": "identity"}


def owed_module():
    import lupa
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    owed = lua.eval(f'dofile("{(g2.ROOT / "lua/owed_reports.lua").as_posix()}")').new()
    sent = []

    def send(event, fields):
        sent.append(str(event))
        owed.line_sent(owed)
        return True
    return lua, owed, sent, send


def reply(lua, owed, *commands):
    owed.line_received(owed)
    owed.answer(owed, lua.table_from([lua.table_from(c) for c in commands]))


def test_owed_a_refused_report_keeps_every_later_report_behind_it():
    lua, owed, sent, send = owed_module()
    for ev in ("A", "B"):
        owed.list[len(owed.list) + 1] = lua.table_from({"event": ev, "fields": lua.table()})
    owed.step(owed, True, True, send)
    assert sent == ["A", "B"]
    reply(lua, owed, REFUSED)                                  # line 1 (A) was not processed
    reply(lua, owed, {"cmd": "noop"})                          # line 2 (B) was, but ahead of A
    assert [str(e.event) for e in owed.list.values()] == ["A", "B"], "B stays behind A (INV-CLIENT-2 order)"
    owed.step(owed, True, True, send)
    assert sent == ["A", "B", "A", "B"], "both go again, in order, once the server answers normally"
    reply(lua, owed, {"cmd": "noop"})
    reply(lua, owed, {"cmd": "noop"})
    assert len(owed.list) == 0


def test_owed_after_a_refusal_waits_for_an_accepted_reply_before_sending_again():
    lua, owed, sent, send = owed_module()
    owed.list[1] = lua.table_from({"event": "A", "fields": lua.table()})
    owed.step(owed, True, True, send)
    reply(lua, owed, REFUSED)
    owed.step(owed, True, True, send)
    assert sent == ["A"], "no resend into a gate that is still refusing (one per frame otherwise)"
    send("tick", None)                                        # the next tick is answered normally
    reply(lua, owed, {"cmd": "noop"})
    owed.step(owed, True, True, send)
    assert sent == ["A", "tick", "A"]


def test_gen2_a_refused_hello_never_retires_the_owed_report():
    cart = g2.TradeCart()
    g2_done(cart, g2_up=False)
    cart.w.net.up = True
    before = len(cart.w.sent())
    cart.w.frames(3)                                          # hello + trade_done, both refused
    assert g2_received(cart.w) == [(codec_key(g2.PARTNER), 19)]
    ack_all(before, lambda: len(cart.w.sent()), lambda: cart.w.reply(REFUSED))
    cart.w.frames(1)
    cart.w.reply()                                            # the gate accepts: the next line is answered
    cart.w.frames(2)
    assert g2_received(cart.w) == [(codec_key(g2.PARTNER), 19)] * 2


def test_gen1_a_refused_hello_never_retires_the_owed_report():
    w = g1._patched_world()
    g1_apply(w, up=False)
    w.connected = True
    before = len(w.sent)
    w.step(3)
    assert len(w.events("trade_done")) == 1
    ack_all(before, lambda: len(w.sent), lambda: w.reply(REFUSED))
    w.step()
    w.reply()
    w.step(2)
    assert len(w.events("trade_done")) == 2


# ── O-35 (owner ruling, server 8f662994): a PC release sends release{key}; the server kills the partner ────
@pytest.mark.parametrize("collection", ["party", "box"])
def test_gen2_a_pc_release_sends_release_not_a_deposit(collection):
    world = g2.World()
    lead, gone = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, gone])
    world.hello()
    record = world.parts.reads.read_party().mons[2]
    ev = world.lua.table_from({"kind": "pc_release", "collection": collection, "mon": record, "box_index": 0})
    world.client.on_event(world.client, ev)
    world.frames(1)
    assert [m["key"] for m in world.sent("release")] == [codec_key(gone)]
    assert world.sent("party_to_box") == [], "a release is not a deposit"


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
        world.client.boundary(world.client, "reset", "save_reset")
        world.reply({"cmd": "dead_keys", "keys": [codec_key(dead)]})   # the post-reset hello's sync
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


# ── INV-CLIENT-2 (OMP cx-40ba318d on 5d7cbe1c / f5c8193b / 149b38e2) ─────────────────────────────────
def test_owed_a_refused_report_is_replayed_in_its_original_order():
    """A/B/C in flight; A refused, B answered: everything from the first unanswered line goes again, A, B, C."""
    lua, owed, sent, send = owed_module()
    for ev in ("A", "B", "C"):
        owed.list[len(owed.list) + 1] = lua.table_from({"event": ev, "fields": lua.table()})
    owed.step(owed, True, True, send)
    reply(lua, owed, REFUSED)
    reply(lua, owed, {"cmd": "noop"})
    reply(lua, owed, REFUSED)
    send("tick", None)
    reply(lua, owed, {"cmd": "noop"})                          # the gate answers normally again
    owed.step(owed, True, True, send)
    assert sent == ["A", "B", "C", "tick", "A", "B", "C"]
    for _ in range(3):
        reply(lua, owed, {"cmd": "noop"})
    assert len(owed.list) == 0


def test_gen2_a_release_while_the_socket_is_down_is_sent_once_after_the_hello():
    world = g2.World()
    lead, gone = mon(), mon(species=172, dvs=0x3AAA)
    world.party([lead, gone])
    world.hello()
    record = world.parts.reads.read_party().mons[2]
    world.net.up = False
    world.frames(2)
    world.client.on_event(world.client, world.lua.table_from({"kind": "pc_release", "collection": "box",
                                                               "mon": record, "box_index": 0}))
    world.frames(2)
    assert world.sent("release") == []
    world.net.up = True
    world.frames(3)
    assert [m["key"] for m in world.sent("release")] == [codec_key(gone)]
    events = [m["event"] for m in world.sent()]
    assert events.index("release") > max(i for i, e in enumerate(events) if e == "hello")


def test_gen1_a_release_while_the_socket_is_down_is_sent_once_after_the_hello(world1):
    r = world1.ram
    released = g1._box_mon(random.Random(5), 0x15, level=8)
    g1._seed_active_box(world1, [released])
    world1.step(3)
    world1.connected = False
    world1.step()
    world1.bus[r["wRemoveMonFromBox"]] = 1
    world1.bus[r["wWhichPokemon"]] = 0
    world1.fire("remove_pokemon")
    world1.step()
    assert world1.events("release") == []
    world1.overworld_safe()
    world1.connected = True
    world1.step(3)
    assert [m["key"] for m in world1.events("release")] == [g1.codec.key(released)]


def test_gen2_a_released_dead_key_is_forgotten_so_a_reused_key_lives():
    world = g2.World()
    lead, dead = g2_landed(world)
    record = world.parts.reads.read_party().mons[2]
    world.party([lead])
    world.client.on_event(world.client, world.lua.table_from({"kind": "pc_release", "collection": "party",
                                                              "mon": record}))
    assert not world.client.dead_keys[codec_key(dead)]
    world.party([lead, dict(dead, hp=30)])                    # a new mon under the same key
    world.frames(3)
    assert world.hp_of(1) == (30, 0)


def test_gen2_the_hello_sync_replaces_the_dead_set_so_a_revived_mon_survives():
    """A debug revive (or an unlink, a rollback) before the burial: the server no longer lists the key."""
    world = g2.World()
    lead, dead = g2_landed(world)
    world.reply({"cmd": "dead_keys", "keys": []})
    world.frames(1)
    n = len(world.written())
    world.party([lead, dict(dead, hp=30)])                    # the manual restore
    world.frames(3)
    assert world.hp_of(1) == (30, 0) and len(world.written()) == n


def test_gen2_a_different_save_with_the_same_ot_gets_no_stale_write():
    world = g2.World()
    lead, dead = g2_landed(world)
    n = len(world.written())
    world.client.boundary(world.client, "reload", "save_reload")   # another save, same OT
    world.party([lead, dict(dead, hp=30)])
    world.frames(3)                                           # its checkpoints, before the hello's sync
    assert world.hp_of(1) == (30, 0) and len(world.written()) == n
    world.reply({"cmd": "dead_keys", "keys": []})             # this run never killed it on that save
    world.frames(3)
    assert world.hp_of(1) == (30, 0) and len(world.written()) == n


def test_gen2_a_failed_memorial_of_an_absent_key_forgets_it():
    world = g2.box_world([mon(), mon(species=172, dvs=0x3AAA)])
    lead, dead = mon(), mon(species=172, dvs=0x3AAA)
    world.checkpoint_ok = True
    world.reply({"cmd": "force_faint", "key": codec_key(dead)})
    world.frames(2)
    assert world.hp_of(1) == (0, 0)
    world.party([lead])                                       # gone (released, traded, lost)
    world.reply({"cmd": "memorialize", "key": codec_key(dead)})
    world.frames(2)
    assert [m["key"] for m in world.sent("memorialize_failed")] == [codec_key(dead)]
    world.party([lead, dict(dead, hp=30)])                    # the key comes back as another mon
    world.frames(3)
    assert world.hp_of(1) == (30, 0)


@pytest.mark.parametrize("present", [True, False])
def test_gen1_a_failed_memorial_keeps_a_present_key_and_forgets_an_absent_one(world1, present):
    key = g1.codec.key(world1.party()[1])
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world1.step(2)
    assert world1.party()[1]["hp"] == 0
    world1.client.boxes = world1.lua.table(memorialize=lambda self, k, hint: (None, "memorial box full"))
    mons = world1.party()
    if not present:
        world1.seed_party([mons[0]])
    world1.reply({"cmd": "memorialize", "key": key})
    world1.step()
    assert bool(world1.client.dead_keys[key]) is present
    world1.seed_party(mons)
    g1_heal(world1)
    world1.step(3)
    assert (world1.party()[1]["hp"] == 0) is present


def test_gen1_the_hello_sync_replaces_the_dead_set(world1):
    key = g1.codec.key(world1.party()[1])
    world1.reply({"cmd": "force_faint", "key": key, "nickname": "PIDGEY"})
    world1.step(2)
    world1.reply({"cmd": "dead_keys", "keys": []})
    world1.step()
    g1_heal(world1)
    world1.step(3)
    assert world1.party()[1]["hp"] == 7


# ── BOX-MEMORIAL (O-35): a boxed dead partner is buried from its box, not refused ────────────────────
def test_gen2_a_boxed_dead_partner_is_memorialized_from_its_box():
    lead, dead = mon(), mon(species=19, dvs=0x7AAA)
    world = g2.box_world([lead], [dead])
    world.checkpoint_ok = True
    world.reply({"cmd": "force_faint", "key": codec_key(dead)},     # the O-35 pair: faint + memorialize
                {"cmd": "memorialize", "key": codec_key(dead)})
    world.frames(4)
    assert [(m["key"], m["box"]) for m in world.sent("memorialize_done")] == [(codec_key(dead), 13)]
    assert world.sent("memorialize_failed") == []
    assert g2.active(world)[0] == 0 and g2.storage(world, 13)[0:3] == [1, 19, 255]
    assert g2.party_count(world) == 1 and not world.client.dead_keys[codec_key(dead)]


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
