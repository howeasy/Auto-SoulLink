"""Replay the keyed HP0 edge inside the actual lose/verify/wait helper chain."""
import re

import lupa
import pytest

import tests.unit.test_e2e_duo_gen3 as model
from tests.unit.test_e2e_duo_gen3 import REPO, _lua_defs, battle_model as battle_model


def _observe(lua, *, faint_at=0, menu="timeout"):
    lua.globals().FAINT_AT, lua.globals().MENU = faint_at, menu
    lua.execute('''
        M.ctrl=0; M.over=false; M.filled=true; M.lead_hp=1; M.after=nil
        M.frame=0; PARTY_UP=false; TRACE={}; FINISH_CALLS=0
        emu.framecount=function() return M.frame end
        ctx.find=function(key) if key=="K0" then return {key="K0",hp=M.lead_hp} end end
        ctx.hp0=function() return nil end
        party_menu_up=function() return PARTY_UP end
        local set=joypad.set
        joypad.set=function(t)
            TRACE[#TRACE+1]=(t and t.A) and "A" or "released"
            return set(t)
        end
        local finish=G.finish
        G.finish=function(ok,why) FINISH_CALLS=FINISH_CALLS+1;return finish(ok,why) end
        local advance=emu.frameadvance
        emu.frameadvance=function()
            advance()
            if FAINT_AT>0 and M.frame==FAINT_AT then M.lead_hp=0 end
            if M.frame==3 then
                if MENU=="action" then M.ctrl=S.HandleInputChooseAction|1
                elseif MENU=="party" then PARTY_UP=true
                elseif MENU=="ended" then M.over=true end
            end
        end
    ''')
    return lua


def _logs(lua):
    return list(lua.globals().LOGS.values())


@pytest.mark.parametrize("faint_at", (5, 1200))
def test_requested_key_hp0_during_verify_returns_lose_success_without_finish(battle_model, faint_at):
    lua = _observe(battle_model, faint_at=faint_at)
    result = lua.globals().ctx.lose_active("K0", "whiteout wait replay", lua.table(stop_on_faint=True))
    assert (result[0] if isinstance(result, tuple) else result) is True
    assert lua.globals().FINISH_CALLS == 0 and lua.globals().M.frame == faint_at
    assert lua.globals().M.over is False and lua.globals().M.ctrl == 0
    assert len(lua.globals().M.used) == 0  # HP0 arose while waiting, before another move was selected.
    logs = _logs(lua)
    assert any(line.startswith("LOSE_WAIT_ENTER") and re.search(r"\bframe=0\b", line) for line in logs)
    assert any(line.startswith("LOSE_WAIT_STOP") and "reason=fainted" in line
               and re.search(rf"\bframe={faint_at}\b", line) for line in logs)


@pytest.mark.parametrize("key,faint_at", (("OTHER", 5), ("K0", 0)))
def test_wrong_key_or_no_hp0_keeps_the_same_1200_frame_failure(battle_model, key, faint_at):
    lua = _observe(battle_model, faint_at=faint_at)
    with pytest.raises(lupa.LuaError, match="G.finish: .*neither action nor forced party menu"):
        lua.globals().ctx.lose_active(key, "not the observed faint", lua.table(stop_on_faint=True))
    assert lua.globals().M.frame == 1200 and lua.globals().FINISH_CALLS == 1
    logs = _logs(lua)
    assert any(line.startswith("LOSE_WAIT_ENTER") for line in logs)
    assert any(line.startswith("LOSE_WAIT_STOP") and "reason=timeout" in line for line in logs)
    assert not any("reason=fainted" in line for line in logs)


@pytest.mark.parametrize("menu,reason,passed", (("action", "menu", True),
    ("party", "menu", False), ("ended", "ended", False)))
def test_lose_wait_logs_normal_menu_and_battle_end_stops(battle_model, menu, reason, passed):
    lua = _observe(battle_model, menu=menu)
    result = lua.globals().ctx.lose_active("K0", "normal wait stop", lua.table(stop_on_faint=True))
    assert (result[0] if isinstance(result, tuple) else result) is passed
    assert lua.globals().FINISH_CALLS == 0
    stops = [line for line in _logs(lua) if line.startswith("LOSE_WAIT_STOP")]
    assert stops and f"reason={reason}" in stops[0] and re.search(r"\bframe=3\b", stops[0])


