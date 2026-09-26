"""Map keys preserve group identity; unsupported source cannot silently vanish."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.gen_gen2_map_names import landmarks, map_constants, map_rows


def test_map_numbers_restart_per_group_and_keep_dimensions():
    groups = map_constants("const_def\nnewgroup A\nmap_const FIRST_ROOM, 5, 4\nendgroup\nnewgroup B\nmap_const SECOND_ROOM, 7, 8\nendgroup")
    assert len(groups) == 2 and [len(group) for group in groups] == [1, 1]
    assert groups[0][0] == {"constant": "FIRST_ROOM", "width_blocks": 5, "height_blocks": 4}


@pytest.mark.parametrize("text", ["map_const ROOM, 5, 4", "newgroup A\nmap_const ROOM, 0, 4\nendgroup",
                                  "newgroup A\nmap_const ROOM, 5, 4", "newgroup A\nendgroup",
                                  "IF _GOLD\nENDC"])
def test_bad_group_dimension_or_unhandled_source_refuses(text):
    with pytest.raises(ValueError):
        map_constants(text)


def test_header_pointer_coverage_and_field_count():
    source = "MapGroupPointers::\ndw MapGroup_A\nMapGroup_A:\nmap Room, TILESET_HOUSE, INDOOR, LANDMARK_TOWN, MUSIC_TOWN, FALSE, PALETTE_DAY, FISHGROUP_NONE"
    pointers, groups = map_rows(source)
    assert pointers == ["MapGroup_A"] and groups["MapGroup_A"][0][3] == "LANDMARK_TOWN"
    with pytest.raises(ValueError, match="coverage"):
        map_rows(source.replace("dw MapGroup_A", "dw MapGroup_B"))
    with pytest.raises(ValueError, match="eight"):
        map_rows(source.replace(", FISHGROUP_NONE", ""))


def test_landmark_intermediate_assertion_and_rom_pointer_are_verified():
    constants = "DEF NUM_LANDMARKS EQU 1\nDEF KANTO_LANDMARK EQU 1"
    table = 'Landmarks:\nlandmark -8, -16, Place\nassert_table_length KANTO_LANDMARK\nPlace: db "A@"'
    rom = bytearray(0x4000)
    rom[0x100:0x104] = bytes([0, 0, 0, 2])
    rom[0x200:0x202] = bytes([0x80, 0x50])

    class Symbol(tuple):
        bank = property(lambda self: self[0])
        address = property(lambda self: self[1])

    ctx = SimpleNamespace(rom=bytes(rom), symbol=lambda name: Symbol((0, 0x100 if name == "Landmarks" else 0x200)),
                          read_source=lambda path: constants if path.startswith("constants/") else table)
    assert landmarks(ctx, {"encoding": {"A": 0x80, "@": 0x50}})[0]["name"] == "A"
    constants = constants.replace("KANTO_LANDMARK EQU 1", "KANTO_LANDMARK EQU 2")
    with pytest.raises(ValueError, match="table count"):
        landmarks(ctx, {"encoding": {"A": 0x80, "@": 0x50}})


def test_generated_map_counts_and_group_identity_stay_title_specific():
    root = Path(__file__).resolve().parents[2] / "data/games"
    for title, count in (("crystal", 388), ("gold", 368), ("silver", 368)):
        pack = json.loads((root / f"gen2_{title}/map_names.json").read_bytes())
        assert len(pack["maps"]) == count
        assert pack["maps"]["1:1"]["constant"] == "OLIVINE_POKECENTER_1F"
        assert pack["maps"]["1:1"]["landmark_name"] == "OLIVINE CITY"
        assert pack["maps"]["15:4"]["source_label"] == "FastShipCabins_NNW_NNE_NE"
        assert all(entry["group"] * 256 + entry["number"] == entry["encoded_id"] for entry in pack["maps"].values())
