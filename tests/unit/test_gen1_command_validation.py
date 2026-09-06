"""Malformed commands cannot poison queues/HUD state or interrupt later commands."""
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
VALID_KEY = "ABCD:1234:01"
STATS = {"level": 10, "maxHP": 40, "attack": 20, "defense": 20, "speed": 20, "spAtk": 20, "spDef": 20}


@pytest.fixture
def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.execute("package.path=root..'/lua/?.lua;'..package.path")
    lua.execute("""
        memory={getmemorydomainlist=function() return {'System Bus'} end,
          read_u8=function() return 0 end,write_u8=function() error('unexpected write') end}
        print=function() end; console={log=function() end};fmt=string.format
        sent={};shown={};writes=0;nick_cache={};resolved_areas={};writes_enabled=true
        send=function(msg) sent[#sent+1]=msg;return true end
        hud_show=function(text) shown[#shown+1]=text end
        prompt_show=hud_show;nick_label=function() return 'MON' end
        HUD={set_game_over=function() end,set_rebuilding=function() end,clear_rebuilding=function() end}
    """)
    g = lua.globals()
    g.G = lua.execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
    g.M = lua.execute((ROOT / "lua/memory_gb.lua").read_text(encoding="utf-8"))
    g.M.initProfile(g.G, "red")
    g.Commands = lua.execute((ROOT / "lua/gen1_commands.lua").read_text(encoding="utf-8"))
    g.JSON = lua.execute((ROOT / "lua/json_codec.lua").read_text(encoding="utf-8"))
    lua.execute("""
        M.getPartyCount=function() return 1 end
        M.readPartySlot=function() return {key='ABCD:1234:01'} end
        M.forceFaint=function() writes=writes+1 end
    """)
    source = (ROOT / "lua/clients/gen1_rby_client.lua").read_text(encoding="utf-8")
    block = source[source.index("local pending_sync_cmds = {}"):source.index("-- ── Per-frame state")]
    client = lua.execute(block + """
        return {dispatch=dispatch_commands,queue=function() return pending_sync_cmds end,
          seed=function(q) pending_sync_cmds=q end}
    """)
    return lua, client


def dispatch(runtime, commands):
    lua, client = runtime
    client.dispatch(lua.globals().JSON.decode(json.dumps(commands)))


@pytest.mark.parametrize("command", ["force_faint", "force_explode", "box_mon", "party_mon", "memorialize"])
@pytest.mark.parametrize("key", [None, 17, False, {}, [], "broken", "ABCD:1234:1F", "abcd:1234:01", "A:CD:1234:01"])
def test_bad_keys_never_enter_or_cancel_a_queue_and_do_not_stop_the_batch(runtime, command, key):
    lua, client = runtime
    original = lua.table_from([lua.table_from({"cmd": "box_mon", "key": VALID_KEY})])
    client.seed(original)
    dispatch(runtime, [{"cmd": command, "key": key}, {"cmd": "hud_show", "text": "after"}])
    assert lua.eval("function(a,b) return rawequal(a,b) end")(client.queue(), original)
    assert len(client.queue()) == 1 and lua.globals().writes == 0
    assert lua.globals().sent[1].ack == "NACK"
    assert lua.globals().sent[1].key is None
    assert lua.globals().shown[1] == "after"


@pytest.mark.parametrize("stats", [{}, {"level": 5}, {**STATS, "maxHP": 1000}, {**STATS, "level": 1.5},
                                  {**STATS, "spDef": 21}, "invalid"])
def test_invalid_stats_are_nacked_before_canceling_a_valid_opposite_command(runtime, stats):
    lua, client = runtime
    original = lua.table_from([lua.table_from({"cmd": "box_mon", "key": VALID_KEY})])
    client.seed(original)
    dispatch(runtime, [{"cmd": "party_mon", "key": VALID_KEY, "stats": stats}])
    assert lua.eval("function(a,b) return rawequal(a,b) end")(client.queue(), original)
    assert lua.globals().writes == 0
    assert lua.globals().sent[1].event == "sync_retrieve_failed"
    assert lua.globals().sent[1].key == VALID_KEY and lua.globals().sent[1].ack == "NACK"


