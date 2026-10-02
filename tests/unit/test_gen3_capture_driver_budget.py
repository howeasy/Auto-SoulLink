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
        title="firered"; cp={}; S={gBattleOutcome=0,gActionSelectionCursor=1}; ACTION_BAG=1; B_OUTCOME_CAUGHT=7
        fmt=string.format; ctrl0=function() return 0x12345679 end
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
             battler_slot=function() return 0 end,
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


@pytest.mark.parametrize("expected_ball", (None, 4))
def test_emerald_capture_forwards_the_optional_expected_ball(expected_ball):
    lua = _capture_model(catch_on=1)
    lua.globals().requested_ball = expected_ball
    lua.execute('''
        EMERALD_ENGINE=true; helper_calls=0
        ctx.hunt=function() error("already observed encounter must not hunt again") end
        SP.EMH={throw_ball=function(cp,label,expected_ball)
            assert(expected_ball==requested_ball, "ctx.catch lost its requested ball")
            helper_calls=helper_calls+1; spent=spent+1; return true
        end}
    ''')
    catch = lua.globals().ctx.catch
    result = catch("explicit ball", True) if expected_ball is None else catch("explicit ball", True, expected_ball)
    assert result == "caught"
    assert lua.globals().helper_calls == lua.globals().spent == 1


def test_lead_faint_answers_use_next_yes_switches_and_keeps_throwing():
    lua = _capture_model(catch_on=3)
    lua.execute('''
        switched=0
        ctx.party=function() return {{slot=0,hp=spent>0 and 0 or 10},{slot=1,hp=20}} end
        ctx.battler_slot=function() return switched end
        ctx.send_out=function(slot) assert(slot==1); switched=1; return true end
        ctx.await_turn=function(_,button,policy)
            if spent==1 then
                local handled,key=policy()
                assert(handled and key=="A", "B would decline Use next Pokemon and flee")
                return "party"
            end
            if spent==3 then in_battle=false; return "over" end
            return "action"
        end
    ''')
    assert lua.globals().ctx.catch("lead faint replay") == "caught"
    assert lua.globals().switched == 1 and lua.globals().spent == 3


def test_forced_party_seen_before_a_throw_is_recovered():
    lua = _capture_model(catch_on=1)
    lua.execute('''
        switched=0
        ctx.party=function() return {{slot=0,hp=0},{slot=1,hp=20}} end
        ctx.send_out=function(slot) assert(slot==1); switched=1; return true end
        SP.verify_fight_cursor=function() return switched==0 and "party" or "action" end
    ''')
    assert lua.globals().ctx.catch("party already up") == "caught"
    assert lua.globals().switched == 1


def test_outcome_failure_includes_controller_and_action_cursor():
    lua = _capture_model(catch_on=1)
    lua.globals().memory.read_u8 = lua.eval("function(address) return address==0 and 4 or 2 end")
    key, why = lua.globals().ctx.catch("unexpected flee")
    assert key is None and why == "the battle ended with outcome 4 (ctrl0=0x12345679 action_cursor=2)"
