"""
Gen 2 (Crystal/Gold/Silver) damage-calc stat decoding.

Gen2GSCAdapter.calc_stats(detail) decodes detail["blob_hex"] (the 70-byte party
transfer blob docs/protocol.md S4.1 defines, gen2_codec.decode_party_blob shape)
into calc-ready DVs/stat-exp/computed-stats. The mon's own stored stats (part of
the party struct) are the in-game ground truth: calc_stats() returns them as
"stats" (never a recompute), so the calc bridge's "computed stat differs" warning
can fire; on the real blobs the codec's recompute also matches them. This suite decodes real captured blobs (tests/fixtures/gen2
receipts) rather than hand-built bytes, so the fixture and the assertion can't
share the same authoring mistake.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.adapters import gen2_codec  # noqa: E402
from server.adapters.gen2_gsc import Gen2GSCAdapter  # noqa: E402

CRYSTAL = Gen2GSCAdapter(title="crystal")

# Real 70-byte party transfer blobs captured from a live duo run, pinned verbatim from
# tests/fixtures/gen2/receipts/duo_trade_decline_new_cc_a_result.txt's TRADE_BASELINE
# "party" entries (line 47). species_marker there confirms neither mon is an egg.
_BLOB_PIKACHU = ("9e000a2b0000b54100008700000000000000000000f794231e00004600850105"
                 "000000150015000d000c000a0009000a8287918892505050505050938e938e83888b84505050")
_BLOB_HOOTHOOT = ("100021000000b541000039000000000000000000000ce12300000047004302030000000f000f"
                  "0007000800090007000782879188925050505050508f88838684985050505050")


def test_pikachu_blob_matches_in_game_stats():
    detail = {"blob_hex": _BLOB_PIKACHU, "species_id": 158, "level": 5}
    result = CRYSTAL.calc_stats(detail)
    assert result == {
        "dvs": {"atk": 15, "def": 7, "spe": 9, "spc": 4},
        "stat_exp": {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0},
        "stats": {"hp": 21, "atk": 13, "def": 12, "spa": 9, "spd": 10, "spe": 10},
    }


def test_hoothoot_blob_matches_in_game_stats():
    detail = {"blob_hex": _BLOB_HOOTHOOT, "species_id": 16, "level": 3}
    result = CRYSTAL.calc_stats(detail)
    assert result == {
        "dvs": {"atk": 0, "def": 12, "spe": 14, "spc": 1},
        "stat_exp": {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0},
        "stats": {"hp": 15, "atk": 7, "def": 8, "spa": 7, "spd": 7, "spe": 9},
    }


def test_spa_and_spd_use_their_own_base_stats():
    """spa/spd share one DV and one stat-exp value in Gen 2 (the "Special" pair) but must
    still be computed off their own separate base stats -- assert against the species'
    real base_stats rather than hard-coding numbers, so this fails if a future edit
    accidentally shares one base stat between them."""
    detail = {"blob_hex": _BLOB_HOOTHOOT, "species_id": 16, "level": 3}
    base = CRYSTAL._species[16]["base_stats"]
    result = CRYSTAL.calc_stats(detail)
    dvs = gen2_codec.decode_party_mon(bytes.fromhex(_BLOB_HOOTHOOT)[:48], CRYSTAL._layout,
                                      species_marker=16)["dvs"]
    expected_spa = gen2_codec.calc_stat(base["special_attack"], dvs["special"], 0, 3)
    expected_spd = gen2_codec.calc_stat(base["special_defense"], dvs["special"], 0, 3)
    assert result["stats"]["spa"] == expected_spa
    assert result["stats"]["spd"] == expected_spd


def test_stats_are_the_stored_stats_not_a_recompute():
    """Re-encode the Pikachu blob with nonzero stat exp (via gen2_codec, never hand-built
    bytes) but leave its stored stats alone: stat_exp decodes, and "stats" stay the stored
    in-game numbers, so a struct whose stats disagree with its DVs/stat exp reaches the calc
    bridge as a disagreement instead of being papered over."""
    mon = CRYSTAL.decode_party_blob(_BLOB_PIKACHU, species_marker=158)
    mon["stat_exp"] = {"hp": 5000, "attack": 10000, "defense": 2000, "speed": 300, "special": 65535}
    new_party = gen2_codec.encode_party_mon(mon, CRYSTAL._layout)
    blob_hex = (new_party + bytes.fromhex(mon["ot_raw_hex"]) + bytes.fromhex(mon["nickname_raw_hex"])).hex()
    result = CRYSTAL.calc_stats({"blob_hex": blob_hex, "species_id": 158, "level": 5})
    assert result["stat_exp"] == {"hp": 5000, "atk": 10000, "def": 2000, "spe": 300, "spc": 65535}
    assert result["stats"] == {"hp": 21, "atk": 13, "def": 12, "spa": 9, "spd": 10, "spe": 10}
    base = CRYSTAL._species[158]["base_stats"]
    recompute = gen2_codec.calc_stats(base, mon["dvs"], mon["stat_exp"], 5)
    assert recompute["attack"] != result["stats"]["atk"]  # the fixture really does disagree


def test_missing_blob_hex_returns_none():
    assert CRYSTAL.calc_stats({"species_id": 158, "level": 5}) is None
    assert CRYSTAL.calc_stats({}) is None


def test_garbage_blob_hex_returns_none():
    assert CRYSTAL.calc_stats({"blob_hex": "not hex", "species_id": 158}) is None
    assert CRYSTAL.calc_stats({"blob_hex": "ab", "species_id": 158}) is None  # too short
    assert CRYSTAL.calc_stats({"blob_hex": "zz" * 70, "species_id": 158}) is None  # invalid hex
    assert CRYSTAL.calc_stats({"blob_hex": _BLOB_PIKACHU, "species_id": 999}) is None  # marker mismatch


def test_calc_stats_never_raises_on_malformed_detail():
    """Untrusted client input; the contract (base.py) requires this never to raise."""
    for bad in (None, [], {"blob_hex": 12345}, {"blob_hex": _BLOB_PIKACHU, "species_id": "nope"}):
        assert CRYSTAL.calc_stats(bad) is None


def test_calc_profile_all_titles():
    for title in ("crystal", "gold", "silver"):
        profile = Gen2GSCAdapter(title=title).calc_profile()
        sets = {"sets": {"file": "Crystal.js", "var": "CUSTOMSETDEX_C"}} if title == "crystal" else {}
        assert profile == {"gen": 2, "dex": "vanilla", **sets}
