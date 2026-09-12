"""The acquisition collector merges the real static, NPC-exchange and wild-encounter observers with capture/grant.

The emulator is stubbed (bus, registers, hooks) exactly as the per-observer tests do; capture and
grant hooks are the collector test's buffer stubs. Every title is driven, since each carries its own
site table. Proves ordering, cursor stability, hold gating and fault latching without an emulator.
"""

import json

import pytest
from lupa.lua54 import LuaError

from server.gen1_capture_receipt import DATA as CAPTURE
from server.gen1_npc_exchange_receipt import DATA as NPC
from server.gen1_static_receipt import DATA as STATIC
from server.gen1_wild_encounter_receipt import DATA as WILD
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_capture_receipt import receipt as capture_receipt
from tests.unit.test_gen1_npc_exchange_receipt import receipt as npc_receipt
from tests.unit.test_gen1_static_receipt import end_receipt, receipt as static_receipt
from tests.unit.test_gen1_wild_encounter import receipt as wild_receipt

SNORLAX = "static:route12_snorlax"
FOSSIL = "npc:cinnabar_lab_fossil_room:3"

LUA = """
    package.loaded.gen1_capture_sites=assert(JSON.decode(capture_json))
    package.loaded.gen1_static_sites=assert(JSON.decode(static_json))
    package.loaded.gen1_npc_exchange_sites=assert(JSON.decode(npc_json))
    package.loaded.gen1_wild_encounter_sites=assert(JSON.decode(wild_json))
    W=package.loaded.gen1_wild_encounter_sites.titles[variant];WA=W.addresses
    S=package.loaded.gen1_static_sites.titles[variant];SA=S.addresses
    N=package.loaded.gen1_npc_exchange_sites.titles[variant];NA=N.addresses;E=N.engine
    hash=S.clean_sha1;Canonical=require('journal_document')
    rom={};bus={};hooks={};frame=100;pc=0;regs={SP=0xDFFE,A=0};held=true;drains=0;nonce=0
    context={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
    memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
    gameinfo={getromhash=function()return hash end}
    emu={framecount=function()return frame end,getregister=function(k)if k=='PC' then return pc end;return regs[k]end}
    event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(name)hooks[name]=nil end}
    function put(address,hexs,domain)for i=1,#hexs,2 do (domain=='ROM' and rom or bus)[address+(i-1)/2]=tonumber(hexs:sub(i,i+1),16)end end
    for _,site in pairs(S.sites)do for _,anchor in ipairs({site.arm,site.writes,site.arm.routine})do put(anchor.rom_offset,anchor.expected_hex,'ROM')end end
    for _,anchor in ipairs({S.began,S.began.prelude,S.battle_end,S.battle_end.reset,S.battle_end.call})do put(anchor.rom_offset,anchor.expected_hex,'ROM')end
    for _,anchor in ipairs({E.remove,E['return'],E.block,E.trainer_string,E.species_level_check,E.copy_received,E.ot_id_source})do
        put(anchor.rom_offset,anchor.expected_hex,'ROM')
    end
    for _,site in pairs(N.sites)do
        put(site.call.rom_offset,site.call.expected_hex,'ROM');put(site.dispatch.rom_offset,site.dispatch.expected_hex,'ROM')
        put(site.record_rom_offset,site.record_hex,'ROM')
    end
    for _,site in pairs(W.sites)do put(site.rom_offset,site.expected_hex,'ROM')end
    function detached(v)return assert(JSON.decode(assert(JSON.encode(v))))end
    capture_pending=JSON.array()
    capture_hooks={status=function()return {pending=#capture_pending}end,peek=function()return detached(capture_pending)end,
        acknowledge=function(expected)
            assert(Canonical.encode(expected)==Canonical.encode(capture_pending),'capture publication cursor differs')
            drains=drains+1;capture_pending=JSON.array();return true
        end,close=function()end}
    grant_hooks={status=function()return {pending=0,in_flight=0}end,peek=function()return JSON.array()end,
        acknowledge=function()return true end,close=function()end}
    collector=require('gen1_acquisition_observers').new({variant=variant,final_sha1=hash,owned=function()return context end,
        held=function()return held end,capture=capture_hooks,grants=grant_hooks,evolution=grant_hooks,
        new_nonce=function()nonce=nonce+1;return string.format('%032x',nonce)end})
    state=collector:initial(frame)
    -- Hook drivers: the site's bytes go on the bus right before its hook fires, as the engine would have them.
    local snames={map_id='wCurMap',cur_opponent='wCurOpponent',cur_level='wCurEnemyLevel',enemy_species2='wEnemyMonSpecies2',
        battle_flag='wIsInBattle',battle_type='wBattleType',sprite_index='wSpriteIndex',engaged_class='wEngagedTrainerClass',
        engaged_set='wEngagedTrainerSet',battle_result='wBattleResult'}
    local nnames={map_id='wCurMap',battle_flag='wIsInBattle',which_trade='wWhichTrade',which_pokemon='wWhichPokemon',
        cur_species='wCurPartySpecies',cur_level='wCurEnemyLevel',mon_location='wMonDataLocation',remove_from_box='wRemoveMonFromBox',
        give_species='wInGameTradeGiveMonSpecies',receive_species='wInGameTradeReceiveMonSpecies',current_box='wCurrentBoxNum'}
    local function fire(prefix,name,anchor,w)
        frame=w.frame;regs.SP=w.sp;regs.A=w.a or 0;pc=anchor.address
        bus[SA.hLoadedROMBank]=anchor.bank;put(anchor.address,anchor.expected_hex)
        hooks[prefix..name]()
    end
    function static_fire(name,w)
        put(SA.wPlayerName,w.point.trainer_hex);put(SA.wPlayerID,w.point.player_id_hex)
        for key,addr in pairs(snames)do bus[SA[addr]]=w.point[key]end
        local anchor=name=='began' and S.began or name=='battle-end' and S.battle_end or S.sites[name:sub(5)].arm
        fire('slink-static-',name,anchor,w)
    end
    function npc_fire(name,w)
        local p=w.point
        put(NA.wPartyDataStart,p.party_hex);put(NA.wBoxDataStart,p.box_hex);put(NA.wPlayerName,p.trainer_hex);put(NA.wPlayerID,p.player_id_hex)
        put(NA.wTradedEnemyMonOTID,p.traded_ot_id_hex);put(NA.wInGameTradeMonNick,p.trade_nick_hex)
        for key,addr in pairs(nnames)do bus[NA[addr]]=p[key]end
        fire('slink-exchange-',name,name:sub(1,5)=='call-' and N.sites[name:sub(6)].call or E[name],w)
    end
    function capture_fire(kind,w)frame=w.frame;local row=detached(w);row.kind=kind;capture_pending[#capture_pending+1]=row end
    local wnames={map_id='wCurMap',cur_opponent='wCurOpponent',species_index='wEnemyMonSpecies2',level='wCurEnemyLevel',
        battle_flag='wIsInBattle',battle_type='wBattleType',battle_result='wBattleResult',link_state='wLinkState'}
    function wild_fire(kind,w)
        local p=w.point
        put(WA.wPlayerName,p.trainer_hex);put(WA.wPlayerID,p.player_id_hex);put(WA.wNumBagItems,p.bag_hex)
        for key,addr in pairs(wnames)do bus[WA[addr]]=p[key]end
        fire('slink-wild-encounter-',kind,W.sites[kind],w)
    end
    function persist_and_drain(prepared)
        assert(store:commit({source=prepared.state,receipts=prepared.receipts}))
        state=prepared.state;assert(collector:drain(prepared))
    end
"""


