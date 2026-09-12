"""The Lua exchange observer's receipts are exactly what the Python decoder accepts.

The emulator is stubbed (memory bus, registers, hooks); the party/box bytes placed on the
bus are the same synthetic, source-faithful fixtures the decoder tests use. This proves the
wire contract end to end without claiming any live engine behaviour.
"""

import json

import pytest

from server.gen1_npc_exchange_receipt import DATA, validate
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_grant_receipt import CONTEXT, SAVE
from tests.unit.test_gen1_npc_exchange_receipt import receipt

PROFILE = DATA["titles"]["yellow"]


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().sites_json = json.dumps(DATA)
    lua.execute("""
        package.loaded.gen1_npc_exchange_sites=assert(JSON.decode(sites_json))
        profile=JSON.decode(sites_json).titles.yellow;A=profile.addresses;E=profile.engine
        rom={};bus={};hooks={};frame=100;pc=0;regs={SP=0xDFFE,A=0};held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)if k=='PC' then return pc end;return regs[k]end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(name)hooks[name]=nil end}
        function put(address,hexs,domain)for i=1,#hexs,2 do (domain=='ROM' and rom or bus)[address+(i-1)/2]=tonumber(hexs:sub(i,i+1),16)end end
        for _,anchor in ipairs({E.remove,E['return'],E.block,E.trainer_string,E.species_level_check,E.copy_received,E.ot_id_source})do
            put(anchor.rom_offset,anchor.expected_hex,'ROM')
        end
        for _,site in pairs(profile.sites)do
            put(site.call.rom_offset,site.call.expected_hex,'ROM');put(site.dispatch.rom_offset,site.dispatch.expected_hex,'ROM')
            put(site.record_rom_offset,site.record_hex,'ROM');put(site.call.address,site.call.expected_hex)
        end
        put(E.remove.address,E.remove.expected_hex);put(E['return'].address,E['return'].expected_hex)
        observer=require('gen1_npc_exchange_observer').new({variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})
        function load_point(p)
            put(A.wPartyDataStart,p.party_hex);put(A.wBoxDataStart,p.box_hex);put(A.wPlayerName,p.trainer_hex);put(A.wPlayerID,p.player_id_hex)
            put(A.wTradedEnemyMonOTID,p.traded_ot_id_hex);put(A.wInGameTradeMonNick,p.trade_nick_hex)
            for key,name in pairs({map_id='wCurMap',battle_flag='wIsInBattle',which_trade='wWhichTrade',which_pokemon='wWhichPokemon',
                cur_species='wCurPartySpecies',cur_level='wCurEnemyLevel',mon_location='wMonDataLocation',remove_from_box='wRemoveMonFromBox',
                give_species='wInGameTradeGiveMonSpecies',receive_species='wInGameTradeReceiveMonSpecies',current_box='wCurrentBoxNum'})do
                bus[A[name]]=p[key]
            end
        end
        function fire(kind,source_id)
            local anchor=kind=='call' and profile.sites[source_id].call or E[kind]
            pc=anchor.address;bus[A.hLoadedROMBank]=anchor.bank
            hooks['slink-exchange-'..(kind=='call' and 'call-'..source_id or kind)]()
        end
    """)
    return lua


def drive(lua, value, source, *, stop_after=None):
    lua.globals().value_json = json.dumps(value)
    steps = [f"frame=v.call.frame;regs.SP=v.call.sp;regs.A=v.call.a;load_point(v.call.point);fire('call','{source}')",
             "frame=v.remove.frame;regs.SP=v.remove.sp;load_point(v.remove.point);fire('remove')",
             "frame=v['return'].frame;regs.SP=v['return'].sp;load_point(v['return'].point);fire('return')"]
    lua.execute("local v=JSON.decode(value_json)\n" + "\n".join(steps[: {None: 3, "call": 1, "remove": 2}[stop_after]]))


