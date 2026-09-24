"""Client findings of the independent Soul Link invariant review
(docs/gen2/reviews/REVIEW_SOULLINK_INVARIANTS_2026-09-24.md): MAJOR-1, both GB clients.
Harnesses are reused from tests/unit/test_gen2_client.py and tests/unit/test_gen1_client.py.
"""

import random

from tests.unit import test_gen1_client as g1, test_gen2_client as g2
from tests.unit.test_gen2_client import codec_key


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
