"""The Mart signature's per-title inventory and scroll window.

`gen1_rb_mart_signature.lua` is how the scripted host reads a live Mart menu out of the tilemap
point. Its item list was Red/Blue's four items with the scroll offset bounded to 0..2, and Yellow
stocks FIVE (pokeyellow data/items/marts.asm:5), so without the per-title list a Yellow purchase
step would either read the wrong row or refuse a legal offset.

Pure Lua through lupa: no emulator, no ROM. What is pinned is the row the window resolves to —
which is what the parcel driver's purchase step keys on (index 1 is the ball in both titles).
"""
from __future__ import annotations

import os

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_SIG = os.path.join(_REPO, "lua", "tests", "gen1_rb_mart_signature.lua")

RB = (0x04, 0x0B, 0x0F, 0x0C)            # POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL
YELLOW = (0x04, 0x14, 0x0B, 0x0F, 0x0C)  # POKE_BALL, REPEL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL


@pytest.fixture
def mart():
    """The module and a point builder bound to ONE Lua runtime (mixing them is an error)."""
    runtime = LuaRuntime(unpack_returned_tuples=True)
    sig = runtime.execute(f'return dofile("{_SIG.replace(chr(92), "/")}")')

    def point(**overrides):
        fields = {"map": 0x2A, "mart_script": 2, "font_loaded": True, "list_menu_id": 2,
                  "menu_index": 0, "menu_y": 4, "menu_x": 5, "menu_max": 2,
                  "menu_watch_oob": 1, "list_scroll_offset": 0, "menu_exit_method": 0,
                  "quantity": 0, "text_box": 0}
        fields.update(overrides)
        return runtime.table(**fields)

    return sig, point


def test_rb_inventory_is_the_four_item_list_with_the_ball_first(mart):
    sig, _ = mart
    assert tuple(sig.inventory("red")[i] for i in range(1, 5)) == RB
    assert tuple(sig.inventory("blue")[i] for i in range(1, 5)) == RB
    assert sig.inventory("red")[1] == 0x04


def test_yellow_inventory_is_the_five_item_list_with_the_ball_first(mart):
    sig, _ = mart
    assert tuple(sig.inventory("yellow")[i] for i in range(1, 6)) == YELLOW
    assert sig.inventory("yellow")[1] == 0x04


@pytest.mark.parametrize(("title", "offset", "item"), [
    ("red", 0, 0x04),
    ("red", 2, 0x0F),
    ("yellow", 0, 0x04),
    ("yellow", 3, 0x0F),      # a legal window only because the list has five entries
])
def test_the_scroll_window_reads_the_title_s_own_list(mart, title, offset, item):
    sig, point = mart
    kind, got, _confirm = sig.mart_menu(point(list_scroll_offset=offset), title)
    assert kind == "mart-item", (title, offset, kind)
    assert got == item, (title, offset, got)


def test_the_fifth_yellow_row_is_reachable_through_the_window(mart):
    """Yellow's list is one longer than Red/Blue's: row 5 comes from menu_index 1 + offset 3,
    which is exactly the window the R/B bound would have refused."""
    sig, point = mart
    kind, got, _confirm = sig.mart_menu(point(menu_index=1, list_scroll_offset=3), "yellow")
    assert (kind, got) == ("mart-item", 0x0C)


@pytest.mark.parametrize(("title", "offset"), [("red", 3), ("yellow", 4), ("yellow", 5),
                                               ("yellow", -1)])
def test_offsets_outside_the_list_are_ambiguous_not_a_row(mart, title, offset):
    """The driver idles on "unknown"; reading a row past the list would buy the wrong item."""
    sig, point = mart
    kind, item, _confirm = sig.mart_menu(point(list_scroll_offset=offset), title)
    assert kind == "unknown", (title, offset, kind)
    assert item == 0


def test_the_choice_and_quantity_signatures_still_win_over_the_item_list(mart):
    """The pre-existing R/B signatures are untouched by the parametrisation."""
    sig, point = mart
    assert sig.mart_menu(point(menu_y=1, menu_x=1, text_box=0x0E), "red")[0] == "mart-choice"
    assert sig.mart_menu(point(menu_watch_oob=0, menu_exit_method=1, quantity=5),
                         "yellow")[0] == "mart-quantity"
    assert sig.mart_menu(point(map=0x00), "yellow")[0] == "none"