@pytest.mark.parametrize("command", [{"cmd": "hud_show", "text": {}}, {"cmd": "msgbox", "text": 17},
    {"cmd": "force_faint", "key": VALID_KEY, "nickname": []}, {"cmd": "hud_show", "text": "x", "r": -1},
    {"cmd": "hud_show", "text": "x", "frames": 1.5}, {"cmd": "resolved_areas", "areas": [None]},
    {"cmd": "link_panel", "rows": [{}]}, {"cmd": "unresolve_area", "area_id": {}},
    {"cmd": "show_choices", "text": "excluded native choices"}])
def test_bad_display_and_collection_shapes_do_not_poison_later_hud_processing(runtime, command):
    lua, client = runtime
    dispatch(runtime, [command, {"cmd": "hud_show", "text": "after"}])
    assert lua.globals().writes == 0 and len(client.queue()) == 0
    assert lua.globals().sent[1].ack == "NACK"
    assert len(lua.globals().nick_cache) == 0
    assert lua.globals().shown[1] == "after"


def test_an_unexpected_handler_exception_nacks_and_the_next_command_runs(runtime):
    lua, _ = runtime
    lua.execute("M.forceFaint=function() error('injected handler failure') end")
    dispatch(runtime, [{"cmd": "force_faint", "key": VALID_KEY}, {"cmd": "hud_show", "text": "after"}])
    assert lua.globals().sent[1].ack == "NACK"
    assert lua.globals().sent[1].event == "command_nack"
    assert lua.globals().shown[1] == "after"


def test_validation_exceptions_are_contained_before_any_queue_mutation(runtime):
    lua, client = runtime
    lua.execute("""
        local original=Commands.validate
        Commands.validate=function(c,...)
            if c.cmd=='box_mon' then error('injected validator failure') end
            return original(c,...)
        end
    """)
    dispatch(runtime, [{"cmd": "box_mon", "key": VALID_KEY}, {"cmd": "hud_show", "text": "after"}])
    assert len(client.queue()) == 0 and lua.globals().writes == 0
    assert lua.globals().sent[1].ack == "NACK"
    assert lua.globals().shown[1] == "after"


@pytest.mark.parametrize("stats", [None, STATS])
def test_valid_retrieval_still_replaces_an_opposite_pending_command(runtime, stats):
    lua, client = runtime
    client.seed(lua.table_from([lua.table_from({"cmd": "box_mon", "key": VALID_KEY})]))
    command = {"cmd": "party_mon", "key": VALID_KEY}
    if stats is not None:
        command["stats"] = stats
    dispatch(runtime, [command])
    assert len(client.queue()) == 1 and client.queue()[1].cmd == "party_mon"
    assert len(lua.globals().sent) == 0


def test_valid_faint_and_noop_are_not_rejected(runtime):
    lua, _ = runtime
    dispatch(runtime, [{"cmd": "force_faint", "key": VALID_KEY}, {"cmd": "noop"}])
    assert lua.globals().writes == 1 and len(lua.globals().sent) == 0


@pytest.mark.parametrize("failure", ["writes-disabled", "missing-key", "bad-party-count"])
def test_unavailable_faint_target_does_not_claim_success_or_change_nickname_cache(runtime, failure):
    lua, _ = runtime
    if failure == "writes-disabled":
        lua.globals().writes_enabled = False
    elif failure == "missing-key":
        lua.execute("M.readPartySlot=function() return {key='1111:1234:01'} end")
    else:
        lua.execute("M.getPartyCount=function() return 255 end")
    dispatch(runtime, [{"cmd": "force_faint", "key": VALID_KEY, "nickname": "new name"},
                       {"cmd": "hud_show", "text": "after"}])
    assert lua.globals().writes == 0 and len(lua.globals().nick_cache) == 0
    assert lua.globals().sent[1].ack == "NACK"
    assert lua.globals().sent[1].reason
    assert lua.globals().shown[1] == "after"
