"""The Lua static observer's receipts are exactly what the Python decoder accepts.

The emulator is stubbed (memory bus, registers, hooks); the RAM bytes placed on the bus
are the decoder tests' synthetic points. This proves the wire contract end to end without
claiming any live engine behaviour.
"""

import json

import pytest

from server.gen1_static_receipt import DATA, validate, validate_end
from server.protocol_journal import JournalError
from tests.unit.test_client_journal import start
from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_gen1_static_receipt import CONTEXT, SAVE, end_receipt, receipt

SITES = DATA["titles"]["yellow"]["sites"]
POINT = ["map_id", "cur_opponent", "cur_level", "enemy_species2", "battle_flag", "battle_type", "sprite_index", "engaged_class", "engaged_set",
         "battle_result"]


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().sites_json = json.dumps(DATA)
    lua.globals().point_keys = json.dumps(POINT)
    lua.execute("""
        package.loaded.gen1_static_sites=assert(JSON.decode(sites_json))
        profile=JSON.decode(sites_json).titles.yellow;A=profile.addresses
        rom={};bus={};hooks={};frame=100;pc=0;regs={SP=0xDFFE};held=true
        scope={context_generation=string.rep('a',32),physical_instance=string.rep('1',32)}
        hash=profile.clean_sha1
        memory={read_u8=function(a,d)return (d=='ROM' and rom[a] or bus[a])or 0 end}
        gameinfo={getromhash=function()return hash end}
        emu={framecount=function()return frame end,getregister=function(k)if k=='PC' then return pc end;return regs[k]end}
        event={on_bus_exec=function(fn,a,name)hooks[name]=fn;return name end,unregisterbyid=function(name)hooks[name]=nil end}
        function put(address,hexs,domain)for i=1,#hexs,2 do (domain=='ROM' and rom or bus)[address+(i-1)/2]=tonumber(hexs:sub(i,i+1),16)end end
        for _,site in pairs(profile.sites)do
            for _,anchor in ipairs({site.arm,site.writes,site.arm.routine})do put(anchor.rom_offset,anchor.expected_hex,'ROM')end
            put(site.arm.address,site.arm.expected_hex)
        end
        for _,anchor in ipairs({profile.began,profile.began.prelude,profile.battle_end,profile.battle_end.reset,profile.battle_end.call})do
            put(anchor.rom_offset,anchor.expected_hex,'ROM')
        end
        put(profile.began.address,profile.began.expected_hex);put(profile.battle_end.address,profile.battle_end.expected_hex)
        observer=require('gen1_static_observer').new({variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})
        names={map_id='wCurMap',cur_opponent='wCurOpponent',cur_level='wCurEnemyLevel',enemy_species2='wEnemyMonSpecies2',battle_flag='wIsInBattle',
            battle_type='wBattleType',sprite_index='wSpriteIndex',engaged_class='wEngagedTrainerClass',engaged_set='wEngagedTrainerSet',
            battle_result='wBattleResult'}
        function load_point(p)
            put(A.wPlayerName,p.trainer_hex);put(A.wPlayerID,p.player_id_hex)
            for key,name in pairs(names)do bus[A[name]]=p[key]end
        end
        function fire(name,anchor)pc=anchor.address;bus[A.hLoadedROMBank]=anchor.bank;hooks['slink-static-'..name]()end
        function arm_name(source_id)local site=profile.sites[source_id];return site.kind=='object' and 'arm-object' or 'arm-'..source_id end
    """)
    return lua


def drive(lua, value, source, *, began=True):
    lua.globals().value_json = json.dumps(value)
    lua.execute(f"""
        local v=JSON.decode(value_json);local site=profile.sites['{source}']
        frame=v.arm.frame;regs.SP=v.arm.sp;load_point(v.arm.point);fire(arm_name('{source}'),site.arm)
        if {"true" if began else "false"} then frame=v.began.frame;regs.SP=v.began.sp;load_point(v.began.point);fire('began',profile.began) end
    """)


def end_battle(lua, value, *, bank=None):
    lua.globals().value_json = json.dumps(value)
    lua.execute(f"""
        local v=JSON.decode(value_json)
        frame=v['end'].frame;regs.SP=v['end'].sp;load_point(v['end'].point)
        {"fire('battle-end',profile.battle_end)" if bank is None else f"pc=profile.battle_end.address;bus[A.hLoadedROMBank]={bank};hooks['slink-static-battle-end']()"}
    """)


