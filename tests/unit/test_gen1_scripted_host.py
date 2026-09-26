"""The scripted host's per-title wiring: Yellow's lab driver, symbols and lab script indices.

`gen1_scripted_play.lua` is the host the fixture builds and the S-1/S-2 gates run through. Until
A10 it admitted only Red/Blue: the title assert refused "yellow" outright, `MODULES.lab` was a
file-scope constant that could not see the title, and the Oak's-lab script indices were hardcoded
to Red/Blue's 15/16/17/18 in the shared parcel module — so Yellow could not have run the lab
route even with its own driver sitting on disk (a0349b8).

These are pure Lua, driven through lupa with stubbed BizHawk globals: no emulator, no ROM, no
server. What they pin is the RESOLUTION (which driver file, which constants), which is exactly
the part the route cannot check for itself — a wrong driver reads plausible bytes and simply
never reaches its terminal.
"""
from __future__ import annotations

import os

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_HOST = os.path.join(_REPO, "lua", "tests", "gen1_scripted_play.lua")
_PARCEL = os.path.join(_REPO, "lua", "tests", "gen1_rb_parcel_inputs.lua")


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().memory = runtime.table(read_u8=lambda _addr, _domain=None: 0)
    runtime.globals().gameinfo = runtime.table(getromhash=lambda: "ab" * 20)
    return runtime


def _host(lua, title):
    """P.new through the real file, with only the emulator globals stubbed."""
    module = lua.execute(f'return dofile("{_HOST.replace(chr(92), "/")}")')
    return module.new(_REPO.replace("\\", "/"), title, "a", lua.table())


def _parcel(lua):
    return lua.execute(f'return dofile("{_PARCEL.replace(chr(92), "/")}")')


def _expected(lua, title):
    return lua.table(player="a", run_id="scripted", rom_sha1="ab" * 20, context_generation=1,
                     physical_instance="scripted-host", title=title)


def test_yellow_resolves_the_yellow_lab_driver_and_its_own_symbols(lua):
    play = _host(lua, "yellow")
    assert play.modules["lab"]["file"] == "gen1_y_ball_gate_inputs.lua"
    assert play.modules["lab"]["terminal"] == "lab-loss-complete"
    # everything else stays the shared module
    assert play.modules["parcel"]["file"] == "gen1_rb_parcel_inputs.lua"
    assert play.modules["save"]["file"] == "gen1_rb_save_inputs.lua"
    assert play.expected["title"] == "yellow"
    # pokeyellow.sym parsed to real addresses (wCurMap is in the Yellow profile's WRAM range)
    assert 0xD000 <= play.symbols["wCurMap"] <= 0xDFFF


def test_red_still_resolves_the_rb_lab_driver(lua):
    play = _host(lua, "red")
    assert play.modules["lab"]["file"] == "gen1_rb_ball_gate_inputs.lua"
    assert play.expected["title"] == "red"


def test_an_unknown_title_is_refused(lua):
    with pytest.raises(Exception, match="Red/Blue lab route and a Yellow one"):
        _host(lua, "green")


def test_the_lab_script_indices_are_per_title(lua):
    """pokered 15/16/17 + noop 18; pokeyellow 19/20/21 + noop 22 (pret scripts/OaksLab.asm)."""
    parcel = _parcel(lua)
    assert [parcel.LAB["red"]["delivery"][i] for i in (1, 2, 3)] == [15, 16, 17]
    assert parcel.LAB["red"]["noop"] == 18
    assert [parcel.LAB["yellow"]["delivery"][i] for i in (1, 2, 3)] == [19, 20, 21]
    assert parcel.LAB["yellow"]["noop"] == 22


def test_the_parcel_driver_takes_its_table_from_the_expected_title(lua):
    parcel = _parcel(lua)
    assert parcel.new(_expected(lua, "yellow")).lab["noop"] == 22
    assert parcel.new(_expected(lua, "red")).lab["noop"] == 18
    # an unknown title is refused rather than silently given R/B's scripts
    with pytest.raises(Exception, match="no lab script table"):
        parcel.new(_expected(lua, "green"))


def test_the_host_hands_the_title_to_the_drivers_it_builds(lua):
    """`expected` is what every route module receives; the title has to be in it or the parcel
    module would fall back to R/B's indices on a Yellow cartridge."""
    play = _host(lua, "yellow")
    assert play.expected["title"] == "yellow"
    assert play.expected["player"] == "a" and play.expected["run_id"] == "scripted"


def stubbed_steps(lua):
    lua.execute('''
        local real_dofile=dofile
        model_ram={}; model_frame=0; model_steps=0; model_phases={}
        emu={framecount=function() return model_frame end}
        dofile=function(path)
            if path:match("/lua/gen1/entry.lua$") then
                return {harness_bus_u8=function() return function(address) return model_ram[address] or 0 end end}
            elseif path:match("/gen1_rb_ball_gate_inputs.lua$") then
                return {new=function(expected)
                    assert(expected.title=="red")
                    return {step=function(handshake,status,point,frame)
                        assert(handshake.ready and status.observation_loop)
                        return {A=true},point.tick==3 and "lab-loss-complete" or "model-walk"
                    end}
                end}
            end
            return real_dofile(path)
        end
        model_step=function(buttons)
            model_steps=model_steps+1; model_frame=model_frame+1; model_last_buttons=buttons
        end
    ''')
    play = _host(lua, "red")
    lua.globals().play = play
    return play


def test_boot_preserves_gen1_thirty_frame_predicate_and_frame_return(lua):
    play = stubbed_steps(lua)
    lua.globals().model_ram[play.symbols["wCurMap"]] = play.expected["facts"]["MAP"]["REDS_HOUSE_2F"]
    result = lua.execute('return play.boot(model_step,function() return true end,40)')
    assert result == 30 and lua.globals().model_steps == 29


def test_boot_does_not_accept_map_bytes_without_game_checkpoint(lua):
    play = stubbed_steps(lua)
    lua.globals().model_ram[play.symbols["wCurMap"]] = play.expected["facts"]["MAP"]["REDS_HOUSE_2F"]
    with pytest.raises(Exception, match="bounded progress"):
        lua.execute('play.boot(model_step,function() return false end,40)')
    assert lua.globals().model_steps == 40


def test_route_rebind_preserves_receipts_callbacks_and_terminal_idle(lua):
    stubbed_steps(lua)
    receipt = lua.execute('''
        play.point=function() return {tick=model_frame+1} end
        return play.run(model_step,{"lab"},function(name,phase,frame,point)
            model_phases[#model_phases+1]={name,phase,frame,point.tick}
        end,10)
    ''')
    assert receipt["lab"] == 3 and lua.globals().model_steps == 3
    assert lua.globals().model_last_buttons["A"] is False
    assert len(lua.globals().model_phases) == 2
    assert lua.globals().model_phases[2][2] == "lab-loss-complete"


def test_unknown_or_empty_chain_refuses_before_any_input(lua):
    stubbed_steps(lua)
    for chain in ('{}', '{"lab","unknown"}', '{"lab","lab"}'):
        with pytest.raises(Exception):
            lua.execute('play.run(model_step,' + chain + ',nil,10)')
    assert lua.globals().model_steps == 0
