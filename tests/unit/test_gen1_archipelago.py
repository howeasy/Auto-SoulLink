"""Archipelago Red/Blue must resolve to an adapter, and its label must not become a key.

`rom_type_for_variant` used to return the display string `"Red (AP)"`, which is not a key in
`_ROM_TYPE_TO_GAME_ID`, so `game_id_for_rom_type` returned None and the hello never bound an
adapter. rom_type is a key; the label is the server's own business.

P8-2b: the Lua half of this file is gone with the feature. The AP seed sniffer, the AP
profile's relocated WRAM addresses and the AP variants themselves lived in
`lua/games/gen1_rby.lua`; the rewritten Gen 1 client ships three titles only
(data/games/gen1_rby/profile.json) and P8-2a already retired the AP gate and
tools/gen1_ap_rom.py. What survives is the server-side routing, which is retained Python and
still has to answer for a `red_ap` hello arriving from anywhere.
"""
import pytest

from server.adapters import game_id_for_rom_type, get_adapter, variant_label


@pytest.mark.parametrize("rom_type", ["red_ap", "blue_ap"])
def test_ap_rom_types_resolve_to_the_gen1_adapter(rom_type):
    assert game_id_for_rom_type(rom_type) == "gen1_rby", (
        f"{rom_type!r} does not map to a game_id — the hello cannot bind an adapter"
    )


@pytest.mark.parametrize("rom_type,expected", [("red_ap", "Red (AP)"), ("blue_ap", "Blue (AP)")])
def test_ap_rom_types_have_display_labels(rom_type, expected):
    assert variant_label(rom_type) == expected


def test_display_label_is_not_used_as_a_rom_type():
    """"Red (AP)" is a label. If it ever comes back as a rom_type it resolves to nothing."""
    assert game_id_for_rom_type("Red (AP)") is None


@pytest.mark.parametrize("rom_type,expected_variant", [
    ("red_ap", "red"), ("blue_ap", "blue"),
])
def test_ap_inherits_its_base_games_encounter_tables(rom_type, expected_variant):
    """AP randomises placement, not the wild tables, so it uses the base game's."""
    adapter = get_adapter("gen1_rby", rom_type=rom_type)
    assert adapter._enc_variant == expected_variant
