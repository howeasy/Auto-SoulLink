"""MODEL regressions at the real G/S poison driver and scenario seams; no emulator."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def poison_lua():
    lua = LuaRuntime(unpack_returned_tuples=True)
    poison = lua.eval("dofile")((ROOT / "lua/tests/gen2_poison_inputs.lua").as_posix())
    return lua, poison


@pytest.mark.parametrize("constructor", ["driver", "new"])
@pytest.mark.parametrize("gs_harden", [None, False, True])
@pytest.mark.parametrize("cursor", [1, 2])
def test_trainer_ball_stall_selects_use_only_when_opted_in(constructor, gs_harden, cursor):
    lua, poison = poison_lua()
    exercise = lua.execute("""
        return function(PI, constructor, gs_harden, cursor)
            local facts = {maps={H={}}, hunt_map='H', start_phase='hunt',
                           moves={POISON_STING=40}, psn_mask=8}
            local F = {TOWARD_BALLS={pack_items='Right'}, BUDGET={settle_frames=1}}
            local opts = {moves={'LEER'}, target=1, gs_harden=gs_harden,
                          fainted=function() return false end, max_frames=100, max_phase_frames=100}
            local d
            if constructor == 'driver' then d = PI.driver(F, facts, opts)
            else
                local ctx = {u1={poison=facts}, json={}, api={}}
                local SG = {qualify_observer=function() return function() return {} end end}
                d = PI.new(ctx, SG, F, {PASSIVE_MOVES={'LEER'}}, opts)
            end
            local function step(ui)
                return d.step({battle_mode=2, input_ready=true, active_slot=1,
                    active_hp=30, active_max_hp=30, active_psn=false, foe_sting=true,
                    party={[0]={hp=80,status=0}, [1]={hp=30,status=0}}, ui=ui})
            end
            local function drain()
                for _=1,PI.HOLD do d.step({}) end
            end
            -- Learn that the linked target has no passive move, then take PACK -> Ball.
            local buttons = step({kind='move_menu', items={'TACKLE'}, pp={35}, cursor=1, columns=1})
            assert(buttons.B)
            drain()
            buttons = step({kind='battle_menu', items={'FIGHT','PKMN','PACK','RUN'}, cursor=3, columns=2})
            assert(buttons.A)
            drain()
            buttons = d.step({battle_mode=2,input_ready=true,active_slot=1,active_hp=30,
                active_max_hp=30,foe_sting=true,party={[1]={hp=30,status=0}},
                ball_cursor='ball',ui={kind='pack_balls'}})
            assert(buttons.A)
            drain()
            local submenu = {kind='item_submenu',items={'USE','QUIT'},cursor=cursor,columns=1}
            local reason
            buttons, reason = step(submenu)
            if not buttons then return nil, reason end
            if cursor == 2 then
                assert(buttons.Up and not buttons.A)
                drain()
                submenu.cursor=1
                buttons, reason = step(submenu)
            end
            return buttons.A, reason
        end
    """)
    used, reason = exercise(poison, constructor, gs_harden, cursor)
    if gs_harden:
        assert used is True and reason == "hunt"
    else:
        assert used is None and reason == "UI is not valid in battle: item_submenu"


@pytest.mark.parametrize("battle_mode,active_slot,learned", [(1, 1, True), (2, 0, True), (2, 1, False)])
def test_opt_in_does_not_accept_submenu_outside_target_trainer_ball_stall(battle_mode, active_slot, learned):
    lua, poison = poison_lua()
    reason = lua.execute("""
        return function(PI, mode, active, learned)
            local d=PI.driver({TOWARD_BALLS={}}, {maps={H={}},hunt_map='H',start_phase='hunt',
                moves={POISON_STING=40},psn_mask=8}, {moves={'LEER'},target=1,gs_harden=true})
            local point={battle_mode=2,input_ready=true,active_slot=1,active_hp=30,
                active_max_hp=30,foe_sting=true,party={[1]={hp=30,status=0}}}
            if learned then
                point.ui={kind='move_menu',items={'TACKLE'},pp={35},cursor=1,columns=1}
                assert(d.step(point).B)
                for _=1,PI.HOLD do d.step({}) end
            end
            point.battle_mode,point.active_slot=mode,active
            point.ui={kind='item_submenu',items={'USE','QUIT'},cursor=1,columns=1}
            local buttons,why=d.step(point)
            assert(buttons == nil)
            return why
        end
    """)(poison, battle_mode, active_slot, learned)
    assert reason == "UI is not valid in battle: item_submenu"


@pytest.mark.parametrize("player", ["a", "b"])
@pytest.mark.parametrize("gs_harden", [None, False, True])
@pytest.mark.parametrize("arrival_ok,setup_ok", [(True, True), (False, True), (True, False)])
def test_poison_starter_setup_is_after_continue_before_catch_and_fails_closed(player, gs_harden, arrival_ok, setup_ok):
    lua = LuaRuntime(unpack_returned_tuples=True)
    scenario = lua.eval("dofile")((ROOT / "lua/tests/duo/scenario_gen2_poison.lua").as_posix())
    ok, reason, order = lua.execute("""
        return function(S,root,player,gs_harden,arrival_ok,setup_ok)
            local calls={}
            local function call(name) calls[#calls+1]=name end
            local h={root=root,player=player,gs_harden=gs_harden,registered={'poison_faint'},
                sent={hello={}},rec={},link_settled=function() return true end}
            h.jitter=function() call('jitter') end
            h.arrive=function() call('arrive'); return arrival_ok,'MODEL arrival refused' end
            h.party=function() call('party') end
            h.go=function() return true end
            h.wait=function(predicate) return predicate() end
            h.play=function() call('catch'); return false,'MODEL stop before catch' end
            if gs_harden then
                h.gs_setup={condition_starter=function()
                    call('setup'); return setup_ok,'MODEL setup refused'
                end}
            end
            local original_arrive=h.arrive
            local ok,why=S.run(h)
            assert(h.arrive == original_arrive) -- scenario must not mutate the shared harness
            return ok,why,table.concat(calls,',')
        end
    """)(scenario, ROOT.as_posix(), player, gs_harden, arrival_ok, setup_ok)
    assert ok is False
    if not arrival_ok:
        assert order == "jitter,arrive" and "MODEL arrival refused" in reason
    elif gs_harden and not setup_ok:
        assert order == "jitter,arrive,setup" and "MODEL setup refused" in reason
    else:
        assert order == ("jitter,arrive,setup,party,catch" if gs_harden else "jitter,arrive,party,catch")
        assert reason == "link route failed: MODEL stop before catch"


def _hardened_lines(player, disclosure=True):
    from tests.unit.test_gen2_duo_driver import poison_lines

    lines = poison_lines(player)
    for index, line in enumerate(lines):
        if line.startswith("DUO_GEN2 "):
            header = json.loads(line.partition(" ")[2])
            header["gs_harden"] = True
            lines[index] = "DUO_GEN2 " + json.dumps(header)
            break
    row = {"purpose": "condition_starter", "frame": 100, "symbol": "wPartyMon1HP",
           "domain": "System Bus", "address": 0xDCEE, "bytes_before": "0014", "bytes_after": "0050"}
    if disclosure:
        lines.insert(3, "SYNTH_SETUP " + json.dumps(row))
    return lines, row


@pytest.mark.parametrize("player", ["a", "b"])
def test_opted_poison_receipt_discloses_actual_setup_writes(player):
    from tests.unit.test_gen2_duo_driver import poison_verdict

    lines, row = _hardened_lines(player)
    problems, receipt = poison_verdict(lines)
    assert problems == [], problems
    assert receipt["input_mode"] == "SYNTH_setup_then_normal_buttons"
    for field in ("harness_write_scopes", "synth_disclosure"):
        assert len(receipt[field]) == 1
        assert dict(receipt[field][1].items()) == row


def test_opted_poison_receipt_refuses_missing_setup_disclosure():
    from tests.unit.test_gen2_duo_driver import poison_verdict

    lines, _ = _hardened_lines("a", disclosure=False)
    problems, receipt = poison_verdict(lines)
    assert receipt is None and "missing SYNTH_SETUP disclosure" in problems


def test_disabled_poison_propagation_cannot_pass_the_hardened_receipt():
    from tests.unit.test_gen2_duo_driver import poison_verdict

    lines, _ = _hardened_lines("b")
    lines = [line for line in lines if not line.startswith(("RX force_faint", "PARTY_HP_WRITE", "MEMORIAL_ACK"))]
    problems, receipt = poison_verdict(lines)
    assert receipt is None
    assert "no RX force_faint for B's linked key" in problems
    assert "missing PARTY_HP_WRITE marker" in problems
    assert any("no memorialize_done" in problem for problem in problems)


def test_hardened_poison_refuses_missing_starter_helper_before_catch():
    lua = LuaRuntime(unpack_returned_tuples=True)
    scenario = lua.eval("dofile")((ROOT / "lua/tests/duo/scenario_gen2_poison.lua").as_posix())
    ok, reason = lua.execute("""
        return function(S,root)
            return S.run({root=root,player='b',gs_harden=true,
                jitter=function() end,arrive=function() return true end,
                party=function() error('setup must precede party/catch') end})
        end
    """)(scenario, ROOT.as_posix())
    assert ok is False and reason == "no CONTINUE arrival: G/S poison starter setup unavailable"


@pytest.mark.parametrize("field,value", [("symbol", None), ("bytes_before", "0"), ("bytes_after", "000000")])
def test_hardened_poison_refuses_incomplete_setup_disclosure(field, value):
    from tests.unit.test_gen2_duo_driver import poison_verdict

    lines, row = _hardened_lines("a", disclosure=False)
    row[field] = value
    lines.insert(3, "SYNTH_SETUP " + json.dumps(row))
    problems, receipt = poison_verdict(lines)
    assert receipt is None and "incomplete SYNTH_SETUP disclosure" in problems


def test_default_poison_keeps_legacy_receipt_and_ignores_opted_setup_markers():
    from tests.unit.test_gen2_duo_driver import poison_lines, poison_verdict

    lines = poison_lines("a")
    lines.insert(3, "SYNTH_SETUP not parsed without opt-in")
    problems, receipt = poison_verdict(lines)
    assert problems == [], problems
    assert receipt["input_mode"] == "normal_buttons"
    assert len(receipt["harness_write_scopes"]) == 0
    assert receipt["synth_disclosure"] is None
