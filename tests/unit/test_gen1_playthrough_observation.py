"""A successful, quarantined capture must not cause a second hunt in the same area."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def run_scenario(location="box", failure=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    lua.globals().location = location
    lua.globals().failure = failure
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        SLINK_DUO={wt=root}; captured=false; hunts=0; logs={}; advances=0
        local old={key='1111:1234:99',species_index=153,hp=20,level=5}
        local caught={key='2222:1234:99',species_index=153,hp=20,level=5,slot=0}
        local H={}
        function H.stock_balls(n) assert(n==40); return true end
        function H.balls() return captured and 39 or 40 end
        function H.all_keys() return {[old.key]=true} end
        function H.hunt(mode,limit)
            assert(mode=='catch' and limit==1); hunts=hunts+1
            if failure=='lost' then return nil,'first encounter lost' end
            captured=true
            return {key=caught.key,species_index=-1,level=-1}
        end
        dofile=function(path)
            assert(path==root..'/lua/tests/duo/gen1_hunt.lua')
            return function(_) return H end
        end
        M={MAP_ID_ADDR=1,BOX_BASE_ADDR=100,BOX_STRUCT_SIZE=33,HP_OFFSET=1,OTID_OFFSET=12,gb_variant='red'}
        function M.read_u8(_) return 12 end
        function M.hasWildEncounters() return true end
        function M.getPartyCount()
            return captured and (location=='party' or failure=='duplicate') and 2 or 1
        end
        function M.readPartySlot(slot) return slot==0 and old or caught end
        function M.getBoxCount() return captured and location=='box' and 1 or 0 end
        function M.readBoxSlot(_) return {key=caught.key,species_index=153,slot=0} end
        function M.getMemorialBoxCount() return captured and location=='memorial' and 1 or 0 end
        function M.readMemorialBoxSlot(_) return caught end
        function M.box_read_u16_be(addr) assert(addr==101); return failure=='dead' and 0 or 20 end
        function M.box_read_u8(addr) return addr==116 and 125 or 0 end
        G={toNatDex=function(_) return 1 end,readBaseStats=function(...) return {growth_rate=0} end}
        ctx={M=M,G=G,wait_go=function() return true end,party_count=M.getPartyCount,
             log=function(s) logs[#logs+1]=s end,frames=function(n) advances=advances+n end,
             wait_link_verified=function(key) assert(key==caught.key); return true end,
             wait_until=function(check) return check() end,find_slot_by_key=function(key) return 1 end}
    """)
    scenario = lua.execute((ROOT / "lua/tests/duo/scenario_gen1_playthrough.lua").read_text(encoding="utf-8"))
    result = scenario(lua.globals().ctx)
    logs = list(lua.globals().logs.values())
    return lua, result, logs


@pytest.mark.parametrize("location", ["party", "box"])
def test_actual_location_and_experience_are_observed_after_quarantine(location):
    lua, (ok, _), logs = run_scenario(location)
    assert ok and lua.globals().hunts == 1
    assert any("CAUGHT 2222:1234:99 species=0x99 level=5" in line and "where=" + location in line for line in logs)
    assert lua.globals().advances == 120


@pytest.mark.parametrize("location,failure", [("box", "lost"), ("box", "dead"),
                                            ("box", "duplicate"), ("memorial", None)])
def test_lost_retired_or_ambiguous_captures_fail_without_recapturing(location, failure):
    lua, (ok, reason), logs = run_scenario(location, failure)
    assert ok is False and reason and lua.globals().hunts == 1
    assert not any(line.startswith("CAUGHT ") for line in logs)
    assert lua.globals().advances == 0


def test_real_runner_stops_before_waiting_for_a_failed_partner(monkeypatch):
    from tools import e2e_duo
    monkeypatch.setattr(e2e_duo, "read_result", lambda scenario, player, directory:
                        "RESULT: FAIL first encounter lost" if player == "b" else "still playing")
    runner = e2e_duo.DuoRun.__new__(e2e_duo.DuoRun)
    runner.scenario = "playthrough"
    runner.data_dir = "isolated-run"
    runner.cfg = {"timeout": 1500}
    with pytest.raises(RuntimeError, match="instance b.*first encounter lost"):
        runner.assert_real_link_formed()
    with pytest.raises(RuntimeError, match="instance b"):
        runner.wait_results()


def test_runner_ignores_partial_debug_keys_and_requires_one_exact_capture():
    from tools.e2e_duo import confirmed_capture
    receipt = "CAUGHT 2222:1234:99 species=0x99 level=5 where=box\n"
    debug = "  attempt 1: CAUGHT 2222:1234\n[client] [duo] " + receipt
    assert confirmed_capture(debug) is None
    assert confirmed_capture(debug + receipt + receipt) == "2222:1234:99"
    with pytest.raises(RuntimeError, match="multiple different"):
        confirmed_capture(receipt + receipt.replace("2222", "3333"))
