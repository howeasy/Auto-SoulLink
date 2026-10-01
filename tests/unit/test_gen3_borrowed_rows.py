"""MODEL checks against real DuoRun helpers, existing RR bytes and actual ROM. No new game fixture."""
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
import e2e_duo as h
from server.adapters import gen3_codec as c
from tools import gen3_borrowed_rows as d


def runner(case):
    r=object.__new__(h.DuoRun)
    r.game="gen3_rr";r.gcfg=h.GAMES["gen3_rr"];r.scenario="borrowed_party_"+case+"_gen3"
    r.cfg=dict(d.ROWS[r.scenario]);r.attempt=1
    a,b=r._gen3_fixture_saved("a"),r._gen3_fixture_saved("b")
    r._link_keys={"a":h.gen3_key(a[0][1]),"b":h.gen3_key(b[0][1])}
    r._gen3_flushed=lambda pid:r._gen3_fixture_bytes(pid)
    r._gen3_flush_boundary=lambda:None # no emulator; saved bytes are the existing fixture
    r._links_json=lambda:[{"status":"alive","a":{"key":r._link_keys["a"]},"b":{"key":r._link_keys["b"]}}]
    r._pydec_note=lambda text:None
    return r


def receipts(r):
    image=r._gen3_fixture_bytes("a")
    parsed=c.parse_flash(image,cfru=True);count=parsed["sb1"][0x34]
    raw=[parsed["sb1"][0x38+i*100:0x38+(i+1)*100].hex() for i in range(count)]
    facts=d.own_facts(r)
    values=[("BORROW_BASELINE",dict(key=r._link_keys["a"],raw_party_hex=raw,rom_sha1=facts["rom_sha1"])),
            ("BORROW_SIGNAL",dict(kind="borrowed_party_begin")),
            ("BORROW_BATTLE",dict(outcome=2)),("BORROW_SIGNAL",dict(kind="borrowed_party_end")),
            ("BORROW_RESTORED",dict(key=r._link_keys["a"],borrowed=False))]
    return {"a":"\n".join(tag+" "+json.dumps(value) for tag,value in values)+"\nSAVE_WITNESS borrowed counter=4->5\n",
            "b":"RESULT: PASS (idle peer; no save)\n"}


def test_actual_duorun_rom_route_and_both_rows():
    for case in ("menu","battle"):
        r=runner(case);f=d.own_facts(r)
        assert f["arrival"]==[4,8] and len(f["paths"]["city"])==13 and len(f["paths"]["school"])==6
        assert f["menu_option"]==(0 if case=="menu" else 3)
        assert r.cfg["no_save"]==("b",)


def test_actual_saved_codec_accepts_unchanged_borrow_battle_and_rejects_missing_restore():
    r=runner("battle");texts=receipts(r)
    d.saved_oracle(r,texts)
    texts["a"]=texts["a"].replace('"kind": "borrowed_party_end"','"kind": "unrelated"')
    with pytest.raises(RuntimeError,match="begin/end"):d.saved_oracle(r,texts)


def test_borrow_oracle_rejects_spurious_own_faint_and_wrong_link():
    r=runner("battle");texts=receipts(r)
    texts["a"]+='TX faint '+r._link_keys["a"]+' '+json.dumps(dict(event="faint",key=r._link_keys["a"]))+'\n'
    with pytest.raises(RuntimeError,match="own faint"):d.saved_oracle(r,texts)
    texts=receipts(r);r._links_json=lambda:[]
    with pytest.raises(RuntimeError,match="alive linked"):d.saved_oracle(r,texts)


def test_lua_draft_parses_and_uses_no_game_data_write_apis():
    from lupa import LuaRuntime
    source=(ROOT / "lua/tests/duo/scenario_gen3_borrowed.lua").read_text()
    assert LuaRuntime().execute("return type(assert(load(...)))",source)=="function"
    assert "memory.write" not in source and "ctx.lose_active" not in source


def test_menu_oracle_cannot_accept_saved_healthy_target_as_command_success():
    r=runner("menu");texts=receipts(r);r._links_json=lambda:[]
    texts["a"]=texts["a"].replace("SAVE_WITNESS ","BORROW_HELD "+json.dumps(dict(frames=120,party_write_count=0,hidden_ticks=4,start_frame=100,end_frame=220))+"\nSAVE_WITNESS ")
    with pytest.raises(RuntimeError,match="ownHP0"):d.saved_oracle(r,texts)