def peeked(lua):
    return json.loads(lua.eval("JSON.encode(observer.peek())"))


def status(lua):
    return lua.globals().observer.status(lua.globals().observer)


@pytest.mark.parametrize("source", ["static:route12_snorlax", "static:route16_snorlax", "static:powerplant_voltorb2", "static:powerplant_zapdos",
                                    "static:ceruleancaveb1f_mewtwo", "static:seafoamislandsb4f_articuno"])
def test_observer_receipt_is_accepted_by_the_decoder_verbatim(probe, source):
    value = receipt("yellow", source)
    drive(probe, value, source)
    rows = peeked(probe)
    assert len(rows) == 1 and rows[0] == value  # the observer reproduces the decoder's fixture shape byte for byte
    fact = validate(rows[0], variant="yellow", identity=SAVE, final_sha1=DATA["titles"]["yellow"]["clean_sha1"], **CONTEXT)
    assert fact["static_id"] == source and status(probe)["in_flight"] == 0
    probe.execute("assert(observer.acknowledge(observer.peek()))")
    assert peeked(probe) == []


def test_object_statics_are_told_apart_by_the_sprite_index_at_the_shared_home_ret(probe):
    for source in ("static:powerplant_voltorb1", "static:powerplant_voltorb6", "static:powerplant_electrode2"):
        drive(probe, receipt("yellow", source), source)
    assert [row["source_id"] for row in peeked(probe)] == ["static:powerplant_voltorb1", "static:powerplant_voltorb6", "static:powerplant_electrode2"]
    assert SITES["static:powerplant_voltorb1"]["arm"] == SITES["static:powerplant_electrode2"]["arm"]  # one hook, three identities


def test_began_without_an_arm_publishes_nothing(probe):
    value = receipt("yellow", "static:route12_snorlax")
    probe.globals().value_json = json.dumps(value)
    probe.execute("local v=JSON.decode(value_json);frame=v.began.frame;load_point(v.began.point);fire('began',profile.began)")
    assert peeked(probe) == [] and status(probe)["failed"] is None and status(probe)["in_flight"] == 0
    drive(probe, value, "static:route12_snorlax", began=False)  # armed, battle not yet started
    assert peeked(probe) == [] and status(probe)["in_flight"] == 1


def test_hooks_survive_an_unheld_frame_but_publication_needs_the_hold(probe):
    value = receipt("yellow", "static:victoryroad2f_moltres")
    probe.execute("held=false")
    drive(probe, value, "static:victoryroad2f_moltres")
    assert status(probe)["failed"] is None and status(probe)["pending"] == 1
    probe.execute("assert(not pcall(observer.peek))")
    probe.execute("held=true")
    assert len(peeked(probe)) == 1


@pytest.mark.parametrize("fault", ["overlap", "unknown_object", "context", "rom", "bytes", "began_bytes"])
def test_observer_latches_on_invalid_sequences_or_lost_context(probe, fault):
    value = receipt("yellow", "static:route12_snorlax")
    if fault == "overlap":
        drive(probe, value, "static:route12_snorlax", began=False)
        drive(probe, receipt("yellow", "static:route16_snorlax"), "static:route16_snorlax", began=False)
    elif fault == "unknown_object":
        stray = receipt("yellow", "static:powerplant_zapdos")
        stray["arm"]["point"]["sprite_index"] = 12  # an item ball's index, never a monster object
        drive(probe, stray, "static:powerplant_zapdos")
    elif fault == "context":
        probe.execute("scope.context_generation=string.rep('c',32)")
        drive(probe, value, "static:route12_snorlax")
    elif fault == "rom":
        probe.execute("hash=string.rep('e',40)")
        drive(probe, value, "static:route12_snorlax")
    elif fault == "bytes":
        probe.execute("bus[profile.sites['static:route12_snorlax'].arm.address]=0")
        drive(probe, value, "static:route12_snorlax")
    else:
        probe.execute("bus[profile.began.address]=0")
        drive(probe, value, "static:route12_snorlax")
    assert status(probe)["failed"]
    probe.execute("assert(not pcall(observer.peek))")


