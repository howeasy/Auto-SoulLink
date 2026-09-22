"""Strict RGBDS symbol text and conventional Game Boy ROM offsets."""

import pytest


def test_parse_symbol_addresses_preserves_ram_banks_and_local_labels():
    from tools.rgbds_symbols import parse_symbols, rom_offset

    symbols = parse_symbols("; rgblink\r\n00:0100 Entry\r\n02:4000 Table.local\n03:d123 wBanked\n")
    assert symbols["Entry"].address == 0x100
    assert symbols["wBanked"].bank == 3
    assert tuple(symbols["Table.local"]) == (2, 0x4000)
    assert rom_offset(*symbols["Table.local"]) == 0x8000


def test_exported_numeric_constants_are_not_misclassified_as_addresses():
    from tools.rgbds_symbols import parse_symbols

    assert set(parse_symbols("00:0100 Entry\n00 SCENE_AZALEATOWN_NOOP\n36 PICS_FIX\n")) == {"Entry"}


@pytest.mark.parametrize("text", ["", "garbage", "00:10000 Outside", "00:0000 A\n01:4000 A"])
def test_symbol_text_refuses_missing_malformed_or_duplicate_rows(text):
    from tools.rgbds_symbols import parse_symbols

    with pytest.raises(ValueError):
        parse_symbols(text)


@pytest.mark.parametrize("bank,address", [(0, 0x4000), (1, 0x2000), (1, 0x8000),
                                         (3, 0xD000), (-1, 0x4000), (True, 0x4000)])
def test_rom_offset_refuses_non_rom_or_ambiguous_coordinates(bank, address):
    from tools.rgbds_symbols import rom_offset

    with pytest.raises(ValueError):
        rom_offset(bank, address)
