"""trade_gen3 / trade_decline_gen3 / infopanel_gen3 oracles: a known-positive and a known-negative
control for every assertion (each negative flips exactly one fact the positive holds)."""
import copy
import hashlib
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
MODEL_ROM_SHA1 = {"a": hashlib.sha1(RAW_A).hexdigest(),
                  "b": hashlib.sha1(RAW_B).hexdigest()}


def _oracle_stub(monkeypatch, tmp_path, scenario, links):
    """A minimal RR DuoRun for assert_trade_gen3_saved/assert_trade_decline_gen3_saved, both
    cartridges at their fixture bytes (rr_battle2{,_b}.sav): nothing moved."""
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario, run.game = scenario, "gen3_rr"
    run.cfg = dict(duo.SCENARIOS[scenario])
    run.gcfg, run.emus, run.data_dir = dict(duo.GAMES["gen3_rr"]), [], str(tmp_path)
    run._pydec_note = lambda *a, **k: None
    (tmp_path / "links.json").write_text(json.dumps({"links": links}), encoding="utf-8")
    monkeypatch.setattr(run, "_gen3_flushed", lambda inst: RAW_A if inst == "a" else RAW_B)
    monkeypatch.setattr(run, "_gen3_fixture_bytes", lambda inst: RAW_A if inst == "a" else RAW_B)
    monkeypatch.setattr(run, "_gen3_rom", lambda inst: f"tests/fixtures/gen3/rr_battle2{'_b' if inst == 'b' else ''}.sav")
    run._link_keys = {"a": KA, "b": KB}
    return run


REFUSAL = "Trade unavailable for Radical Red in this build."


def _refusal_receipts():
    return {
        "a": ("TALKED npc=(3,3) player=(3,4) facing=Up pi_count=0->1\n"
              'TX trade_request - {"event":"trade_request"}\n'
              f"RX msgbox text={REFUSAL}\n"
              f"REFUSED_UNAVAILABLE reason={REFUSAL}\n"
              f"KEPT {KA} slot=1\n"),
        "b": f"KEPT {KB} slot=1\n",
    }


@pytest.mark.parametrize("scenario", ["trade_gen3", "trade_decline_gen3"])
def test_the_rr_refusal_never_passes_a_trade_row(monkeypatch, tmp_path, scenario):
    """RR-DURABLE (OMP cx-bfa0a588 F2/F3/F5): the durable build trades, so the named refusal an
    old-UPS client gets is a FAIL on both rows, even with nothing moved on either cartridge."""
    run = _oracle_stub(monkeypatch, tmp_path, scenario,
                       [{"a": {"key": KA}, "b": {"key": KB}, "status": "alive"}])
    with pytest.raises(RuntimeError, match="REFUSED_UNAVAILABLE|show_choices"):
        getattr(run, duo.SCENARIOS[scenario]["oracle"])(_refusal_receipts())


@pytest.mark.parametrize("scenario", ["trade_gen3", "trade_decline_gen3"])
def test_the_two_rows_are_distinct_again(monkeypatch, tmp_path, scenario):
    """F2: a decline receipt set passes only trade_decline_gen3 (both saves at their fixture
    bytes), and a traded chain never passes trade_decline_gen3's forbidden list."""
    run = _oracle_stub(monkeypatch, tmp_path, scenario,
                       [{"a": {"key": KA}, "b": {"key": KB}, "status": "alive"}])
    receipts = {"a": _receipt_a(True) + f"\nKEPT {KA} slot=1", "b": _receipt_b(True) + f"\nKEPT {KB} slot=1"}
    oracle = getattr(run, duo.SCENARIOS[scenario]["oracle"])
    if scenario == "trade_decline_gen3":
        oracle(receipts)                                                  # must not raise
        with pytest.raises(RuntimeError, match="forbidden"):
            oracle({"a": _receipt_a(), "b": _receipt_b()})
    else:
        with pytest.raises(RuntimeError, match="apply_prepare"):
            oracle(receipts)


def _traded():
    a, b = copy.deepcopy(FA), copy.deepcopy(FB)
    a[0][1], b[0][1] = copy.deepcopy(FB[0][1]), copy.deepcopy(FA[0][1])
    return {"a": a, "b": b}


def _row(a, b, status="alive"):
    return [{"a": {"key": a}, "b": {"key": b}, "status": status}]


def _trade(saved, rows, traded=True, preimages=None):
    return duo.gen3_trade_problems(KA, KB, rows, saved, {"a": FA, "b": FB}, traded, preimages)


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
            rx = { {cmd="msgbox", text="Route 1 is a dead zone!", phone="dead_zone"} }   -- stale
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



