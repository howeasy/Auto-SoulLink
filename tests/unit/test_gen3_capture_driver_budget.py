"""R4-DRIVER: replay the eight-miss live failure at the capture-driver boundary."""
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _capture_model(catch_on=0, stock=20):
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text(encoding="utf-8")
    body = source[source.index("function ctx.catch("):source.index("--- Keep choosing a no-damage move")]
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        title="firered"; cp={}; S={gBattleOutcome=0}; ACTION_BAG=1; B_OUTCOME_CAUGHT=7
        spent=0; in_battle=true; settled_in_battle=false; boot_keys={}; logs={}
        log=function(s) logs[#logs+1]=s end
        ctx={hunt=function() return true end, balls=function() return stock-spent end,
             choose_action=function() return true end, bag_input_ready=function() return true end,
             wait_until=function() return true end,
             await_turn=function()
                 if catch_on>0 and spent==catch_on then in_battle=false; return "over" end
                 return "action"
             end,
             last_sent=function() return {key="caught"} end, party=function() return {} end,
             run_away=function() in_battle=false; return true end}
        SP={verify_fight_cursor=function() return in_battle and "action" or nil end,
            throw_pokeball_from_bag=function() spent=spent+1 end}
        play={in_battle=function() return in_battle end,
              wait_scene_settled=function() settled_in_battle=in_battle; return not in_battle end}
        memory={read_u8=function() return in_battle and 0 or B_OUTCOME_CAUGHT end}
    ''')
    lua.globals().catch_on, lua.globals().stock = catch_on, stock
    lua.execute(body)
    return lua


def test_eight_misses_never_fall_through_to_unmetered_scene_inputs():
    lua = _capture_model(stock=40)
    key, why = lua.globals().ctx.catch("cap replay")
    assert key is None and "budget" in why
    assert lua.globals().in_battle is True
    assert lua.globals().settled_in_battle is False
    assert lua.globals().spent == len(lua.globals().logs) <= 20


def test_ninth_throw_is_instrumented_when_the_cartridge_still_has_balls():
    lua = _capture_model(catch_on=9)
    result = lua.globals().ctx.catch("live ninth-throw replay")
    assert result == "caught"
    assert lua.globals().spent == len(lua.globals().logs) == 9
    assert lua.globals().logs[9] == "THREW 9"
    assert lua.globals().settled_in_battle is False


@pytest.mark.parametrize("catch_on", (1, 8, 20))
def test_completed_captures_settle_only_after_the_battle(catch_on):
    lua = _capture_model(catch_on=catch_on)
    assert lua.globals().ctx.catch("positive") == "caught"
    assert lua.globals().spent == catch_on and lua.globals().settled_in_battle is False


def test_capture_propagates_a_scene_settle_refusal():
    lua = _capture_model(catch_on=1)
    lua.globals().play.wait_scene_settled = lua.eval('function() return false, "unsettled" end')
    key, why = lua.globals().ctx.catch("settle failure")
    assert key is None and "unsettled" in why


def test_capture_of_an_observed_encounter_does_not_hunt_again():
    lua = _capture_model(catch_on=1)
    lua.globals().ctx.hunt = lua.eval('function() error("a second hunt discarded the observed foe") end')
    assert lua.globals().ctx.catch("already at the native battle menu", True) == "caught"