@pytest.fixture(params=["red", "blue", "yellow"])
def probe(request, runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().variant = request.param
    lua.globals().capture_json = json.dumps(CAPTURE)
    lua.globals().static_json = json.dumps(STATIC)
    lua.globals().npc_json = json.dumps(NPC)
    lua.globals().wild_json = json.dumps(WILD)
    lua.execute(LUA)
    return lua


def at(value, frame):
    """A receipt fixture with every witness moved to one frame (the returned physical step)."""
    for witness in value.values():
        if isinstance(witness, dict) and "frame" in witness:
            witness["frame"] = frame
    return value


def fire(lua, calls):
    for fn, name, witness in calls:
        lua.globals().w_json = json.dumps(witness)
        lua.execute(f"{fn}('{name}',JSON.decode(w_json))")


def origin(lua, variant, frame):
    value = at(static_receipt(variant, SNORLAX), frame)
    fire(lua, [("static_fire", "arm-" + SNORLAX, value["arm"]), ("static_fire", "began", value["began"])])
    return value


def battle_end(lua, variant, frame):
    value = at(end_receipt(variant, SNORLAX), frame)
    fire(lua, [("static_fire", "battle-end", value["end"])])
    return value


def exchange(lua, variant, frame, *, upto=3):
    value = at(npc_receipt(variant, FOSSIL), frame)
    steps = [("npc_fire", "call-" + FOSSIL, value["call"]), ("npc_fire", "remove", value["remove"]), ("npc_fire", "return", value["return"])]
    fire(lua, steps[:upto])
    return value


def capture(lua, variant, frame, kind):
    value = capture_receipt(variant, party_count=0, box_count=0)
    fire(lua, [("capture_fire", kind, at(value, frame)["begin" if kind == "party_begin" else "end"])])


def wild(lua, variant, frame, kind):
    """One wild boundary hook (`begin`/`end`); returns the witness the observer should publish."""
    value = wild_receipt(variant, kind, frame)
    fire(lua, [("wild_fire", kind, value["witness"])])
    return value["witness"]


def wild_pending(lua):
    return lua.globals().collector.status(lua.globals().collector).wild.pending


def rows(lua, prepared="prepared"):
    return json.loads(lua.eval(f"JSON.encode({prepared}.receipts)"))


def pending(lua):
    s = lua.globals().collector.status(lua.globals().collector)
    return [s.capture.pending, s.static.pending, s.npc_exchange.pending]


def test_mixed_frame_is_one_list_in_hook_order_and_a_repeated_peek_is_identical(probe):
    lua, variant = probe, probe.globals().variant
    lua.execute("assert(collector:ready(state))")
    capture(lua, variant, 101, "party_begin")
    lua.execute("prepared=collector:prepare(state);assert(#prepared.receipts==0);persist_and_drain(prepared)")
    lua.execute("assert(collector:ready(state))")
    capture(lua, variant, 102, "party_end")  # hook order: capture return, static began, battle end, exchange delivery
    static = origin(lua, variant, 102)
    end = battle_end(lua, variant, 102)
    trade = exchange(lua, variant, 102)
    assert pending(lua) == [1, 2, 1]
    lua.execute("prepared=collector:prepare(state);again=collector:prepare(state)")
    merged = rows(lua)
    assert [row["kind"] for row in merged] == ["capture", "static_origin", "static_battle_end", "npc_exchange"]
    assert merged[1]["receipt"] == static and merged[2]["receipt"] == end and merged[3]["receipt"] == trade
    assert merged[0]["receipt"]["receipt"]["end"]["frame"] == 102
    assert rows(lua, "again") == merged and pending(lua) == [1, 2, 1]  # peek moves no cursor
    assert lua.eval("Canonical.encode(prepared.state)==Canonical.encode(again.state)")
    assert lua.eval("#prepared.static==2 and #prepared.npc_exchange==1")
    lua.execute("persist_and_drain(again);assert(collector:ready(state))")
    assert pending(lua) == [0, 0, 0] and lua.globals().state.frame == 102
    status = lua.globals().collector.status(lua.globals().collector)
    assert status.static.live is False and status.npc_exchange.in_flight == 0 and status.failed is None


def test_each_frame_acknowledges_its_own_rows_and_later_rows_keep_their_order(probe):
    lua, variant = probe, probe.globals().variant
    origin(lua, variant, 101)
    lua.execute("prepared=collector:prepare(state)")
    assert [row["kind"] for row in rows(lua)] == ["static_origin"]
    lua.execute("persist_and_drain(prepared);assert(collector:ready(state))")
    battle_end(lua, variant, 102)
    exchange(lua, variant, 102)
    lua.execute("prepared=collector:prepare(state)")
    assert [row["kind"] for row in rows(lua)] == ["static_battle_end", "npc_exchange"]
    lua.execute("persist_and_drain(prepared);assert(collector:ready(state))")
    lua.execute("frame=103;prepared=collector:prepare(state)")
    assert rows(lua) == [] and pending(lua) == [0, 0, 0]


def test_stale_or_tampered_acknowledgements_are_refused_and_keep_the_buffers(probe):
    lua, variant = probe, probe.globals().variant
    origin(lua, variant, 101)
    battle_end(lua, variant, 101)
    exchange(lua, variant, 101)
    lua.execute("prepared=collector:prepare(state);tampered=detached(prepared);tampered.static[2]=nil")
    with pytest.raises(LuaError, match="static publication cursor differs"):
        lua.execute("collector:drain(tampered)")
    assert pending(lua)[1:] == [2, 1]
    lua.execute("persist_and_drain(prepared)")
    assert pending(lua) == [0, 0, 0]
    with pytest.raises(LuaError, match="publication cursor differs"):
        lua.execute("collector:drain(prepared)")  # duplicate: the cursor already moved
    lua.execute("assert(collector:ready(state))")


def test_unheld_frames_still_record_hooks_but_publication_waits_for_the_hold(probe):
    lua, variant = probe, probe.globals().variant
    lua.execute("held=false")
    origin(lua, variant, 101)
    exchange(lua, variant, 101)
    assert pending(lua) == [0, 1, 1]
    with pytest.raises(LuaError, match="lost held ownership"):
        lua.execute("collector:prepare(state)")
    lua.execute("held=true;prepared=collector:prepare(state)")
    assert [row["kind"] for row in rows(lua)] == ["static_origin", "npc_exchange"]
    lua.execute("persist_and_drain(prepared)")


@pytest.mark.parametrize("source", ["static", "npc_exchange", "wild"])
def test_an_observer_fault_latches_the_collector(probe, source):
    lua, variant = probe, probe.globals().variant
    if source == "wild":
        wild(lua, variant, 101, "begin")
        lua.execute("pc=0;hooks['slink-wild-encounter-begin']()")  # the hook fires off its anchored instruction
        expected = "wild encounter instruction changed"
    elif source == "static":
        origin(lua, variant, 101)
        value = at(static_receipt(variant, SNORLAX), 101)
        fire(lua, [("static_fire", "arm-" + SNORLAX, value["arm"])] * 2)  # a second arm before any began
        expected = "overlapping static arm"
    else:
        exchange(lua, variant, 101, upto=2)
        exchange(lua, variant, 101, upto=2)  # a second selector inside one delivery
        expected = "exchange selector during a delivery"
    status = lua.globals().collector.status(lua.globals().collector)
    assert expected in status[source].failed
    for call in ("collector:prepare(state)", "collector:ready(state)"):
        with pytest.raises(LuaError, match="acquisition hook failed or closed"):
            lua.execute(call)
    assert lua.globals().drains == 0


def test_battle_end_is_published_only_while_an_origin_is_live(probe):
    lua, variant = probe, probe.globals().variant
    battle_end(lua, variant, 101)  # a random encounter's end: nobody's
    lua.execute("prepared=collector:prepare(state)")
    assert rows(lua) == []
    lua.execute("persist_and_drain(prepared)")
    origin(lua, variant, 102)
    lua.execute("prepared=collector:prepare(state);persist_and_drain(prepared)")
    assert lua.globals().collector.status(lua.globals().collector).static.live is True
    battle_end(lua, variant, 103)
    lua.execute("prepared=collector:prepare(state)")
    assert [row["kind"] for row in rows(lua)] == ["static_battle_end"]
    lua.execute("persist_and_drain(prepared)")
    battle_end(lua, variant, 104)
    lua.execute("prepared=collector:prepare(state)")
    assert rows(lua) == [] and lua.globals().collector.status(lua.globals().collector).static.live is False


def test_collector_owns_and_closes_the_observers_it_constructed(probe):
    lua = probe
    lua.execute("collector:close()")
    status = lua.globals().collector.status(lua.globals().collector)
    assert status.static.closed is True and status.npc_exchange.closed is True and status.wild.closed is True
    assert lua.eval("next(hooks)") is None  # every static and exchange hook unregistered
    with pytest.raises(LuaError, match="acquisition observers closed"):
        lua.execute("collector:prepare(state)")


def test_wild_boundaries_merge_after_the_other_producers_and_drain_with_their_own_frame(probe):
    """One prepare covers one returned frame, so cross-producer order inside it is collection order
    (capture, grant, static, exchange, wild); across frames each wild row drains with its frame."""
    lua, variant = probe, probe.globals().variant
    begin = wild(lua, variant, 101, "begin")
    assert wild_pending(lua) == 1 and pending(lua) == [0, 0, 0]
    with pytest.raises(LuaError, match="not durably drained"):
        lua.execute("frame=100;collector:ready(state)")  # back on the held frame: the undrained wild row still blocks
    lua.execute("frame=101;prepared=collector:prepare(state);again=collector:prepare(state)")
    merged = rows(lua)
    assert [(row["kind"], row["receipt"]["kind"]) for row in merged] == [("wild_begin", "begin")]
    assert merged[0]["receipt"]["witness"] == begin and merged[0]["receipt"]["schema"] == "rby-wild-encounter-receipt-v1"
    assert rows(lua, "again") == merged and wild_pending(lua) == 1  # peek moves no cursor
    assert lua.eval("#prepared.wild==1 and Canonical.encode(prepared.state)==Canonical.encode(again.state)")
    lua.execute("tampered=detached(prepared);tampered.wild[1]=nil")
    with pytest.raises(LuaError, match="wild receipts changed before durable acknowledgement"):
        lua.execute("collector:drain(tampered)")
    assert wild_pending(lua) == 1
    lua.execute("persist_and_drain(prepared);assert(collector:ready(state))")
    assert wild_pending(lua) == 0 and lua.globals().state.frame == 101
    with pytest.raises(LuaError, match="publication cursor differs|wild receipts changed"):
        lua.execute("collector:drain(prepared)")  # duplicate: the cursor already moved
    static = origin(lua, variant, 102)
    battle_end(lua, variant, 102)
    exchange(lua, variant, 102)
    end = wild(lua, variant, 102, "end")
    assert wild_pending(lua) == 1 and pending(lua) == [0, 2, 1]
    lua.execute("prepared=collector:prepare(state)")
    merged = rows(lua)
    assert [row["kind"] for row in merged] == ["static_origin", "static_battle_end", "npc_exchange", "wild_end"]
    assert merged[0]["receipt"] == static and merged[3]["receipt"]["witness"] == end and merged[3]["receipt"]["kind"] == "end"
    lua.execute("persist_and_drain(prepared);assert(collector:ready(state))")
    assert wild_pending(lua) == 0 and pending(lua) == [0, 0, 0]
    lua.execute("frame=103;prepared=collector:prepare(state)")
    assert rows(lua) == [] and lua.eval("#prepared.wild") == 0
    status = lua.globals().collector.status(lua.globals().collector)
    assert status.wild.failed is None and status.wild.closed is False and status.failed is None