def test_wait_trade_answer_never_takes_a_fresh_dead_zone_notice_for_the_refusal():
    """OMP cx-bfa0a588 F1: the refusal is typed. A dead-zone notice that lands AFTER rx0 (the walk
    queued it late) carries phone="dead_zone" and must not answer the request; the untagged
    server refusal, or show_choices, does."""
    lupa = pytest.importorskip("lupa")
    with open(SCENARIO_TRADE_LUA, encoding="utf-8") as handle:
        text = handle.read()
    body = re.search(r"^local function wait_trade_answer\(.*?^end$", text, re.M | re.S).group(0)
    for late, want in ((None, None), ({"cmd": "show_choices"}, "show_choices")):
        lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        lua.execute("""
            rx = {}
            ctx = {}
            function ctx.rx_after(index, pred)
                for i = index + 1, #rx do if pred(rx[i]) then return rx[i], i end end
            end
            function ctx.wait_until(pred, secs, what)
                rx[#rx + 1] = {cmd="msgbox", text="Route 1 is a dead zone!", phone="dead_zone"}
                if late then rx[#rx + 1] = late end
                return pred()
            end
        """)
        lua.globals().late = lua.table_from(late) if late else None
        fn = lua.execute(body + "\nreturn wait_trade_answer")
        answer = fn(lua.globals().ctx, 0, 120)
        answer = answer[0] if isinstance(answer, tuple) else answer
        assert (answer["cmd"] if answer else None) == want


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


def test_trade_oracle_accepts_naturally_learned_donor_move_before_transfer():
    donor = copy.deepcopy(FA[0][1])
    donor["level"], donor["experience"] = 5, 153
    donor["moves"] = [33, 230, 71, 0]
    saved = _traded()
    saved["b"][0][1] = copy.deepcopy(donor)  # native transfer preserved A's live record
    assert _trade(saved, _row(KB, KA), preimages={"a": [donor], "b": [FB[0][1]]}) == []
    saved["b"][0][1]["moves"] = [33, 230, 45, 0]
    assert any("moves" in p for p in _trade(saved, _row(KB, KA),
                                           preimages={"a": [donor], "b": [FB[0][1]]}))


def test_decline_positive_and_negative():
    assert _trade({"a": FA, "b": FB}, _row(KA, KB), traded=False) == []
    assert _trade(_traded(), _row(KA, KB), traded=False)
    saved = {"a": copy.deepcopy(FA), "b": copy.deepcopy(FB)}
    saved["a"][0][1]["moves"] = [33, 230, 71, 0]
    assert any("declined trade changed" in p for p in _trade(
        saved, _row(KA, KB), traded=False,
        preimages={"a": [FA[0][1]], "b": [FB[0][1]]}))


def _preimage(side):
    mon = (FA if side == "a" else FB)[0][1]
    raw = codec.encode_party_mon(mon, rr=True)
    row = {"token": "t1", "player": side, "key": KA if side == "a" else KB,
           "slot": 1, "frame": 100, "counter": 4,
           "rom_sha1": MODEL_ROM_SHA1[side],
           "raw_hex": raw.hex().upper()}
    return "TRADE_PREIMAGE " + json.dumps(row, separators=(",", ":"))


def test_trade_preimage_binding_rejects_missing_wrong_and_late_receipts():
    good = {"a": _receipt_a(), "b": _receipt_b()}
    def problems(rows):
        return duo.gen3_trade_preimages(rows, {"a": KA, "b": KB},
                                        {"a": FA, "b": FB}, MODEL_ROM_SHA1)[1]
    assert problems(good) == []
    missing = dict(good, a=good["a"].replace(_preimage("a") + "\n", ""))
    assert problems(missing)
    wrong = dict(good, b=good["b"].replace(KB, KA))
    assert problems(wrong)
    late = dict(good, a=good["a"].replace(_preimage("a") + "\n", "") + "\n" + _preimage("a"))
    assert problems(late)
    # A replayed send after a late marker must not hide the first native menu send.
    b_after_first_send = good["b"].replace(_preimage("b") + "\n", "")
    first_send = 'TX menu_result - {"choice":1,"event":"menu_result","token":"t1"}'
    b_after_first_send = b_after_first_send.replace(first_send, first_send + "\n" + _preimage("b")
                                                   + "\n" + first_send)
    assert problems(dict(good, b=b_after_first_send))


def test_lua_trade_preimage_captures_raw_keyed_party_before_native_input():
    lupa = pytest.importorskip("lupa")
    from tests.unit.gen3_world import lua_to_py

    source = open(SCENARIO_TRADE_LUA, encoding="utf-8").read()
    body = re.search(r"(?ms)^local function trade_preimage\(.*?^end$", source).group(0)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    raw = codec.encode_party_mon(FA[0][1], rr=True)
    base, count_at = 0x02010000, 0x02000080  # fake bus addresses, not product pins
    lua.globals().memory = lua.table(read_u8=lambda addr, domain=None:
                                     2 if addr == count_at else raw[addr - base - 100]
                                     if base + 100 <= addr < base + 200 else 0)
    lua.globals().gameinfo = lua.table(getromhash=lambda: MODEL_ROM_SHA1["a"])
    lua.globals().emu = lua.table(framecount=lambda: 123)
    capture = lua.execute('local function u8(a) return memory.read_u8(a, "System Bus") end\n'
                          + body + "\nreturn trade_preimage")
    rows = []
    ctx = lua.table(player="a", find=lambda key: lua.table(slot=1) if key == KA else None,
                    party_base=lambda: base,
                    G=lua.table(flash_domain=lambda: "CART", save_counter=lambda domain: 4),
                    jlog=lambda tag, row: rows.append((tag, lua_to_py(row))))
    assert capture(ctx, lua.table(PARTY_COUNT_ADDR=count_at), KA, 1, "t1") is True
    tag, row = rows[0]
    assert tag == "TRADE_PREIMAGE" and row["token"] == "t1" and row["slot"] == 1
    assert bytes.fromhex(row["raw_hex"]) == raw
    assert duo.gen3_key(codec.decode_party_mon(bytes.fromhex(row["raw_hex"]), rr=True)) == KA
    moved = lua.table(player="a", find=lambda key: lua.table(slot=0), party_base=lambda: base,
                      G=ctx.G, jlog=ctx.jlog)
    assert capture(moved, lua.table(PARTY_COUNT_ADDR=count_at), KA, 1, "t1")[0] is False


