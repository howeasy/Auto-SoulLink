"""Regression pin for tools/rr_ingame_trades.py, with no ROM dependency at
collection time (skips if the local ROM build isn't present)."""
import hashlib

import pytest

from tools import rr_ingame_trades as rit


def _rom(path, sha1):
    if not path.exists():
        pytest.skip(f"ROM absent: {path}")
    data = path.read_bytes()
    rit_sha1 = hashlib.sha1(data).hexdigest()
    if rit_sha1 != sha1:
        pytest.skip(f"ROM sha1 mismatch (got {rit_sha1}): {path}")
    return data


def test_parse_trades_rr_pin():
    rom = _rom(rit.DEFAULT_RR_ROM, rit.RR_ROM_SHA1)
    trades = rit.parse_trades(rom)
    assert len(trades) == 9
    assert [t["label"] for t in trades] == list(rit.TRADE_LABELS)
    mimic = trades[0]
    assert mimic["nickname"] == "Mimien"
    assert mimic["species"] == 1216  # RR-expanded id for Mr Mime-Galar
    assert mimic["requested_species"] == 63  # Abra -- unchanged FR dex number
    assert mimic["ot_name"] == "Reyley"
    assert mimic["ivs"] == [20, 15, 17, 24, 23, 22]  # carried over from vanilla FR
    assert mimic["ot_id"] == 1985
    # Every entry must decode to a plausible struct (never garbage/all-zero).
    for t in trades:
        assert 1 <= t["species"] <= 2000
        assert 1 <= t["requested_species"] <= 2000
        assert all(0 <= iv <= 31 for iv in t["ivs"])


def test_parse_map_object_events_vanilla_cross_check():
    # Cross-check the map-header walker on a map CFRU did not touch (per the
    # research doc: rr_obj_events_anchor.md already shows the overworld engine
    # is vanilla-identical) before trusting it on the RR ROM.
    rom = _rom(rit.DEFAULT_VANILLA_ROM, "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc")
    objs, warps = rit.parse_map_object_events(rom, 7, 2)  # CeruleanCity_House3
    assert [(o["x"], o["y"], o["elevation"]) for o in objs] == [(2, 2, 3), (7, 5, 3)]
    assert warps[0]["map_group"] == 3 and warps[0]["map_num"] == 3


def test_decode_text_charmap():
    assert rit.decode_text(bytes([0xC7, 0xD3, 0xC8, 0xC2, 0xD9, 0xD8, 0xFF])) == "MYNHed"
    assert rit.decode_text(bytes([0xBD, 0xC2, 0xB4, 0xBE, 0xFF])) == "CH'D"
