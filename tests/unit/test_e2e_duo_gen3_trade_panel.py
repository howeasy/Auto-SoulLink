"""trade_gen3 / trade_decline_gen3 / infopanel_gen3 oracles: a known-positive and a known-negative
control for every assertion (each negative flips exactly one fact the positive holds)."""
import copy
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, "tools"), REPO]
import e2e_duo as duo  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

FIX = os.path.join(REPO, "tests", "fixtures", "gen3")


def _fixture(name):
    with open(os.path.join(FIX, name), "rb") as handle:
        return duo.gen3_decode(handle.read(), rr=True)


def _raw(name):
    with open(os.path.join(FIX, name), "rb") as handle:
        return handle.read()


FA, FB = _fixture("rr_battle2.sav"), _fixture("rr_battle2_b.sav")
RAW_A, RAW_B = _raw("rr_battle2.sav"), _raw("rr_battle2_b.sav")
KA, KB = duo.gen3_key(FA[0][1]), duo.gen3_key(FB[0][1])


def _oracle_stub(monkeypatch, tmp_path, scenario, links):
    """A minimal RR DuoRun for assert_trade_gen3_saved/assert_trade_decline_gen3_saved: both
    cartridges stay at their fixture bytes (rr_battle2{,_b}.sav) -- exactly what RR-unavailable
    trade must leave behind, nothing moved."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.game = scenario, "gen3_rr"
    run.cfg = dict(duo.SCENARIOS[scenario])
    run.gcfg, run.emus, run.data_dir = dict(duo.GAMES["gen3_rr"]), [], str(tmp_path)
    run._pydec_note = lambda *a, **k: None
    (tmp_path / "links.json").write_text(json.dumps({"links": links}), encoding="utf-8")
    monkeypatch.setattr(run, "_gen3_flushed", lambda inst: RAW_A if inst == "a" else RAW_B)
    monkeypatch.setattr(run, "_gen3_fixture_bytes", lambda inst: RAW_A if inst == "a" else RAW_B)
    run._link_keys = {"a": KA, "b": KB}
    return run


def _unavailable_receipts():
    return {
        "a": ("TALKED npc=(3,3) player=(3,4) facing=Up pi_count=0->1\n"
              'TX trade_request - {"event":"trade_request"}\n'
              "RX msgbox text=Trade unavailable for Radical Red in this build.\n"
              "REFUSED_UNAVAILABLE reason=Trade unavailable for Radical Red in this build.\n"
              f"KEPT {KA} slot=1\n"),
        "b": f"KEPT {KB} slot=1\n",
    }


@pytest.mark.parametrize("scenario", ["trade_gen3", "trade_decline_gen3"])
def test_assert_trade_gen3_saved_passes_on_the_rr_unavailable_refusal(monkeypatch, tmp_path, scenario):
    """PYDEC final cut d9a928d7: both rows FAILed "no show_choices" because the oracle only ever
    expected a completed native trade. RR ABI1 trade is UNAVAILABLE (docs/protocol.md): the
    refusal itself, with nothing moved on either cartridge, is now the passing outcome."""
    run = _oracle_stub(monkeypatch, tmp_path, scenario,
                       [{"a": {"key": KA}, "b": {"key": KB}, "status": "alive"}])
    getattr(run, duo.SCENARIOS[scenario]["oracle"])(_unavailable_receipts())   # must not raise


def test_assert_trade_gen3_saved_still_fails_if_a_trade_actually_completed():
    """A regression guard, not RR's live behaviour: if something DID move (a raw swap, or a future
    build's real trade completing without both sides' native scene), the oracle must still catch
    it -- the unavailable path is a specific, narrow refusal, not a blanket pass."""
    receipts = _unavailable_receipts()
    problems = duo.gen3_trade_problems(
        KA, KB, [{"a": {"key": KB}, "b": {"key": KA}, "status": "alive"}],
        {"a": _traded()["a"], "b": _traded()["b"]}, {"a": FA, "b": FB}, traded=False)
    assert problems   # traded=False against an actually-traded state is a mismatch
    req, forb = duo.gen3_trade_unavailable_chain("a")
    assert duo.gen3_receipt_problems("a", receipts["a"] + "RX apply_trade\n", req, forb)


def _traded():
    a, b = copy.deepcopy(FA), copy.deepcopy(FB)
    a[0][1], b[0][1] = copy.deepcopy(FB[0][1]), copy.deepcopy(FA[0][1])
    return {"a": a, "b": b}


def _row(a, b, status="alive"):
    return [{"a": {"key": a}, "b": {"key": b}, "status": status}]


def _trade(saved, rows, traded=True):
    return duo.gen3_trade_problems(KA, KB, rows, saved, {"a": FA, "b": FB}, traded)


SCENARIO_TRADE_LUA = os.path.join(REPO, "lua", "tests", "duo", "scenario_gen3_trade.lua")


def test_wait_trade_answer_ignores_a_stale_msgbox_from_before_the_request():
    """PHYSICAL live trade_decline_gen3_rr_as_a (card RR-FC-FIX): the walk to the NPC crosses
    Route 1 grass, which can queue an unrelated dead-zone msgbox (server/state.py dz_text, "X is a
    dead zone!") before trade_request is ever sent. The first version of the RR-unavailable fix
    checked ctx.received("msgbox") > 0 / ctx.rx_after(0, ...) -- counting from the start of the
    whole receipt -- and reported that stale notice as the trade refusal; a live rerun of
    trade_decline_gen3 confirmed it: "RX msgbox text=Route 1 is a dead zone!" logged as the
    REFUSED_UNAVAILABLE reason. lua/tests/duo/scenario_gen3_trade.lua's wait_trade_answer(ctx, rx0,
    secs) must only see what arrives strictly after the rx0 snapshot."""
    lupa = pytest.importorskip("lupa")
    with open(SCENARIO_TRADE_LUA, encoding="utf-8") as handle:
        text = handle.read()
    body = re.search(r"^local function wait_trade_answer\(.*?^end$", text, re.M | re.S).group(0)

    def world():
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        lua.execute("""
            rx = { {cmd="msgbox", text="Route 1 is a dead zone!"} }   -- stale, BEFORE trade_request
            polls = 0
            ctx = {}
            function ctx.rx_after(index, pred)
                for i = index + 1, #rx do if pred(rx[i]) then return rx[i], i end end
            end
            -- deterministic stand-in for the real frame-polled wait_until: the REAL answer lands
            -- on the second poll, after the request would actually reach the server
            function ctx.wait_until(pred, secs, what)
                for _ = 1, 4 do
                    if pred() then return true end
                    polls = polls + 1
                    if polls == 1 then
                        rx[#rx + 1] = {cmd="msgbox", text="Trade unavailable for Radical Red in this build."}
                    end
                end
                return pred()
            end
        """)
        fn = lua.execute(body + "\nreturn wait_trade_answer")
        return lua, fn

    lua, fn = world()
    rx0 = len(lua.globals().rx)      # snapshot taken right after trade_request was sent (1 stale entry)
    answer, _idx = fn(lua.globals().ctx, rx0, 120)
    assert (answer["cmd"], answer["text"]) == ("msgbox", "Trade unavailable for Radical Red in this build.")

    # the bug reproduced: an unscoped rx0 (the pre-fix ctx.rx_after(0, ...)) picks the stale notice
    lua2, fn2 = world()
    stale, _idx2 = fn2(lua2.globals().ctx, 0, 120)
    assert (stale["cmd"], stale["text"]) == ("msgbox", "Route 1 is a dead zone!")


def test_trade_positive():
    assert _trade(_traded(), _row(KB, KA)) == []


def test_trade_negative_nothing_moved():
    assert any("saved party" in p for p in _trade({"a": FA, "b": FB}, _row(KB, KA)))


def test_trade_negative_link_not_rekeyed():
    assert any("links.json" in p for p in _trade(_traded(), _row(KA, KB)))


def test_trade_negative_duplicate_in_a_box():
    saved = _traded()
    saved["a"][1][(0, 0)] = copy.deepcopy(FA[0][1])        # A kept a boxed copy of what it gave
    assert any(f"{KA} exists 2x" in p for p in _trade(saved, _row(KB, KA)))


def test_trade_negative_received_record_changed():
    saved = _traded()
    saved["a"][0][1]["ot_name"] = "X"
    assert any("differs from b's record" in p for p in _trade(saved, _row(KB, KA)))


def test_decline_positive_and_negative():
    assert _trade({"a": FA, "b": FB}, _row(KA, KB), traded=False) == []
    assert _trade(_traded(), _row(KA, KB), traded=False)


def _receipt_a(decline=False):
    lines = ["TALKED npc=(3,3) player=(3,4) facing=Up pi_count=0->1",
             'TX trade_request - {"event":"trade_request"}', "RX show_choices",
             'TX menu_result - {"choice":0,"event":"menu_result","token":"t1"}', "RX choose_mon",
             'TX mon_chosen - {"event":"mon_chosen","slot":1,"token":"t1"}']
    if decline:
        return "\n".join(lines + ["RX msgbox text=Your partner declined the trade."])
    return "\n".join(lines + ["RX apply_trade",
                              f"[client] [SLink-gen3] trade: native scene complete; trade_done {KA} -> {KB}",
                              f'TX trade_done - {{"event":"trade_done","new_key":"{KB}","slot":1}}',
                              f"TRADED gave={KA} got={KB} slot=1 species=1324 level=4"])


def test_trade_chain_positive_and_negative():
    req, order, forb = duo.gen3_trade_chain("a", KA, KB, False)
    good = _receipt_a()
    assert duo.gen3_receipt_problems("a", good, req, forb, order) == []
    bad = good.replace(KB, KA)                            # trade_done reports the wrong key
    assert duo.gen3_receipt_problems("a", bad, req, forb, order)
    silent = good.replace("native scene complete", "silent swap after the field never cleared")
    assert duo.gen3_receipt_problems("a", silent, req, forb, order)   # A fell back, no native scene
    req, order, forb = duo.gen3_trade_chain("a", KA, KB, True)
    assert duo.gen3_receipt_problems("a", _receipt_a(True), req, forb, order) == []
    assert duo.gen3_receipt_problems("a", _receipt_a(True) + "\nRX apply_trade", req, forb, order)



def test_trade_unavailable_chain_positive_and_negative():
    """RR ABI1 trade is UNAVAILABLE (docs/protocol.md): A's own refusal (msgbox, never
    show_choices) and both sides' KEPT (nothing moved) -- lua/tests/duo/scenario_gen3_trade.lua's
    new refusal path (card RR-FC-FIX, PYDEC final cut d9a928d7: "no show_choices")."""
    good_a = ("TALKED npc=(3,3) player=(3,4) facing=Up pi_count=0->1\n"
              'TX trade_request - {"event":"trade_request"}\n'
              "RX msgbox text=Trade unavailable for Radical Red in this build.\n"
              "REFUSED_UNAVAILABLE reason=Trade unavailable for Radical Red in this build.\n"
              f"KEPT {KA} slot=1\n")
    req, forb = duo.gen3_trade_unavailable_chain("a")
    assert duo.gen3_receipt_problems("a", good_a, req, forb) == []
    assert duo.gen3_receipt_problems("a", good_a.replace("RX msgbox", "RX show_choices"), req, forb)
    assert duo.gen3_receipt_problems("a", good_a + "RX apply_trade\n", req, forb)
    assert duo.gen3_receipt_problems("a", good_a.replace("REFUSED_UNAVAILABLE reason=", ""), req, forb)

    good_b = f"KEPT {KB} slot=1\n"
    req, forb = duo.gen3_trade_unavailable_chain("b")
    assert duo.gen3_receipt_problems("b", good_b, req, forb) == []
    assert duo.gen3_receipt_problems("b", good_b + "RX show_menu\n", req, forb)
    assert duo.gen3_receipt_problems("b", "", req, forb)   # no KEPT at all


def test_trade_chain_accepts_the_live_order_talk_logged_after_the_send():
    """Live receipt rr_trade_gen3_gen3_rr_as_a_539e0aea_RED.txt: the patch sends trade_request in the
    frame A talks, and the scenario only logs TALKED once it sees pi_count move, so the send line
    precedes TALKED in A's result file. TALKED is a required witness, not an ordering anchor."""
    req, order, forb = duo.gen3_trade_chain("a", KA, KB, False)
    lines = _receipt_a().split("\n")
    live = "\n".join([lines[1], lines[0], *lines[2:]])
    assert duo.gen3_receipt_problems("a", live, req, forb, order) == []
    no_talk = "\n".join(lines[1:])                       # never talked to the NPC at all
    assert duo.gen3_receipt_problems("a", no_talk, req, forb, order)

