"""trade_gen3 / trade_decline_gen3 / infopanel_gen3 oracles: a known-positive and a known-negative
control for every assertion (each negative flips exactly one fact the positive holds)."""
import copy
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, "tools"), REPO]
import e2e_duo as duo  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

FIX = os.path.join(REPO, "tests", "fixtures", "gen3")


def _fixture(name):
    with open(os.path.join(FIX, name), "rb") as handle:
        return duo.gen3_decode(handle.read(), rr=True)


FA, FB = _fixture("rr_battle2.sav"), _fixture("rr_battle2_b.sav")
KA, KB = duo.gen3_key(FA[0][1]), duo.gen3_key(FB[0][1])


def _traded():
    a, b = copy.deepcopy(FA), copy.deepcopy(FB)
    a[0][1], b[0][1] = copy.deepcopy(FB[0][1]), copy.deepcopy(FA[0][1])
    return {"a": a, "b": b}


def _row(a, b, status="alive"):
    return [{"a": {"key": a}, "b": {"key": b}, "status": status}]


def _trade(saved, rows, traded=True):
    return duo.gen3_trade_problems(KA, KB, rows, saved, {"a": FA, "b": FB}, traded)


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
