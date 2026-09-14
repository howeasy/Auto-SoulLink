"""Pure Lua 5.4 model of the R/B START-menu save driver; never opens an emulator."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
IDLE = {"A": False, "B": False, "Start": False, "Select": False,
        "Up": False, "Down": False, "Left": False, "Right": False}


def model():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/tests/gen1_rb_save_inputs.lua").read_text())
    expected = {"run_id": "r" * 32, "player": "a", "rom_sha1": "a" * 40,
                "context_generation": "c" * 32, "physical_instance": "p" * 32}
    driver = module.new(lua.table_from(expected))
    handshake = lua.table_from({**expected, "ready": True})
    status = lua.table_from({"observation_loop": True,
                             "host": lua.table_from({"held": False, "lease_owned": True, "owner_id": "p" * 32}),
                             "context": lua.table_from({"context_generation": "c" * 32,
                                                        "physical_instance": "p" * 32}),
                             "runtime": lua.table_from({"connected": True, "session_state": "admitted",
                                                        "failed": False})})
    # Lab overworld after the rival loss: no text, stale battle-menu geometry, no in-game save yet.
    point = lua.table_from({"map": 0x28, "battle": 0, "joy_ignore": 0, "font_loaded": False,
                            "save_file_status": 1, "start_menu_save": False, "text_box": 0x0B,
                            "menu_y": 14, "menu_x": 15, "menu_max": 1, "menu_index": 1})
    return lua, driver, handshake, status, point


def buttons(table):
    return {key: bool(table[key]) for key in IDLE}


def test_refuses_input_without_handshake_and_rejects_foreign_context():
    lua, driver, handshake, status, point = model()
    pressed, phase = driver.step(None, status, point, 10)
    assert phase == "await-pair-handshake" and buttons(pressed) == IDLE
    status.host.held = True
    with pytest.raises(LuaError, match="not free and owned"):
        driver.step(handshake, status, point, 11)
    status.host.held = False
    handshake.run_id = "other"
    with pytest.raises(LuaError, match="foreign save handshake"):
        driver.step(handshake, status, point, 12)


def test_opens_start_menu_only_from_free_lab_overworld():
    _, driver, handshake, status, point = model()
    pressed, phase = driver.step(handshake, status, point, 16)
    assert phase == "save-open-start-menu" and buttons(pressed) == {**IDLE, "Start": True}
    point.joy_ignore = 0xFF
    pressed, phase = driver.step(handshake, status, point, 17)
    assert phase == "save-overworld-wait" and buttons(pressed) == IDLE
    point.joy_ignore, point.map = 0, 0
    with pytest.raises(LuaError, match="left the lab overworld"):
        driver.step(handshake, status, point, 18)


def test_save_file_status_is_never_an_oracle():
    """Live r1: wSaveFileStatus ($D088) already read 2 during the rival battle on a fresh cartridge."""
    _, driver, handshake, status, point = model()
    point.save_file_status = 2
    pressed, phase = driver.step(handshake, status, point, 16)
    assert phase == "save-open-start-menu" and buttons(pressed) == {**IDLE, "Start": True}
    point.font_loaded, point.start_menu_save = True, True
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 2, 11, 6, 3
    pressed, phase = driver.step(handshake, status, point, 17)
    assert phase == "save-choose-save" and buttons(pressed) == {**IDLE, "A": True}
    point.start_menu_save, point.text_box = False, 0x14
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 8, 1, 1, 0
    pressed, phase = driver.step(handshake, status, point, 32)
    assert phase == "save-confirm" and buttons(pressed) == {**IDLE, "A": True}
    point.save_file_status, point.text_box = 0, 0  # garbage after the save must not matter either
    pressed, phase = driver.step(handshake, status, point, 33)
    assert phase == "save-await-close" and buttons(pressed) == IDLE
    point.font_loaded = False
    pressed, phase = driver.step(handshake, status, point, 34)
    assert phase == "save-witnessed" and buttons(pressed) == IDLE


@pytest.mark.parametrize("index,button,phase", [
    (0, "Down", "save-select-save"), (2, "Down", "save-select-save"),
    (5, "Up", "save-select-save"), (3, "A", "save-choose-save")])
def test_start_menu_without_pokedex_selects_save_at_index_3(index, button, phase):
    _, driver, handshake, status, point = model()
    point.font_loaded, point.start_menu_save = True, True
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 2, 11, 6, index
    pressed, seen = driver.step(handshake, status, point, 16)
    assert seen == phase and buttons(pressed) == {**IDLE, button: True}


def test_start_menu_with_pokedex_geometry_or_missing_save_row_is_never_pressed():
    _, driver, handshake, status, point = model()
    point.font_loaded, point.start_menu_save = True, True
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 2, 11, 7, 3
    pressed, phase = driver.step(handshake, status, point, 16)
    assert phase == "save-menu-wait" and buttons(pressed) == IDLE
    point.menu_max, point.start_menu_save = 6, False
    pressed, phase = driver.step(handshake, status, point, 17)
    assert phase == "save-menu-wait" and buttons(pressed) == IDLE


def test_save_prompt_yes_then_terminal_only_after_menus_closed():
    _, driver, handshake, status, point = model()
    point.font_loaded, point.text_box = True, 0x14
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 8, 1, 1, 1
    pressed, phase = driver.step(handshake, status, point, 16)
    assert phase == "save-select-yes" and buttons(pressed) == {**IDLE, "Up": True}
    point.menu_index = 0
    pressed, phase = driver.step(handshake, status, point, 17)
    assert phase == "save-confirm" and buttons(pressed) == {**IDLE, "A": True}
    # The prompt is still up after the tap: keep confirming, never idle on a known prompt.
    pressed, phase = driver.step(handshake, status, point, 18)
    assert phase == "save-confirm" and buttons(pressed) == IDLE  # frame 18 is outside the tap window
    point.text_box = 0  # "Now saving..." / GAME SAVED text: unknown menu geometry, wait
    pressed, phase = driver.step(handshake, status, point, 19)
    assert phase == "save-await-close" and buttons(pressed) == IDLE
    point.font_loaded, point.start_menu_save = False, True  # START menu screen restored from buffer 2
    pressed, phase = driver.step(handshake, status, point, 20)
    assert phase == "save-await-close" and buttons(pressed) == IDLE
    point.start_menu_save = False
    pressed, phase = driver.step(handshake, status, point, 21)
    assert phase == "save-witnessed" and buttons(pressed) == IDLE


def test_menus_closed_without_a_confirmation_is_not_the_terminal():
    _, driver, handshake, status, point = model()
    pressed, phase = driver.step(handshake, status, point, 16)
    assert phase == "save-open-start-menu"
    point.font_loaded = True  # a menu opened, then closed again with nothing confirmed
    driver.step(handshake, status, point, 17)
    point.font_loaded = False
    pressed, phase = driver.step(handshake, status, point, 32)
    assert phase == "save-open-start-menu" and buttons(pressed) == {**IDLE, "Start": True}


def test_close_after_confirmation_is_bounded():
    _, driver, handshake, status, point = model()
    point.font_loaded, point.text_box = True, 0x14
    point.menu_y, point.menu_x, point.menu_max, point.menu_index = 8, 1, 1, 0
    driver.step(handshake, status, point, 16)
    point.text_box = 0
    for frame in range(17, 17 + 1800):
        driver.step(handshake, status, point, frame)
    with pytest.raises(LuaError, match="did not close after the save"):
        driver.step(handshake, status, point, 17 + 1800)


def test_frame_must_advance():
    _, driver, handshake, status, point = model()
    driver.step(handshake, status, point, 16)
    with pytest.raises(LuaError, match="frame did not advance"):
        driver.step(handshake, status, point, 16)