def peeked(lua):
    return json.loads(lua.eval("JSON.encode(observer.peek())"))


def status(lua):
    return lua.globals().observer.status(lua.globals().observer)  # a Lua table: absent keys read as None


@pytest.mark.parametrize("source,slot", [("npc:route_2_trade_house:1", 1), ("npc:underground_path_route_5:9", 0), ("npc:cinnabar_lab_trade_room:7", 2)])
def test_observer_receipt_is_accepted_by_the_decoder_verbatim(probe, source, slot):
    value = receipt("yellow", source, slot=slot)
    drive(probe, value, source)
    rows = peeked(probe)
    assert len(rows) == 1
    assert rows[0] == value  # the observer reproduces the decoder's fixture shape byte for byte
    fact = validate(rows[0], variant="yellow", identity=SAVE, final_sha1=PROFILE["clean_sha1"], **CONTEXT)
    assert fact["source_id"] == source and fact["outgoing"]["slot"] == slot and fact["incoming"]["species_index"] == PROFILE["sites"][source]["delivered_species"]
    assert status(probe)["in_flight"] == 0


def test_declined_dialogues_publish_nothing_and_the_next_selector_supersedes(probe):
    first, second = "npc:route_11_gate_2f:0", "npc:route_2_trade_house:1"
    drive(probe, receipt("yellow", first), first, stop_after="call")
    assert peeked(probe) == [] and status(probe)["in_flight"] == 1 and status(probe)["selected"] == first
    value = receipt("yellow", second)
    drive(probe, value, second)
    rows = peeked(probe)
    assert rows == [value] and status(probe)["in_flight"] == 0
    probe.execute("assert(observer.acknowledge(observer.peek()))")
    assert peeked(probe) == []


def test_hooks_survive_an_unheld_frame_but_publication_needs_the_hold(probe):
    source = "npc:route_2_trade_house:1"
    probe.execute("held=false")
    drive(probe, receipt("yellow", source), source)
    assert status(probe)["failed"] is None and status(probe)["pending"] == 1
    probe.execute("assert(not pcall(observer.peek))")
    probe.execute("held=true")
    assert len(peeked(probe)) == 1


@pytest.mark.parametrize("fault", ["remove_without_call", "double_remove", "return_without_remove", "selector_during_delivery", "context", "rom", "bytes", "anchor"])
def test_observer_latches_on_invalid_sequences_or_lost_context(probe, fault):
    source = "npc:route_2_trade_house:1"
    value = receipt("yellow", source)
    if fault == "remove_without_call":
        probe.globals().value_json = json.dumps(value)
        probe.execute("local v=JSON.decode(value_json);load_point(v.remove.point);fire('remove')")
    elif fault == "double_remove":
        drive(probe, value, source, stop_after="remove")
        probe.execute("local v=JSON.decode(value_json);load_point(v.remove.point);fire('remove')")
    elif fault == "return_without_remove":
        drive(probe, value, source, stop_after="call")
        probe.execute("local v=JSON.decode(value_json);load_point(v['return'].point);fire('return')")
    elif fault == "selector_during_delivery":
        drive(probe, value, source, stop_after="remove")
        probe.execute(f"local v=JSON.decode(value_json);load_point(v.call.point);fire('call','{source}')")
    elif fault == "context":
        probe.execute("scope.context_generation=string.rep('c',32)")
        drive(probe, value, source)
    elif fault == "rom":
        probe.execute("hash=string.rep('e',40)")
        drive(probe, value, source)
    elif fault == "bytes":
        probe.execute("bus[E.remove.address]=0")
        drive(probe, value, source)
    else:
        probe.execute("rom[E.trainer_string.rom_offset]=0x80")
        with pytest.raises(Exception, match="exchange ROM anchor differs"):
            probe.execute("require('gen1_npc_exchange_observer').new({variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})")
        return
    assert status(probe)["failed"]
    probe.execute("assert(not pcall(observer.peek))")
