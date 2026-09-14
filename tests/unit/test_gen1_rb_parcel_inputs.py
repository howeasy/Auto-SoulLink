"""Pure R/B parcel input decisions; no emulator or game-state mutation."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def model():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/tests/gen1_rb_parcel_inputs.lua").read_text())
    expected = {"run_id": "r" * 32, "player": "a", "rom_sha1": "a" * 40,
                "context_generation": "c" * 32, "physical_instance": "p" * 32}
    driver = module.new(lua.table_from(expected))
    handshake = lua.table_from({**expected, "ready": True})
    status = lua.table_from({"observation_loop": True,
                             "host": lua.table_from({"held": False, "owner_id": "p" * 32}),
                             "context": lua.table_from({"context_generation": "c" * 32,
                                                        "physical_instance": "p" * 32}),
                             "runtime": lua.table_from({"connected": True,
                                                        "session_state": "admitted", "failed": False})})
    point = lua.table_from({"map": 0x28, "x": 5, "y": 3, "battle": 0,
                            "ball_count": 0, "parcel_count": 0, "money": 3000,
                            "got_parcel": False, "oak_got_parcel": False,
                            "menu_kind": "none", "joy_ignore": 0, "lab_script": 0})
    return driver, handshake, status, point


def step(driver, handshake, status, point, frame=16):
    return driver.step(handshake, status, point, frame)


def test_refuses_unpaired_hold_changed_context_and_unknown_battle():
    driver, handshake, status, point = model()
    buttons, phase = step(driver, None, status, point)
    assert phase == "await-pair-handshake" and not buttons["Down"]
    status.host.held = True
    with pytest.raises(LuaError, match="not free and owned"):
        step(driver, handshake, status, point)
    status.host.held = False
    status.context.context_generation = "other"
    with pytest.raises(LuaError, match="context changed"):
        step(driver, handshake, status, point)
    status.context.context_generation = "c" * 32
    point.battle, point.battle_type, point.party_hp, point.run_attempts = 2, 0, 20, 0
    with pytest.raises(LuaError, match="unexpected trainer"):
        step(driver, handshake, status, point)


def test_post_lab_north_parcel_return_and_oak_handoff():
    driver, handshake, status, point = model()
    point.y = 7
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "lab_exit" and buttons["Down"]
    point.map, point.x, point.y = 0, 12, 11
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "pallet_north" and buttons["Left"]
    point.map, point.x, point.y = 0x0C, 10, 35
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "route_north" and buttons["Up"]
    point.map, point.x, point.y = 1, 21, 35
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "viridian_mart" and buttons["Left"]
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "leave-with-parcel" and buttons["Right"]
    point.map, point.x, point.y = 1, 29, 19
    buttons, phase = step(driver, handshake, status, point, 96)
    assert phase == "viridian_south" and buttons["Down"]
    point.map, point.x, point.y = 0x0C, 10, 0
    buttons, phase = step(driver, handshake, status, point, 112)
    assert phase == "route_south" and buttons["Down"]
    point.map, point.x, point.y = 0, 10, 0
    buttons, phase = step(driver, handshake, status, point, 128)
    assert phase == "pallet_lab" and buttons["Down"]
    point.map, point.x, point.y = 0x28, 5, 3
    buttons, phase = step(driver, handshake, status, point, 144)
    assert phase == "give-parcel-to-oak" and buttons["A"] and buttons["Up"]
    point.parcel_count, point.oak_got_parcel, point.lab_script = 0, True, 18
    buttons, phase = step(driver, handshake, status, point, 160)
    assert phase == "lab_exit" and buttons["Down"]


def test_cancel_readback_then_first_ball_debit():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    step(driver, handshake, status, point)
    point.map, point.x, point.y = 0x28, 5, 3
    step(driver, handshake, status, point, 24)
    point.parcel_count, point.oak_got_parcel, point.lab_script = 0, True, 18
    step(driver, handshake, status, point, 32)
    point.map, point.x, point.y = 0x2A, 2, 5
    point.facing, point.menu_kind = "left", "mart-confirm"
    point.confirm_index = 0
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "cancel-first-purchase" and buttons["B"]
    point.menu_kind, point.menu_index, point.item_id = "mart-item", 0, 4
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "mart-poke-ball" and buttons["A"]
    point.menu_kind = "mart-confirm"
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "confirm-first-ball" and buttons["A"]
    point.menu_kind, point.ball_count, point.money = "none", 1, 2800
    buttons, phase = step(driver, handshake, status, point, 96)
    assert phase == "first-ball-readback" and not any(buttons.values())


def test_cancel_requires_unchanged_bag_and_money():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    step(driver, handshake, status, point)
    point.map, point.x, point.y = 0x28, 5, 3
    step(driver, handshake, status, point, 24)
    point.parcel_count, point.oak_got_parcel, point.lab_script = 0, True, 18
    step(driver, handshake, status, point, 32)
    point.map, point.x, point.y = 0x2A, 2, 5
    point.menu_kind, point.confirm_index = "mart-confirm", 0
    step(driver, handshake, status, point, 48)
    point.menu_kind, point.ball_count = "mart-item", 1
    with pytest.raises(LuaError, match="cancel changed"):
        step(driver, handshake, status, point, 64)


def test_unknown_menu_and_unread_parcel_refuse_completion():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.menu_kind = "unknown"
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "unexpected-menu" and not any(buttons.values())
    point.menu_kind, point.got_parcel, point.parcel_count = "none", True, 1
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "leave-with-parcel" and not buttons["A"]


def test_route_one_wild_run_menu_and_observed_escape_resume():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x0C, 10, 35
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "route_north" and buttons["Up"]
    point.y, point.battle, point.battle_type = 31, 1, 0
    point.party_hp, point.text_box, point.run_attempts = 20, 0x0B, 0
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 14, 9, 1, 0
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "wild-select-right-column" and buttons["Right"] and not buttons["A"]
    point.menu_x = 15
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "wild-select-run" and buttons["Down"] and not buttons["A"]
    point.menu_index = 1
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "wild-attempt-run" and buttons["A"]
    point.battle, point.battle_result = 0, 2
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "route_north" and buttons["Left"]


def test_wild_refuses_unknown_menu_and_unproved_exit():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x0C, 10, 31
    point.battle, point.battle_type, point.party_hp, point.run_attempts = 1, 0, 20, 0
    point.text_box, point.menu_y, point.menu_x, point.menu_max = 0x0B, 14, 8, 1
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "unknown-wild-menu" and not any(buttons.values())
    point.battle, point.battle_result = 0, 0
    with pytest.raises(LuaError, match="without observed escape"):
        step(driver, handshake, status, point, 32)


def test_failed_wild_run_retries_only_known_menu_and_has_bound():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x0C, 10, 31
    point.battle, point.battle_type, point.party_hp = 1, 0, 15
    point.run_attempts, point.text_box = 1, 0x0B
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 14, 15, 1, 1
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "wild-attempt-run" and buttons["A"]
    point.text_box = 0
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "wild-text-state-unknown" and not any(buttons.values())
    point.text_box, point.run_attempts = 0x0B, 8
    with pytest.raises(LuaError, match="attempt bound exceeded"):
        step(driver, handshake, status, point, 48)


def test_mart_initial_text_then_auto_walk_then_parcel_text():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 3, 7
    point.mart_script, point.simulated_joypad_index = 0, 0
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "mart-initial-clerk-dialogue" and buttons["A"]
    point.mart_script, point.simulated_joypad_index = 1, 2
    point.x, point.y = 2, 5
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "mart-auto-walk" and not any(buttons.values())
    point.simulated_joypad_index = 0
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "mart-parcel-dialogue" and buttons["A"]
    point.mart_script, point.got_parcel, point.parcel_count = 2, True, 1
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "leave-with-parcel" and buttons["Right"]


def test_mart_initial_ack_requires_entrance_and_unmasked_buttons():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.mart_script = 0
    buttons, phase = step(driver, handshake, status, point)
    assert phase == "mart-parcel-wait" and not any(buttons.values())
    point.x, point.y, point.joy_ignore = 3, 7, 0xFF
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "mart-parcel-wait" and not any(buttons.values())


def test_removed_parcel_waits_for_oak_event_then_repeats_outbound_waypoints():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    step(driver, handshake, status, point)
    point.map, point.x, point.y = 0x28, 5, 3
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "give-parcel-to-oak" and buttons["A"]
    point.parcel_count, point.lab_script, point.joy_ignore = 0, 16, 0xFC
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "oak-delivery-dialogue" and buttons["A"] and not buttons["Down"]
    point.oak_got_parcel, point.lab_script = True, 17
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "oak-post-event-dialogue" and buttons["A"]
    point.lab_script, point.joy_ignore = 18, 0
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "lab_exit" and buttons["Down"]
    point.map, point.x, point.y = 0, 12, 11
    buttons, phase = step(driver, handshake, status, point, 96)
    assert phase == "pallet_north" and buttons["Left"]
    point.map, point.x, point.y = 0x0C, 10, 35
    buttons, phase = step(driver, handshake, status, point, 112)
    assert phase == "route_north" and buttons["Up"]
    point.map, point.x, point.y = 1, 21, 35
    buttons, phase = step(driver, handshake, status, point, 128)
    assert phase == "viridian_mart" and buttons["Left"]


def test_completed_first_outbound_does_not_skip_second_outbound():
    driver, handshake, status, point = model()
    frame = 0

    def visit(map_id, positions):
        nonlocal frame
        point.map = map_id
        last = None
        for x, y in positions:
            point.x, point.y = x, y
            frame += 16
            last = step(driver, handshake, status, point, frame)
        return last

    visit(0x28, [(5, 3), (5, 11)])
    visit(0, [(12, 11), (9, 11), (9, 2), (10, 2), (10, 0)])
    visit(0x0C, [(10, 35), (10, 31), (8, 31), (8, 24), (12, 24),
                 (12, 22), (9, 22), (9, 14), (14, 14), (14, 4),
                 (11, 4), (11, 0)])
    visit(1, [(21, 35), (20, 35), (20, 30), (19, 30), (19, 20),
              (29, 20), (29, 19)])
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    frame += 16
    step(driver, handshake, status, point, frame)
    point.map, point.x, point.y = 0x28, 5, 3
    frame += 16
    step(driver, handshake, status, point, frame)
    point.parcel_count, point.oak_got_parcel, point.lab_script = 0, True, 18
    frame += 16
    buttons, phase = step(driver, handshake, status, point, frame)
    assert phase == "lab_exit" and buttons["Down"]
    visit(0x28, [(5, 11)])
    buttons, phase = visit(0, [(12, 11)])
    assert phase == "pallet_north" and buttons["Left"]
    buttons, phase = visit(0x0C, [(10, 35)])
    assert phase == "route_north" and buttons["Up"]
    buttons, phase = visit(1, [(21, 35)])
    assert phase == "viridian_mart" and buttons["Left"]


def test_unknown_menu_kind_idles():
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x2A, 2, 5
    point.got_parcel, point.parcel_count = True, 1
    step(driver, handshake, status, point)
    point.map, point.x, point.y = 0x28, 5, 3
    step(driver, handshake, status, point, 24)
    point.parcel_count, point.oak_got_parcel, point.lab_script = 0, True, 18
    step(driver, handshake, status, point, 32)
    point.map, point.x, point.y, point.facing = 0x2A, 2, 5, "left"
    point.menu_kind = "unknown"
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "mart-unknown-wait" and not any(buttons.values())
    # A pending cancel is not completed on an ambiguous display either.
    point.menu_kind, point.confirm_index = "mart-confirm", 0
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "cancel-first-purchase" and buttons["B"]
    point.menu_kind = "unknown"
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "mart-unknown-wait" and not any(buttons.values())
    point.menu_kind, point.ball_count = "mart-item", 1
    with pytest.raises(LuaError, match="cancel changed"):
        step(driver, handshake, status, point, 96)


def test_map_edges_keep_driving_until_the_engine_changes_map():
    # Live parcel attempt 1: pallet_north ended on the edge cell and (9,1) is a tree
    # (PalletTown.blk[4]=$4F -> overworld.bst[1278]=$3A); the engine only changes map
    # once the player steps past the edge (home/overworld.asm:622-635), so a table that
    # ends exactly on y0/y35 idles one step short. follow() advances only on visited
    # waypoints, so walk each table in order like the real player does.
    driver, handshake, status, point = model()
    point.parcel_count, point.got_parcel, point.oak_got_parcel = 0, False, False
    point.lab_script, point.menu_kind, point.ball_count, point.money = 18, "none", 0, 3000
    frame = 0

    def walk(map_id, positions):
        nonlocal frame
        point.map = map_id
        last = None
        for x, y in positions:
            point.x, point.y = x, y
            frame += 16
            last = step(driver, handshake, status, point, frame)
        return last

    buttons, phase = walk(0, [(12, 11), (9, 11), (9, 2)])
    assert phase == "pallet_north" and buttons["Right"] and not buttons["Up"]  # never Up into (9,1)
    buttons, phase = walk(0, [(10, 2), (10, 0)])
    assert phase == "pallet_north" and buttons["Up"]
    buttons, phase = walk(0x0C, [(10, 35), (10, 31), (8, 31), (8, 24), (12, 24), (12, 22), (9, 22),
                                 (9, 14), (14, 14), (14, 4), (11, 4), (11, 0)])
    assert phase == "route_north" and buttons["Up"]
    point.parcel_count, point.got_parcel = 1, True
    buttons, phase = walk(1, [(29, 20), (19, 20), (19, 30), (20, 30), (20, 35)])
    assert phase == "viridian_south" and buttons["Down"]
    buttons, phase = walk(0x0C, [(10, 4), (14, 4), (14, 14), (9, 14), (9, 22), (12, 22), (12, 24),
                                 (8, 24), (8, 31), (10, 31), (10, 35)])
    assert phase == "route_south" and buttons["Down"]


def test_parcel_is_handed_to_oak_from_the_post_rival_noop_script():
    # Live parcel attempt 3: after the rival leaves, wOaksLabCurScript stays at
    # SCRIPT_OAKSLAB_NOOP (18, scripts/OaksLab.asm OaksLabPlayerWatchRivalExitScript);
    # the delivery starts from Oak's text script (:1015 -> script 15), so the driver
    # must talk to Oak in state 18, not wait for 0.
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x28, 5, 3
    point.parcel_count, point.got_parcel, point.oak_got_parcel = 1, True, False
    point.lab_script, point.joy_ignore, point.menu_kind = 18, 0, "none"
    buttons, phase = step(driver, handshake, status, point, 16)
    assert phase == "give-parcel-to-oak" and buttons["A"] and buttons["Up"]


def test_oak_delivery_and_post_event_text_is_advanced_whenever_a_is_unmasked():
    # Live parcel attempt 4: OaksLabRivalArrivesAtOaksRequestScript (15) shows the
    # GRAMPS text with wJoyIgnore 0 and script 16 masks $F0 (scripts/OaksLab.asm:510-560);
    # only $FF (scripted NPC walking) forbids A, so waiting for exactly $FC idles forever.
    driver, handshake, status, point = model()
    point.map, point.x, point.y = 0x28, 5, 3
    point.parcel_count, point.got_parcel, point.oak_got_parcel = 1, True, False
    point.lab_script, point.joy_ignore, point.menu_kind = 18, 0, "none"
    step(driver, handshake, status, point, 16)  # admits the delivery
    point.parcel_count, point.lab_script, point.joy_ignore = 0, 15, 0
    buttons, phase = step(driver, handshake, status, point, 32)
    assert phase == "oak-delivery-dialogue" and buttons["A"]
    point.lab_script, point.joy_ignore = 16, 0xF0
    buttons, phase = step(driver, handshake, status, point, 48)
    assert phase == "oak-delivery-dialogue" and buttons["A"]
    point.joy_ignore, point.npc_moving = 0xFF, True
    buttons, phase = step(driver, handshake, status, point, 64)
    assert phase == "oak-delivery-script-wait" and not buttons["A"]
    point.oak_got_parcel, point.lab_script, point.joy_ignore, point.npc_moving = True, 17, 0xF0, False
    buttons, phase = step(driver, handshake, status, point, 80)
    assert phase == "oak-post-event-dialogue" and buttons["A"]
