"""pureRGB moves/items/charmap packs (data/games/gen1_purergb/{moves,items,charmap}.json).

Facts pinned here come straight from docs/purergb/PLAN.md S11.2 A6/A10: the 7 move
renames, the ball item-id set, APEX CHIP's item id, and the `$33-$4D` text-shortcut
range. `tools/gen_{moves_data,gen1_items,gen1_charmap}.py` already assert every one
of these against the built ROM in all three titles; these tests pin the checked-in
output so a stale regenerate is caught without needing the ROMs on hand.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK = os.path.join(REPO, "data", "games", "gen1_purergb")


def _load(name):
    path = os.path.join(PACK, name)
    if not os.path.exists(path):
        pytest.skip(f"{path} missing -- regenerate the pureRGB data pack")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# moves.json
# ---------------------------------------------------------------------------

_RENAMES = {
    0x0D: "Roost", 0x15: "Filthy Slam", 0x24: "Heat Rush", 0x44: "Drain Punch",
    0x84: "Siphon Snag", 0x86: "Firewall", 0x9A: "Dust Claw",
}


def test_move_renames():
    moves = {m["id"]: m for m in _load("moves.json")["moves"]}
    for move_id, expected_name in _RENAMES.items():
        assert moves[move_id]["name"] == expected_name, move_id


def test_move_count():
    assert len(_load("moves.json")["moves"]) == 165


# ---------------------------------------------------------------------------
# items.json
# ---------------------------------------------------------------------------

def test_ball_item_set():
    items = _load("items.json")
    assert items["ball_items"] == [1, 2, 3, 4, 5, 8]
    for ball_id in items["ball_items"]:
        assert items["items"][str(ball_id)]["ball"] is True


def test_apex_chip_id():
    items = _load("items.json")
    assert items["items"]["50"]["name"] == "Apex Chip"  # 0x32 == 50


def test_bag_and_pc_capacity():
    items = _load("items.json")
    assert items["bag_capacity"] == 30
    assert items["pc_item_capacity"] == 60


# ---------------------------------------------------------------------------
# charmap.json
# ---------------------------------------------------------------------------

def test_shortcut_an_and_ellipsis():
    charmap = _load("charmap.json")
    assert charmap["shortcuts"]["52"] == "an"       # $34
    assert charmap["glyphs"]["86"] == "<...>"        # $56, bracket-token convention (reads.lua EXTRA)


def test_curly_quotes_replace_brackets():
    charmap = _load("charmap.json")
    assert charmap["glyphs"]["158"] == "“"      # $9E
    assert charmap["glyphs"]["159"] == "”"      # $9F


def test_terminator_and_lengths():
    charmap = _load("charmap.json")
    assert charmap["terminator"] == 80
    assert charmap["name_length"] == 11
    assert charmap["player_name_length"] == 8
    assert charmap["box_name_length"] == 6
