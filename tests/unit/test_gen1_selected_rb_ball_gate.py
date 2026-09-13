"""Pure Lua 5.4 route-control model; never opens an emulator."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def model(player="a"):
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/tests/gen1_rb_ball_gate_inputs.lua").read_text())
    expected = {"run_id": "r" * 32, "player": player, "rom_sha1": "a" * 40,
                "context_generation": "c" * 32, "physical_instance": "p" * 32}
    driver = module.new(lua.table_from(expected))
    handshake = lua.table_from({**expected, "ready": True})
    status = lua.table_from({"observation_loop": True,
                             "host": lua.table_from({"held": False, "lease_owned": True,
                                                     "owner_id": "p" * 32}),
                             "context": lua.table_from({"context_generation": "c" * 32,
                                                        "physical_instance": "p" * 32}),
                             "runtime": lua.table_from({"connected": True, "session_state": "admitted",
                                                        "failed": False})})
    point = lua.table_from({"map": 0x26, "x": 4, "y": 4, "party_count": 0, "battle": 0,
                            "pallet_script": 0, "joy_ignore": 0, "npc_moving": False})
    return lua, driver, handshake, status, point


def test_rb_route_refuses_input_without_current_pair_handshake():
    _, driver, _, status, point = model()
    buttons, phase = driver.step(None, status, point, 10)
    assert phase == "await-pair-handshake" and not buttons["Up"] and not buttons["A"]


def test_rb_route_rejects_hold_and_changed_context():
    lua, driver, handshake, status, point = model()
    status.host.held = True
    with pytest.raises(LuaError, match="owned free service"):
        driver.step(handshake, status, point, 10)
    status.host.held = False
    status.context.context_generation = "d" * 32
    with pytest.raises(LuaError, match="changed admitted context"):
        driver.step(handshake, status, point, 10)
    status.context.context_generation = "c" * 32
    handshake.run_id = "other"
    with pytest.raises(LuaError, match="foreign paired route handshake"):
        driver.step(handshake, status, point, 10)


@pytest.mark.parametrize("player,target", [("a", 8), ("b", 6)])
def test_rb_route_chooses_distinct_growl_starter_sites(player, target):
    _, driver, handshake, status, point = model(player)
    point.map, point.x, point.y = 0x28, target, 4
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "choose-growl-starter" and buttons["Up"] and buttons["A"]


@pytest.mark.parametrize("map_id,x,y,button", [
    (0x26, 3, 6, "Right"), (0x26, 4, 6, "Up"), (0x26, 4, 1, "Right"),
    (0x25, 7, 1, "Down"), (0x25, 7, 2, "Left"), (0x25, 2, 2, "Down"),
    (0x00, 5, 5, "Down"), (0x00, 5, 6, "Right"), (0x00, 10, 6, "Up"),
    (0x28, 5, 3, "Down"), (0x28, 5, 4, "Right"),
])
def test_rb_source_waypoints_avoid_known_blocking_rows(map_id, x, y, button):
    _, driver, handshake, status, point = model()
    point.map, point.x, point.y = map_id, x, y
    buttons, _ = driver.step(handshake, status, point, 16)
    assert buttons[button]


@pytest.mark.parametrize("script", [1, 3])
def test_pallet_oak_dialogue_receives_only_allowed_normal_ack(script):
    _, driver, handshake, status, point = model()
    point.map, point.x, point.y = 0, 10, 1
    point.pallet_script, point.joy_ignore, point.npc_moving = script, 0xFC, False
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "pallet-oak-dialogue" and buttons["A"] and not buttons["Up"]


@pytest.mark.parametrize("script", [2, 3, 4])
def test_pallet_npc_movement_or_all_key_mask_stays_idle(script):
    _, driver, handshake, status, point = model()
    point.map, point.x, point.y = 0, 10, 1
    point.pallet_script, point.joy_ignore, point.npc_moving = script, 0xFF, True
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "pallet-script-wait" and not buttons["A"] and not buttons["Up"]


def test_rb_route_refuses_damage_or_struggle_during_lab_rival():
    _, driver, handshake, status, point = model()
    point.map, point.party_count, point.battle, point.opponent = 0x28, 1, 2, 225
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 12, 5, 3, 2
    point.move2, point.move2_pp = 0x2d, 0
    with pytest.raises(LuaError, match="Growl unavailable"):
        driver.step(handshake, status, point, 16)
    point.move2_pp = 30
    buttons, phase = driver.step(handshake, status, point, 17)
    assert phase == "use-growl" and buttons["A"]
    point.menu_index = 1
    buttons, phase = driver.step(handshake, status, point, 32)
    assert phase == "select-growl" and buttons["Down"] and not buttons["A"]


def test_rb_route_requires_lab_loss_and_heal_before_complete():
    _, driver, handshake, status, point = model()
    point.map, point.party_count, point.battle, point.opponent = 0x28, 1, 2, 225
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 14, 9, 1, 0
    driver.step(handshake, status, point, 16)
    point.battle, point.lab_rival_done, point.battle_result, point.party_hp = 0, True, 1, 20
    point.lab_script = 12
    buttons, phase = driver.step(handshake, status, point, 17)
    assert phase == "lab-loss-complete" and not buttons["A"] and not buttons["Down"]


def test_nickname_refusal_waits_for_observed_lab_script_transition():
    _, driver, handshake, status, point = model()
    point.map, point.party_count, point.battle = 0x28, 1, 0
    point.lab_script, point.text_box = 7, 0x14
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "decline-nickname" and buttons["B"]
    buttons, phase = driver.step(handshake, status, point, 17)
    assert phase == "decline-nickname" and not buttons["A"]
    point.lab_script = 8
    buttons, phase = driver.step(handshake, status, point, 18)
    assert phase != "decline-nickname"


def test_captured_lab_choose_mon_speech_advances_only_allowed_text_button():
    _, driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x28, 5, 3
    point.party_count, point.lab_script, point.joy_ignore = 0, 5, 0xFC
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "lab-oak-choose-mon-speech"
    assert buttons["A"] and not buttons["Down"]
    point.joy_ignore = 0xFF
    buttons, phase = driver.step(handshake, status, point, 17)
    assert phase == "lab-oak-speech-wait" and not buttons["A"] and not buttons["Down"]


def test_captured_lab_script6_exits_possible_leftover_text_locally():
    _, driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x28, 5, 3
    point.party_count, point.lab_script, point.joy_ignore = 0, 6, 0
    buttons, phase = driver.step(handshake, status, point, 16)
    assert phase == "lab-text-exit" and buttons["B"] and not buttons["A"] and not buttons["Down"]
    buttons, phase = driver.step(handshake, status, point, 18)
    assert phase == "lab-text-exit" and buttons["Down"] and not buttons["B"]


def test_checkpoint_requires_acked_source_faint_and_alive_preball_link():
    from tests.live.test_gen1_selected_rb_ball_gate import verify_starter_rival_checkpoint

    document = {"components": {"gen1-starter-settlement": {
        "sources": {"a": {}, "b": {}},
        "settled": {"a": {"member_id": "member-a"}, "b": {"member_id": "member-b"}},
        "link_id": "linked", "rejection": None}},
        "rules": {"core": {"links": [{"status": "alive", "area_id": "oaks_lab",
                                     "a": {"species": 1}, "b": {"species": 4}}],
                           "pokeballs_obtained": {"a": False, "b": False}}}}
    markers = {player: {"stage": "lab-loss-complete", "point": {
        "lab_rival_done": True, "battle_result": 1, "party_hp": 20}} for player in ("a", "b")}
    rows = []
    for player in ("a", "b"):
        for index, kind in enumerate(("starter_begin", "starter_end", "battle_faint"), start=1):
            rows.append((player, index, {"event": "observation", "signals": {"signals": [
                {"kind": kind, "frame": index, "point": {"battle_hp": 0 if kind == "battle_faint" else 20}}]}},
                {"ack": "ACK", "engine_evidence_digest": "digest"}, str(index) * 32))
    result = verify_starter_rival_checkpoint(document, rows, markers)
    assert result["link"]["status"] == "alive" and not result["deaths"]
    rows[-1] = (*rows[-1][:3], {"ack": "NACK"}, rows[-1][4])
    with pytest.raises(AssertionError):
        verify_starter_rival_checkpoint(document, rows, markers)
