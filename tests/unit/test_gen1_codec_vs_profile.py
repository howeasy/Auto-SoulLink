"""The Python decoder's hand-pinned bases must equal the pret-generated profile.

gen1_codec cites .sym line numbers; profile.json is parsed from the same .sym files by a
different author and a different tool. Two derivations, one truth.
"""
from __future__ import annotations

import json
import pathlib

from server.adapters import gen1_codec as codec

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILE = json.loads((REPO / "data" / "games" / "gen1_rby" / "profile.json").read_text(encoding="utf-8"))["titles"]


def _sram_offset(addr: int, bank: int) -> int:
    return bank * 0x2000 + (addr - 0xA000)


def test_wram_bases_match_the_profile():
    for title, bases in codec.WRAM_BASES.items():
        ram = PROFILE[title]["ram"]
        assert bases == {"party": ram["wPartyCount"], "box": ram["wBoxCount"]}, title


def test_sram_layout_matches_the_profile():
    for title in PROFILE:
        ram, bank = PROFILE[title]["ram"], PROFILE[title]["sram_bank"]
        for sym in ("sPlayerName", "sMainData", "sSpriteData", "sPartyData", "sCurBoxData",
                    "sTileAnimations", "sMainDataCheckSum"):
            assert codec.SRAM_LAYOUT[sym] == _sram_offset(ram[sym], bank[sym]), (title, sym)
        assert codec.SRAM_LAYOUT["box_banks"] == (
            _sram_offset(ram["sBox1"], bank["sBox1"]), _sram_offset(ram["sBox7"], bank["sBox7"]))
        assert codec.SRAM_LAYOUT["all_boxes_checksums"] == (
            _sram_offset(ram["sBank2AllBoxesChecksum"], bank["sBank2AllBoxesChecksum"]),
            _sram_offset(ram["sBank3AllBoxesChecksum"], bank["sBank3AllBoxesChecksum"]))
        assert codec.SRAM_LAYOUT["individual_checksums"] == (
            _sram_offset(ram["sBank2IndividualBoxChecksums"], bank["sBank2IndividualBoxChecksums"]),
            _sram_offset(ram["sBank3IndividualBoxChecksums"], bank["sBank3IndividualBoxChecksums"]))


def test_struct_geometry_matches_the_profile():
    d = PROFILE["red"]["derived"]
    assert codec.PARTY_LAYOUT["ot_names"] - codec.PARTY_LAYOUT["mons"] == d["party_struct_size"] * d["party_capacity"]
    assert codec.BOX_LAYOUT["ot_names"] - codec.BOX_LAYOUT["mons"] == d["box_struct_size"] * d["box_capacity"]
    assert d["sram_box_stride"] == codec.BOX_SIZE
    assert d["name_length"] == codec.NAME_SIZE
