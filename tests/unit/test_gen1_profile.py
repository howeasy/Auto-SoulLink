"""F-1: every Gen 1 address comes from pret, and the committed profile is what pret says.

The profile is generated from the pinned rgblink .sym files (data/pret/*.sym). Anyone who
edits profile.json by hand, or bumps a .sym without regenerating, fails here.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools import gen_gen1_profile as gen  # noqa: E402

PROFILE = REPO / "data" / "games" / "gen1_rby" / "profile.json"


def _committed() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def test_committed_profile_matches_a_fresh_generation():
    try:
        fresh = gen.render(gen.build())
    except SystemExit as e:
        pytest.skip(f"pret source checkout not present: {e}")
    assert PROFILE.read_text(encoding="utf-8") == fresh


def test_sym_files_are_the_pinned_ones():
    prof = _committed()
    for sym_name, src in prof["source"].items():
        path = REPO / "data" / "pret" / sym_name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == src["sha256"], sym_name
        assert src["commit"] == gen.PRET_COMMITS[src["repo"]]


def test_every_requested_symbol_is_present_in_every_title():
    prof = _committed()
    for title, t in prof["titles"].items():
        assert set(t["ram"]) == set(gen.RAM_SYMBOLS), title
        assert set(gen.ROM_SYMBOLS) <= set(t["rom"]) <= set(gen.ROM_SYMBOLS) | set(gen.OPTIONAL_ROM_SYMBOLS), title


def test_geometry_pret_implies():
    """Struct sizes and capacities fall out of symbol arithmetic; pret fixes them."""
    for title, t in _committed()["titles"].items():
        d = t["derived"]
        assert d == {
            "party_struct_size": 44, "box_struct_size": 33, "battle_struct_size": 44,
            "party_capacity": 6, "box_capacity": 20, "name_length": 11,
            "sram_box_stride": 1122, "sram_boxes_per_bank": 6, "sram_box_banks": [2, 3],
            # Symbol-adjacent constants no address carries (F-1 follow-up C): same for every
            # title, proven against pret's own source text (and pokeyellow's, for yellow).
            "ball_items": [1, 2, 3, 4], "opp_id_offset": 200, "bag_capacity": 20,
            "base_stats_stride": 28, "dex_count": 152, "species_count": 190,
            "rival_trainer_ids": [225, 242, 243],
        }, title


def test_red_and_blue_share_ram_and_yellow_is_shifted_where_pret_says():
    prof = _committed()["titles"]
    assert prof["red"]["ram"] == prof["blue"]["ram"]
    red, yellow = prof["red"]["ram"], prof["yellow"]["ram"]
    # Yellow inserts bytes early in WRAM, so most wram symbols sit one lower; HRAM and SRAM
    # symbols do not move. This pins the shape of the shift without hand-typing addresses.
    assert yellow["wPartyCount"] == red["wPartyCount"] - 1
    assert yellow["wPlayerID"] == red["wPlayerID"] - 1
    assert yellow["hLoadedROMBank"] == red["hLoadedROMBank"]
    assert yellow["sBox1"] == red["sBox1"]
    assert prof["red"]["rom"]["MainInBattleLoop"]["bank"] == 0x0F
    assert prof["yellow"]["rom"]["MainInBattleLoop"]["bank"] == 0x0F


def test_rom_sha1s_are_the_clean_dumps():
    prof = _committed()["titles"]
    assert prof["red"]["rom_sha1"] == "ea9bcae617fdf159b045185467ae58b2e4a48b9a"
    assert prof["blue"]["rom_sha1"] == "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2"
    assert prof["yellow"]["rom_sha1"] == "cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1"


@pytest.mark.parametrize("foundation,path", [
    ("pret", "gen1_rby/profile.json"),
    ("purergb", "gen1_purergb/profile.json"),
    ("purergb_overlay", "gen1_purergb/profile_overlay.json"),
])
def test_trade_slot_symbol_is_generated_from_pinned_symbols(foundation, path):
    profiles = json.loads((REPO / "data/games" / path).read_text())["titles"]
    assert "wTradingWhichPlayerMon" in gen.RAM_SYMBOLS
    for title, profile in profiles.items():
        syms = gen.parse_sym(gen.F.sym_path(foundation, title))
        assert profile["ram"]["wTradingWhichPlayerMon"] == syms["wTradingWhichPlayerMon"][1]