ROWS = ["DUO0|Treecko|6|22/22|38||", "|Treecko|6|22/22|38||", "DUO1|Mon|4|18/18|38||",
        "|Mon|4|18/18|38||", "Pairs alive|2/2", "Dead zones|0", "Badges|0/8"]


def _line(text):
    raw = b"\xfe".join(codec.encode_name(part, 32)[:-1].rstrip(b"\xff") for part in text.split("\n"))
    return (raw + b"\xff").ljust(32, b"\xff").hex().upper()


def _panel(rows=ROWS, closes=("A", "B"), opened=(3, 4), mutate=None):
    out = ["PANEL_ROWS " + json.dumps(rows)]
    for n in (1, 2):
        out.append(f"PANEL_OPEN {n} opened={opened[0]}->{opened[1]} drawn={opened[1]} sc2=1 lines=6 "
                   f"page=0 pages=2 vram=00000001->00000002")
        for i, row in enumerate(rows[:6]):
            hexed = _line(row.replace("|", "\n"))
            if mutate == (n, i):
                hexed = "BB" + hexed[2:]
            out.append(f"PANEL_LINE {n} {i} {hexed}")
        out.append(f"PANEL_SLOT7 {n} {_line('PAGE 1/2')}")
    out += [f"PANEL_CLOSED {n} button={b} sc2=0" for n, b in enumerate(closes, 1)]
    return "\n".join(out)


def test_panel_positive():
    assert duo.gen3_panel_problems(_panel(), 2) == []
    stale = 'PANEL_ROWS ["No linked pairs yet", "Pairs alive|0/0"]\n'
    assert duo.gen3_panel_problems(stale + _panel(), 2) == []            # the LAST payload counts
    late = _panel() + '\nPANEL_ROWS ["No linked pairs yet"]'
    assert duo.gen3_panel_problems(late, 2) == []                        # ...before the first open


def test_panel_negatives():
    assert duo.gen3_panel_problems(_panel(mutate=(1, 2)), 2)          # a drawn byte differs
    assert duo.gen3_panel_problems(_panel(closes=("A",)), 2)          # B never closed it
    assert duo.gen3_panel_problems(_panel(opened=(3, 3)), 2)          # the row never opened it
    assert duo.gen3_panel_problems(_panel(), 1)                       # rows vs links.json
    assert duo.gen3_panel_problems(_panel(rows=ROWS[:5]), 2)          # 1 page, header says 2