def test_observer_refuses_a_cartridge_whose_anchors_moved(probe):
    probe.execute("rom[profile.object_arm.routine.rom_offset]=0")
    probe.execute("ok,why=pcall(require('gen1_static_observer').new,{variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})")
    assert probe.globals().ok is False and "ROM anchor differs" in str(probe.globals().why)


def test_battle_end_is_published_once_per_live_origin_and_validates(probe):
    origin = receipt("yellow", "static:powerplant_zapdos")
    drive(probe, origin, "static:powerplant_zapdos")
    assert status(probe)["live"] is True
    for battle_result in (2,):  # caught or ran: the engine writes $02 for both
        end_battle(probe, end_receipt("yellow", "static:powerplant_zapdos", battle_result=battle_result))
    rows = peeked(probe)
    assert [set(row) for row in rows] == [set(origin), {"schema", "source_sha256", "variant", "context_generation", "physical_instance",
                                                          "final_sha1", "end"}]
    assert rows[1] == end_receipt("yellow", "static:powerplant_zapdos", battle_result=2)  # byte for byte the decoder fixture
    fact = validate_end(rows[1], variant="yellow", identity=SAVE, final_sha1=DATA["titles"]["yellow"]["clean_sha1"], **CONTEXT)
    assert fact["kind"] == "static_battle_end" and fact["static_id"] is None and fact["battle_result"] == 2 and fact["frame"] == 300
    assert status(probe)["live"] is False
    # The next battle's end (a random encounter) is nobody's: nothing more is published.
    end_battle(probe, end_receipt("yellow", "static:powerplant_zapdos", frame=900))
    assert len(peeked(probe)) == 2 and status(probe)["failed"] is None


def test_battle_end_without_a_live_origin_publishes_nothing(probe):
    end_battle(probe, end_receipt("yellow"))
    assert peeked(probe) == [] and status(probe)["failed"] is None and status(probe)["live"] is False
    drive(probe, receipt("yellow", "static:route12_snorlax"), "static:route12_snorlax", began=False)  # armed, never began
    end_battle(probe, end_receipt("yellow"))
    assert peeked(probe) == [] and status(probe)["in_flight"] == 1


def test_battle_end_hook_ignores_another_bank_and_latches_on_moved_bytes(probe):
    drive(probe, receipt("yellow", "static:route12_snorlax"), "static:route12_snorlax")
    end_battle(probe, end_receipt("yellow"), bank=15)  # another bank switched in at $77xx: not EndOfBattle (bank 4)
    assert len(peeked(probe)) == 1 and status(probe)["live"] is True and status(probe)["failed"] is None
    end_battle(probe, end_receipt("yellow"))
    assert len(peeked(probe)) == 2 and status(probe)["live"] is False
    probe.execute("bus[profile.battle_end.address]=0")
    drive(probe, receipt("yellow", "static:route16_snorlax"), "static:route16_snorlax")
    end_battle(probe, end_receipt("yellow", "static:route16_snorlax"))
    assert status(probe)["failed"] and "instruction site changed" in status(probe)["failed"]


def test_battle_end_publication_needs_the_hold_and_carries_the_raw_result_byte(probe):
    drive(probe, receipt("yellow", "static:route12_snorlax"), "static:route12_snorlax")
    probe.execute("held=false")
    end_battle(probe, end_receipt("yellow", battle_result=7))  # the observer reads, the decoder judges
    assert status(probe)["pending"] == 2
    probe.execute("assert(not pcall(observer.peek))")
    probe.execute("held=true")
    rows = peeked(probe)
    assert rows[1]["end"]["point"]["battle_result"] == 7
    with pytest.raises(JournalError, match="result byte out of range"):
        validate_end(rows[1], variant="yellow", identity=SAVE, final_sha1=DATA["titles"]["yellow"]["clean_sha1"], **CONTEXT)
    probe.execute("assert(observer.acknowledge(observer.peek()))")
    assert peeked(probe) == []


def test_observer_refuses_a_cartridge_whose_battle_end_anchor_moved(probe):
    probe.execute("rom[profile.battle_end.call.rom_offset]=0")
    probe.execute("ok,why=pcall(require('gen1_static_observer').new,{variant='yellow',final_sha1=hash,owned=function()return scope end,held=function()return held end})")
    assert probe.globals().ok is False and "ROM anchor differs" in str(probe.globals().why)
