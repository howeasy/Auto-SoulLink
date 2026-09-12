"""The Lua grant observer's receipts are exactly what the Python decoder accepts.

The emulator is stubbed (memory bus, registers, hooks); the party/box bytes placed on the
bus are the same source-faithful fixtures the decoder tests use. This proves the wire
contract end to end without claiming any live engine behaviour.
"""

import json

import pytest

from server.gen1_grant_receipt import DATA, validate
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_grant_receipt import CONTEXT, SAVE, receipt

SITES = DATA["titles"]["yellow"]["sites"]


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().sites_json = json.dumps(DATA)
    lua.execute("""
        package.loaded.gen1_grant_sites=assert(JSON.decode(sites_json))
        profile=JSON.decode(sites_json).titles.yellow;A=profile.addresses
        rom={};bus={};hooks={};frame=100;pc=0;bank=0;regs={SP=0xDFFE,B=0,C=0,F=0};held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)if k=='PC' then return pc end;return regs[k]end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(name)hooks[name]=nil end}
        function put(address,hexs,domain)for i=1,#hexs,2 do (domain=='ROM' and rom or bus)[address+(i-1)/2]=tonumber(hexs:sub(i,i+1),16)end end
        for _,site in pairs(profile.sites)do
            for _,anchor in ipairs({site.call,site['return'],site.purchase and site.purchase.paid})do
                put(anchor.rom_offset,anchor.expected_hex,'ROM');put(anchor.address,anchor.expected_hex)
            end
        end
        observer=require('gen1_grant_observer').new({variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})
        function load_point(p)
            put(A.wPartyDataStart,p.party_hex);put(A.wBoxDataStart,p.box_hex);put(A.wPlayerName,p.trainer_hex);put(A.wPlayerID,p.player_id_hex)
            put(A.wPlayerCoins,p.coins_hex);put(A.wPrize1,p.prizes_hex);put(A.wPrize1Price,p.prices_hex)
            for key,name in pairs({map_id='wCurMap',battle_flag='wIsInBattle',cur_species='wCurPartySpecies',cur_level='wCurEnemyLevel',
                mon_location='wMonDataLocation',added_to_party='wAddedToParty',current_box='wCurrentBoxNum',which_prize='wWhichPrize',
                prize_window='wWhichPrizeWindow'})do bus[A[name]]=p[key]end
        end
        function fire(source_id,kind)
            local site=profile.sites[source_id];local anchor=kind=='paid' and site.purchase.paid or site[kind]
            pc=anchor.address;bus[A.hLoadedROMBank]=anchor.bank
            hooks['slink-grant-'..kind..'-'..source_id]()
        end
    """)
    return lua


def drive(lua, value, source):
    lua.globals().value_json = json.dumps(value)
    lua.execute(f"""
        local v=JSON.decode(value_json)
        frame=v.call.frame;regs.B=v.call.b;regs.C=v.call.c;load_point(v.call.point);fire('{source}','call')
        frame=v['return'].frame;regs.F=v['return'].flags;load_point(v['return'].point);fire('{source}','return')
        if v.paid then frame=v.paid.frame;load_point(v.paid.point);fire('{source}','paid') end
    """)


def peeked(lua):
    return json.loads(lua.eval("JSON.encode(observer.peek())"))


@pytest.mark.parametrize("source,slot,delivery", [("grant:eevee:0", None, "party"), ("grant:lapras:0", None, "box"),
                                                  ("grant:game_corner_purchase:0", 4, "party"), ("grant:yellow_squirtle:0", None, "party")])
def test_observer_receipt_is_accepted_by_the_decoder_verbatim(probe, source, slot, delivery):
    value = receipt("yellow", source, slot=slot, delivery=delivery)
    drive(probe, value, source)
    rows = peeked(probe)
    assert len(rows) == 1
    observed = rows[0]
    assert observed == value  # the observer reproduces the decoder's fixture shape byte for byte
    fact = validate(observed, variant="yellow", identity=SAVE, final_sha1=DATA["titles"]["yellow"]["clean_sha1"], **CONTEXT)
    assert fact["source_id"] == source and fact["delivery"] == delivery
    assert probe.globals().observer.status(probe.globals().observer)["in_flight"] == 0


def test_carry_clear_and_cancelled_prizes_leave_no_receipt(probe):
    value = receipt("yellow", "grant:eevee:0")
    value["return"]["flags"] = 0x00  # .boxFull
    drive(probe, value, "grant:eevee:0")
    assert peeked(probe) == [] and probe.globals().observer.status(probe.globals().observer)["in_flight"] == 0
    prize = receipt("yellow", "grant:game_corner_purchase:0", slot=1)
    del prize["paid"]  # delivered but payment never witnessed: stays in flight, publishes nothing
    drive(probe, prize, "grant:game_corner_purchase:0")
    assert peeked(probe) == [] and probe.globals().observer.status(probe.globals().observer)["in_flight"] == 1


def test_hooks_survive_an_unheld_frame_but_publication_needs_the_hold(probe):
    value = receipt("yellow", "grant:eevee:0")
    probe.execute("held=false")
    drive(probe, value, "grant:eevee:0")
    assert probe.globals().observer.status(probe.globals().observer)["failed"] is None
    assert probe.globals().observer.status(probe.globals().observer)["pending"] == 1
    probe.execute("assert(not pcall(observer.peek))")
    probe.execute("held=true")
    assert len(peeked(probe)) == 1
    probe.execute("assert(observer.acknowledge(observer.peek()))")
    assert peeked(probe) == []


@pytest.mark.parametrize("fault", ["return_without_call", "overlap", "context", "rom", "bytes", "paid_before_return"])
def test_observer_latches_on_invalid_sequences_or_lost_context(probe, fault):
    value = receipt("yellow", "grant:eevee:0")
    if fault == "return_without_call":
        probe.execute("regs.F=0x10;fire('grant:eevee:0','return')")
    elif fault == "overlap":
        probe.globals().value_json = json.dumps(value)
        probe.execute("local v=JSON.decode(value_json);load_point(v.call.point);fire('grant:eevee:0','call');fire('grant:eevee:0','call')")
    elif fault == "context":
        probe.execute("scope.context_generation=string.rep('c',32)")
        drive(probe, value, "grant:eevee:0")
    elif fault == "rom":
        probe.execute("hash=string.rep('e',40)")
        drive(probe, value, "grant:eevee:0")
    elif fault == "bytes":
        probe.execute("bus[profile.sites['grant:eevee:0'].call.address]=0")
        drive(probe, value, "grant:eevee:0")
    else:
        probe.execute("fire('grant:game_corner_purchase:0','paid')")
    assert probe.globals().observer.status(probe.globals().observer)["failed"]
    probe.execute("assert(not pcall(observer.peek))")