def _receipt_a(decline=False):
    lines = ["TALKED npc=(3,3) player=(3,4) facing=Up pi_count=0->1",
             'TX trade_request - {"event":"trade_request"}', "RX show_choices",
             'TX menu_result - {"choice":0,"event":"menu_result","token":"t1"}', "RX choose_mon",
             _preimage("a"),
             'TX mon_chosen - {"event":"mon_chosen","slot":1,"token":"t1"}']
    if decline:
        return "\n".join(lines + ["RX msgbox text=Your partner declined the trade."])
    return "\n".join(lines + ["RX apply_prepare", 'TX apply_ready - {"event":"apply_ready","ok":true,"token":"t1"}',
                              "RX apply_trade",
                              f'TX trade_done - {{"event":"trade_done","new_key":"{KB}","slot":1}}',
                              "RX msgbox text=Traded Treecko for Mon!",
                              f"TRADED gave={KA} got={KB} slot=1 species=1324 level=4"])


def _receipt_b(decline=False):
    lines = ["RX show_menu", _preimage("b"),
             f'TX menu_result - {{"choice":{0 if decline else 1},"event":"menu_result","token":"t1"}}']
    if decline:
        return "\n".join(lines + ["RX msgbox text=Trade declined.", "DECLINED choice=0"])
    return "\n".join(lines + ["RX apply_prepare", 'TX apply_ready - {"event":"apply_ready","ok":true,"token":"t1"}',
                              "RX apply_trade",
                              f'TX trade_done - {{"event":"trade_done","new_key":"{KA}","slot":1}}',
                              "RX msgbox text=Traded Mon for Treecko!",
                              f"TRADED gave={KB} got={KA} slot=1 species=1 level=4"])


def test_trade_chain_positive_and_negative():
    """Each negative flips one fact of the durable round the positive holds."""
    for inst, good in (("a", _receipt_a()), ("b", _receipt_b())):
        req, order, forb = duo.gen3_trade_chain(inst, KA, KB, False)
        assert duo.gen3_receipt_problems(inst, good, req, forb, order) == []
        mine, theirs = (KA, KB) if inst == "a" else (KB, KA)
        for bad in (good.replace(f'"new_key":"{theirs}"', f'"new_key":"{mine}"'),   # wrong key reported
                    good.replace("RX apply_prepare\n", ""),                         # no durable prepare
                    good.replace('"ok":true', '"ok":false'),                          # prepare refused
                    good.replace('"slot":1}', '"slot":1,"uncertain":true}'),         # uncertain apply
                    good.replace("RX msgbox text=Traded", "RX msgbox text=Nope"),    # no server commit
                    good + f"\nREFUSED_UNAVAILABLE reason={REFUSAL}",
                    good + "\n[client] [SLink-gen3] apply_trade refused: durable native trade unavailable"):
            assert duo.gen3_receipt_problems(inst, bad, req, forb, order), bad
    # live RR-DURABLE trade_gen3: TRADED (this side's read-back) before the server's notice
    for inst, good in (("a", _receipt_a()), ("b", _receipt_b())):
        req, order, forb = duo.gen3_trade_chain(inst, KA, KB, False)
        lines = good.split("\n")
        live = "\n".join(lines[:-2] + [lines[-1], lines[-2]])
        assert duo.gen3_receipt_problems(inst, live, req, forb, order) == []
        early = "\n".join([lines[-2]] + lines[:-2] + [lines[-1]])       # notice before trade_done
        assert duo.gen3_receipt_problems(inst, early, req, forb, order)
    for inst, good in (("a", _receipt_a(True)), ("b", _receipt_b(True))):
        req, order, forb = duo.gen3_trade_chain(inst, KA, KB, True)
        assert duo.gen3_receipt_problems(inst, good, req, forb, order) == []
        for extra in ("RX apply_prepare", "RX apply_trade", 'TX trade_done - {"event":"trade_done"}'):
            assert duo.gen3_receipt_problems(inst, good + "\n" + extra, req, forb, order), extra


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
