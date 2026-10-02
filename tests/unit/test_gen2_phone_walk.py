"""MODEL replays of native phone interruptions; no emulator or production writes."""
import json

import pytest
from lupa import LuaError, LuaRuntime

from tests.live.test_gen2_new_gates import phone_call_facts
from tests.unit.test_gen2_duo_driver import FAINT_INPUTS, frame_align
from tests.unit.test_gen2_scripted_gate import Sim, library, make_env, make_root


def replay(points):
    lua, frame = frame_align()
    faint = lua.execute(FAINT_INPUTS.read_text(encoding="utf-8"))
    driver = faint.driver(lua.eval("{walk_direction=function() return 'Left' end}"),
                          lua.table_from({}), lua.table_from({"target": 1}))
    seen = []
    host, observe = lua.eval("""function(points, record)
        local i = 0
        return {run=function(spec, step)
            for n = 1, #points do
                local buttons, phase = step(n)
                record(phase, buttons)
            end
            return 'done'
        end}, function() i = i + 1 return points[i] end
    end""")(lua.table_from([lua.table_from(p, recursive=True) for p in points]),
            lambda phase, buttons: seen.append((phase, sorted(k for k, v in buttons.items() if v))))
    diag = lua.table_from({"log": lambda _: None, "frame": lambda: 0,
                           "screen": lambda: lua.table_from({}), "where": lambda: "-"})
    ok, why = frame.play(host, lua.table_from({"terminal": driver.terminal}), driver, observe, diag)
    return ok, why, seen


WALK = {"battle_mode": 0, "overworld_ready": True, "x": 1, "y": 1}
CALL = {"battle_mode": 0, "overworld_ready": False, "phone_call": True,
        "input_ready": True, "ui": {"kind": "prompt_button"}}


def test_walk_answers_proven_phone_prompts_releases_a_and_resumes_route():
    ok, why, seen = replay([WALK, CALL, CALL, CALL, WALK])
    assert ok, why
    assert seen == [("walk", ["Left"]), ("walk", ["A"]), ("walk", []),
                    ("walk", ["A"]), ("walk", ["Left"])]


def test_walk_still_refuses_non_call_prompt():
    ok, why, _ = replay([WALK, {**CALL, "phone_call": False}])
    assert not ok and "UI is not valid in phase walk: prompt_button" in why


def test_call_already_up_at_leg_start_and_not_ready_frames_are_safe():
    ok, why, seen = replay([{**CALL, "input_ready": False}, CALL, CALL, WALK])
    assert ok, why
    assert seen == [("walk", []), ("walk", ["A"]), ("walk", []), ("walk", ["Left"])]


def test_call_marker_does_not_accept_an_unexpected_menu():
    ok, why, _ = replay([WALK, {**CALL, "ui": {"kind": "yes_no"}}])
    assert not ok and "UI is not valid in phase walk: yes_no" in why


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_only_real_ring_site_arms_phone_and_close_or_overworld_clears_it(tmp_path, title):
    root = make_root(tmp_path, title)
    _, env = make_env(root, title, "town")
    phone = phone_call_facts(title, "clean")
    env["SLINK_GEN2_PHONE_CALL"] = json.dumps(phone)
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), title, "town")
    gate, ctx = library(sim, env)
    gate.hooks(ctx)
    observe = gate.observer(ctx)
    sim.fire("overworld_tick")
    sim.fire("prompt_button")
    assert observe().phone_call is False  # text alone cannot authorize A
    site = phone["ring"]
    sim.run_at(site["bank"] + 1, site["addr"])
    assert observe().phone_call is False  # same PC in a different bank is not a call
    sim.run_at(site["bank"], site["addr"])
    sim.fire("prompt_button")
    assert observe().phone_call is True
    sim.execute("Script_closetext")
    sim.fire("prompt_button")  # a scene can start before the next OWPlayerInput
    assert observe().phone_call is False
    sim.run_at(site["bank"], site["addr"])
    sim.put("wBattleMode", [1])
    assert observe().phone_call is False
    sim.put("wBattleMode", [0])
    sim.fire("prompt_button")  # post-battle text BEFORE any OW tick (review cx-158f3337 F3)
    assert observe().phone_call is False  # a battle ends any call: the latch must not survive it
    sim.fire("overworld_tick")
    sim.fire("prompt_button")
    assert observe().phone_call is False  # a later unrelated text must fail again


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("kind", ["clean", "overlay"])
def test_phone_hook_facts_bind_executed_cartridge(title, kind):
    from tools.gen2_fixtures import exec_context

    ctx = exec_context(title, kind)
    phone = phone_call_facts(title, kind)
    for key, symbol in (("ring", "RingTwice_StartCall"), ("close", "Script_closetext")):
        site = phone[key]
        assert (site["bank"], site["addr"]) == tuple(ctx.symbol(symbol))
        assert bytes.fromhex(site["hex"]) == ctx.rom[site["flat"]:site["flat"] + len(site["hex"]) // 2]
    assert phone["kind"] == kind


@pytest.mark.parametrize("fault", ["rom", "kind", "ring_bytes", "close_bytes"])
def test_wrong_phone_fact_identity_or_code_bytes_refuses_before_play(tmp_path, fault):
    root = make_root(tmp_path, "crystal")
    _, env = make_env(root, "crystal", "town")
    phone = phone_call_facts("crystal", "clean")
    if fault == "rom":
        phone["rom_sha1"] = "0" * 40
    elif fault == "kind":
        phone["kind"] = "overlay"
    else:
        phone[fault.removesuffix("_bytes")]["hex"] = "000000"
    env["SLINK_GEN2_PHONE_CALL"] = json.dumps(phone)
    sim = Sim(LuaRuntime(unpack_returned_tuples=True), "crystal", "town")
    with pytest.raises(LuaError):
        gate, ctx = library(sim, env)
        gate.hooks(ctx)
