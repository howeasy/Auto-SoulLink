"""Pure Viridian Mart menu signature (Lua 5.4 under lupa); no emulator."""

import pytest
from lupa.lua54 import LuaRuntime

from tests.unit.test_gen1_rb_parcel_inputs import ROOT

POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL = 0x04, 0x0B, 0x0F, 0x0C


def signature():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/tests/gen1_rb_mart_signature.lua").read_text())
    return lambda **raw: module.mart_menu(lua.table_from(raw))


def in_mart(**over):
    raw = {"map": 0x2A, "mart_script": 2, "font_loaded": True, "list_menu_id": 2,
           "text_box": 0x0D, "menu_y": 4, "menu_x": 5, "menu_max": 2, "menu_index": 0,
           "menu_watch_oob": 1, "list_scroll_offset": 0, "menu_exit_method": 0,
           "quantity": 0, "cur_item": BURN_HEAL}
    raw.update(over)
    return raw


def test_outside_mart_or_no_display_is_none():
    mart_menu = signature()
    assert mart_menu(**in_mart(map=0x01)) == ("none", 0, -1)
    assert mart_menu(**in_mart(mart_script=1)) == ("none", 0, -1)
    assert mart_menu(**in_mart(list_menu_id=0, font_loaded=False)) == ("none", 0, -1)
    # wListMenuID stays 2 after the Mart closes: never proof of free movement.
    assert mart_menu(**in_mart(font_loaded=False))[0] == "unknown"
    # A live text display before the Mart list is armed is a display, not free movement.
    assert mart_menu(**in_mart(list_menu_id=0, font_loaded=True))[0] == "unknown"


def test_mart_choice_signature():
    mart_menu = signature()
    for index in (0, 1, 2):
        assert mart_menu(**in_mart(text_box=0x0E, menu_y=1, menu_x=1, menu_index=index)) == (
            "mart-choice", 0, -1)
    assert mart_menu(**in_mart(text_box=0x0E, menu_y=1, menu_x=1, menu_index=3))[0] == "unknown"


def test_cur_item_trap():
    mart_menu = signature()
    # wCurItem ends at the last printed price (BURN_HEAL); the row under the cursor is POKE_BALL.
    assert mart_menu(**in_mart(cur_item=BURN_HEAL, menu_index=0, list_scroll_offset=0)) == (
        "mart-item", POKE_BALL, -1)


def test_item_rows_follow_scroll_and_cancel_row_is_zero():
    mart_menu = signature()
    assert mart_menu(**in_mart(menu_index=0, list_scroll_offset=1)) == ("mart-item", ANTIDOTE, -1)
    assert mart_menu(**in_mart(menu_index=2, list_scroll_offset=0)) == ("mart-item", PARLYZ_HEAL, -1)
    assert mart_menu(**in_mart(menu_index=1, list_scroll_offset=2)) == ("mart-item", BURN_HEAL, -1)
    assert mart_menu(**in_mart(menu_index=2, list_scroll_offset=2)) == ("mart-item", 0, -1)


def test_mart_quantity_signature():
    mart_menu = signature()
    assert mart_menu(**in_mart(menu_watch_oob=0, menu_exit_method=1, quantity=1)) == (
        "mart-quantity", 0, -1)
    assert mart_menu(**in_mart(menu_watch_oob=0, menu_exit_method=1, quantity=99))[0] == "mart-quantity"
    assert mart_menu(**in_mart(menu_watch_oob=0, menu_exit_method=1, quantity=0))[0] == "unknown"
    assert mart_menu(**in_mart(menu_watch_oob=0, menu_exit_method=1, quantity=100))[0] == "unknown"


def test_mart_confirm_signature_and_sentinel():
    mart_menu = signature()
    confirm = {"text_box": 0x14, "menu_y": 8, "menu_x": 15, "menu_max": 1, "menu_watch_oob": 0}
    assert mart_menu(**in_mart(**confirm, menu_index=0)) == ("mart-confirm", 0, 0)
    assert mart_menu(**in_mart(**confirm, menu_index=1)) == ("mart-confirm", 0, 1)
    # An answered yes/no (wMenuExitMethod set) is no longer a live confirm.
    assert mart_menu(**in_mart(**confirm, menu_index=0, menu_exit_method=1)) == ("unknown", 0, -1)
    assert mart_menu(**in_mart(**confirm, menu_index=0, menu_exit_method=2)) == ("unknown", 0, -1)
    assert mart_menu(**in_mart(**confirm, menu_index=2))[0] == "unknown"


@pytest.mark.parametrize("over", [
    {"menu_watch_oob": 2},                       # list cancelled (ExitListMenu), geometry retained
    {"menu_watch_oob": 0, "menu_exit_method": 0, "quantity": 1},  # quantity geometry, no chosen item
    {"menu_watch_oob": 0, "menu_exit_method": 2, "quantity": 1},  # returned from a declined confirm
    {"text_box": 0x0F},                          # MONEY_BOX only
    {"list_scroll_offset": 3},                   # scroll beyond the 4-entry list
    {"menu_index": 1.5},
    {"menu_index": "0"},
    {"menu_max": 1},
])
def test_ambiguous_displays_are_unknown(over):
    assert signature()(**in_mart(**over)) == ("unknown", 0, -1)