def _verify(menu, callback):
    lua = _observe(model.battle_model.__wrapped__(), menu=menu)
    helper = lua.execute(_lua_defs(REPO / "lua/tests/gen3_scripted_play.lua",
                                  ["wait_for_action_menu", "verify_fight_cursor"])
                         + "\nreturn verify_fight_cursor")
    stop = None if callback == "absent" else lua.eval(f"function(_) return {callback} end")
    try:
        result = helper(lua.globals().cp, "incidental_battle", stop)
    except lupa.LuaError as exc:
        assert "G.finish:" in str(exc)
        result = "G.finish"
    return result, list(lua.globals().TRACE.values()), lua.globals().M.frame, lua.globals().FINISH_CALLS


@pytest.mark.parametrize("menu", ("action", "party", "ended", "timeout"))
@pytest.mark.parametrize("callback", ("nil", "false"))
def test_optional_nil_or_false_stop_preserves_real_button_and_terminal_behavior(menu, callback):
    baseline = _verify(menu, "absent")
    observed = _verify(menu, callback)
    assert observed == baseline
    expected = {"action": ("fight", 3, 0), "party": ("party", 3, 0),
                "ended": (None, 3, 0), "timeout": ("G.finish", 1200, 1)}[menu]
    assert (observed[0], observed[2], observed[3]) == expected


@pytest.mark.parametrize("faint_at", (5, 1200))
@pytest.mark.parametrize("option", ("absent", "false"))
def test_default_and_false_option_use_two_arg_verify_and_keep_midwait_timeout(battle_model, faint_at, option):
    lua = _observe(battle_model, faint_at=faint_at)
    lua.execute('''
        local real=SP.verify_fight_cursor
        SP.verify_fight_cursor=function(...)
            VERIFY_ARITY=select("#",...); VERIFY_STOP=select(3,...)
            return real(...)
        end
    ''')
    raised = False
    try:
        if option == "absent":
            lua.globals().ctx.lose_active("K0", "default wait")
        else:
            lua.globals().ctx.lose_active("K0", "false wait", lua.table(stop_on_faint=False))
    except lupa.LuaError as exc:
        assert "G.finish:" in str(exc) and "neither action nor forced party menu" in str(exc)
        raised = True
    assert lua.globals().VERIFY_ARITY == 2, "default caller changed the real verify argument shape"
    assert lua.globals().VERIFY_STOP is None, "default caller supplied the whiteout predicate"
    assert raised and lua.globals().M.frame == 1200 and lua.globals().FINISH_CALLS == 1


def _scenario_lose_call(name):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LINKED_SLOT = 1 if name == "whiteout" else 0
    lua.execute('''
        ctx={player="a",D={game="gen3_exp",active_faint_case="wild"},cp={},emerald_engine=true,
             wait_go=function()return true end,linked=function()return "LINK"end,
             walk_to_pc=function()end,pc_deposit=function()return "LINK"end,
             observe_boxed=function()return true end,log=function()end,
             SP={whiteout_destination=function()return {group=0,num=10,x=6,y=17}end},
             write_lines=function()return {}end,watch=function()end,on_write=function()end,
             try=function(fn)return fn()end,walk_pc_to_grass=function()end,
             hunt=function()return true end,party=function()return {{key="K0",slot=0,hp=1}}end,
             find=function()return {key="LINK",slot=LINKED_SLOT,hp=1}end,
             lose_active=function(...)
                 LOSE_ARGS=table.pack(...);error("STOP_AT_LOSE",0)
             end}
    ''')
    scenario = lua.execute((REPO / f"lua/tests/duo/scenario_gen3_{name}.lua").read_text(encoding="utf-8"))
    with pytest.raises(lupa.LuaError, match="STOP_AT_LOSE"):
        scenario(lua.globals().ctx)
    return lua.globals().LOSE_ARGS


def test_real_whiteout_scenario_explicitly_requests_the_faint_stop():
    args = _scenario_lose_call("whiteout")
    assert args.n == 3 and args[1] == "K0" and args[2] == "whiteout a"
    assert args[3].stop_on_faint is True


def test_real_linked_active_natural_scenario_keeps_the_two_arg_default():
    args = _scenario_lose_call("linked_faint_active")
    assert args.n == 2 and args[1] == "LINK" and args[2] == "linked_faint_active a"
