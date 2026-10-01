"""
Falsifiers for calc_stats (server/adapters/base.py's CONTRACT docstring): does the calc
get each party mon's real IV/EV/DV/stat-exp inputs, decoded from the client's blob_hex,
instead of the calc's built-in defaults (31 IV / 0 EV, or 15 DV / max stat exp)?

Party bytes are hand-built here (not read from a live ROM) via gen1_codec.encode_party_mon
/ gen3_codec.encode_party_mon. Each stat is computed from the documented pret formula using
Charmander's base stats (HP 39 / Atk 52 / Def 43 / SpA 60 / SpD 50 / Spe 65; Gen 1 merges
SpA/SpD into one Special stat of 50) -- picked because every stat differs, so a swapped key
(atk/def, spa/spd, the DV nibble order) fails loudly instead of hiding behind two equal
base stats.
"""

import math
import os

from server.adapters import gen1_codec, gen3_codec
from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import _build_mon_entry

# ---------------------------------------------------------------------------
# Gen 1 -- DVs (0-15) / stat exp (raw 0-65535) / stored stats.
# home/move_mon.asm's CalcStats: stat = floor(((base+DV)*2 + floor(min(255,
# ceil(sqrt(statexp)))/4)) * level/100) + 5, HP adds level+10 instead of 5.
# ---------------------------------------------------------------------------

_G1_BASE = {"hp": 39, "atk": 52, "def": 43, "spd": 65, "spc": 50}  # Charmander, pret gen1


def _ceil_sqrt(x: int) -> int:
    r = math.isqrt(x)
    return r if r * r == x else r + 1


def _g1_stat(base: int, dv: int, exp: int, level: int, *, is_hp: bool = False) -> int:
    bonus = min(255, _ceil_sqrt(exp)) // 4
    core = ((base + dv) * 2 + bonus) * level // 100
    return core + level + 10 if is_hp else core + 5


def _hp_dv(dvs: dict) -> int:
    return ((dvs["atk"] & 1) << 3) | ((dvs["def"] & 1) << 2) | ((dvs["spd"] & 1) << 1) | (dvs["spc"] & 1)


def _g1_blob(level: int, dvs: dict, stat_exp: dict) -> tuple[str, dict]:
    hp_dv = _hp_dv(dvs)
    stats = {
        "max_hp": _g1_stat(_G1_BASE["hp"], hp_dv, stat_exp["hp"], level, is_hp=True),
        "atk": _g1_stat(_G1_BASE["atk"], dvs["atk"], stat_exp["atk"], level),
        "def": _g1_stat(_G1_BASE["def"], dvs["def"], stat_exp["def"], level),
        "spd": _g1_stat(_G1_BASE["spd"], dvs["spd"], stat_exp["spd"], level),
        "spc": _g1_stat(_G1_BASE["spc"], dvs["spc"], stat_exp["spc"], level),
    }
    mon = {
        "species": 0x99, "hp": stats["max_hp"], "box_level": level, "status": 0,
        "types": [0x16, 0x03], "catch_rate": 45, "moves": [33, 22, 45, 0], "ot_id": 0xBEEF,
        "exp": 125000, "stat_exp": dict(stat_exp),
        "dvs": {"raw": (dvs["atk"] << 12) | (dvs["def"] << 8) | (dvs["spd"] << 4) | dvs["spc"],
                "atk": dvs["atk"], "def": dvs["def"], "spd": dvs["spd"], "spc": dvs["spc"], "hp": hp_dv},
        "pp": [15, 15, 15, 15], "pp_ups": [0, 0, 0, 0], "level": level,
        "max_hp": stats["max_hp"], "atk": stats["atk"], "def": stats["def"],
        "spd": stats["spd"], "spc": stats["spc"], "box": False,
    }
    blob44 = gen1_codec.encode_party_mon(mon)
    blob66 = blob44 + gen1_codec.encode_name("ASH") + gen1_codec.encode_name("CHARMANDER")
    return blob66.hex(), stats


GEN1 = Gen1Adapter(rom_type="red")


def test_gen1_calc_stats_decodes_dvs_and_stat_exp_and_matches_pret_formula():
    level = 57
    dvs = {"atk": 9, "def": 5, "spd": 13, "spc": 3}
    stat_exp = {"hp": 10000, "atk": 25000, "def": 5000, "spd": 65535, "spc": 1500}
    blob_hex, stats = _g1_blob(level, dvs, stat_exp)

    cs = GEN1.calc_stats({"key": "ABCD:BEEF:99", "level": level, "blob_hex": blob_hex})
    assert cs == {
        "dvs": {"atk": 9, "def": 5, "spe": 13, "spc": 3},
        "stat_exp": {"hp": 10000, "atk": 25000, "def": 5000, "spe": 65535, "spc": 1500},
        "stats": {"hp": stats["max_hp"], "atk": stats["atk"], "def": stats["def"],
                  "spa": stats["spc"], "spd": stats["spc"], "spe": stats["spd"]},
    }

    # Recompute independently from the decoded DVs/stat exp against Charmander's base stats
    # -- confirms the codec byte offsets AND this adapter's spd->spe / spc->spa,spd remap
    # didn't silently swap a stat (all four base stats differ).
    assert _g1_stat(_G1_BASE["hp"], _hp_dv(cs["dvs"] | {"spd": cs["dvs"]["spe"]}),
                     cs["stat_exp"]["hp"], level, is_hp=True) == cs["stats"]["hp"]
    assert _g1_stat(_G1_BASE["atk"], cs["dvs"]["atk"], cs["stat_exp"]["atk"], level) == cs["stats"]["atk"]
    assert _g1_stat(_G1_BASE["def"], cs["dvs"]["def"], cs["stat_exp"]["def"], level) == cs["stats"]["def"]
    assert _g1_stat(_G1_BASE["spd"], cs["dvs"]["spe"], cs["stat_exp"]["spe"], level) == cs["stats"]["spe"]
    assert _g1_stat(_G1_BASE["spc"], cs["dvs"]["spc"], cs["stat_exp"]["spc"], level) == cs["stats"]["spa"]
    assert cs["stats"]["spa"] == cs["stats"]["spd"]


def test_gen1_calc_stats_none_on_missing_or_bad_blob():
    assert GEN1.calc_stats({"key": "x", "level": 5}) is None
    assert GEN1.calc_stats({"key": "x", "level": 5, "blob_hex": ""}) is None
    assert GEN1.calc_stats({"key": "x", "level": 5, "blob_hex": "zz"}) is None
    assert GEN1.calc_stats({"key": "x", "level": 5, "blob_hex": "00" * 10}) is None  # too short


# ---------------------------------------------------------------------------
# Gen 3 -- IVs/EVs (0-31/0-255) / stored stats.
# src/pokemon.c's CalculateMonStats: stat = floor((2*base+IV+floor(EV/4))*level/100)+5,
# times the nature multiplier (1.0 here: personality=0 -> personality%25==0 -> Hardy,
# a neutral nature, so the multiplier drops out); HP adds level+10 instead of *nature+5.
# ---------------------------------------------------------------------------

_G3_BASE = {"hp": 39, "atk": 52, "def": 43, "spa": 60, "spd": 50, "spe": 65}  # Charmander


def _g3_stat(base: int, iv: int, ev: int, level: int, *, is_hp: bool = False) -> int:
    core = (2 * base + iv + ev // 4) * level // 100
    return core + level + 10 if is_hp else core + 5


def _g3_mon(level: int, ivs: dict, evs: dict, ot_id: int) -> tuple[dict, dict]:
    stats = {stat: _g3_stat(_G3_BASE[stat], ivs[stat], evs[stat], level, is_hp=(stat == "hp"))
             for stat in _G3_BASE}
    return {
        "personality": 0, "ot_id": ot_id,  # personality%25==0 -> Hardy (neutral nature)
        "nickname": "CHARMANDER", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0, "block_box_rs": 0, "flags_unused": 0,
        "ot_name": "ASH", "markings": 0, "unknown": 0,
        "species": 4, "held_item": 0, "experience": 100000,
        "pp_bonuses": 0, "friendship": 70, "growth_filler": 0,
        "moves": [52, 45, 98, 0], "pp": [25, 40, 30, 0],
        "evs": {"hp": evs["hp"], "attack": evs["atk"], "defense": evs["def"],
                "speed": evs["spe"], "sp_attack": evs["spa"], "sp_defense": evs["spd"]},
        "contest": [0, 0, 0, 0, 0, 0],
        "pokerus": 0, "met_location": 0, "met_level": level, "met_game": 1, "pokeball": 4,
        "ot_gender": 0,
        "ivs": {"hp": ivs["hp"], "attack": ivs["atk"], "defense": ivs["def"],
                "speed": ivs["spe"], "sp_attack": ivs["spa"], "sp_defense": ivs["spd"]},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
        "status": 0, "level": level, "mail": 0xFF,
        "hp": stats["hp"], "max_hp": stats["hp"], "attack": stats["atk"], "defense": stats["def"],
        "speed": stats["spe"], "sp_attack": stats["spa"], "sp_defense": stats["spd"],
    }, stats


VANILLA = Gen3Adapter(is_rr=False)
RR = Gen3Adapter(is_rr=True)


def test_gen3_vanilla_calc_stats_decodes_ivs_evs_and_matches_formula():
    level = 63
    ivs = {"hp": 31, "atk": 20, "def": 15, "spa": 10, "spd": 5, "spe": 0}
    evs = {"hp": 252, "atk": 128, "def": 0, "spa": 6, "spd": 0, "spe": 4}
    mon, stats = _g3_mon(level, ivs, evs, ot_id=0xDEADBEEF)
    blob = gen3_codec.encode_party_mon(mon, rr=False)
    assert len(blob) == gen3_codec.PARTY_MON_SIZE

    cs = VANILLA.calc_stats({"key": "k", "level": level, "blob_hex": blob.hex()})
    assert cs == {"ivs": ivs, "evs": evs, "stats": stats}

    for stat in _G3_BASE:
        expected = _g3_stat(_G3_BASE[stat], cs["ivs"][stat], cs["evs"][stat],
                             level, is_hp=(stat == "hp"))
        assert expected == cs["stats"][stat], stat


def test_gen3_rr_calc_stats_uses_the_unencrypted_fixed_substruct_order():
    level = 40
    ivs = {"hp": 5, "atk": 31, "def": 12, "spa": 25, "spd": 18, "spe": 31}
    evs = {"hp": 0, "atk": 252, "def": 4, "spa": 0, "spd": 0, "spe": 252}
    mon, stats = _g3_mon(level, ivs, evs, ot_id=0x11223344)
    blob = gen3_codec.encode_party_mon(mon, rr=True)

    cs = RR.calc_stats({"key": "k", "level": level, "blob_hex": blob.hex()})
    assert cs == {"ivs": ivs, "evs": evs, "stats": stats}

    # A vanilla (encrypted / permuted-substruct) decode of the same bytes must NOT
    # agree -- otherwise this test would pass even if the adapter ignored the rr flag.
    wrong = VANILLA.calc_stats({"key": "k", "level": level, "blob_hex": blob.hex()})
    assert wrong is None or wrong != cs


# ---------------------------------------------------------------------------
# Gen 3 Emerald -- unlike every other case in this file, party bytes here are NOT
# hand-built: they're read straight off a real save file (tests/fixtures/gen3/
# emerald_battle.sav, built by tools/gen3_fixtures.py), the same way the live server
# gets blob_hex, to prove the adapter's rom_type="emerald" path decodes a real save's
# SaveBlock1 party slot 0 correctly end to end (not just a synthetic encode/decode
# round-trip of our own construction).
# ---------------------------------------------------------------------------

_MUDKIP_BASE = {"hp": 50, "atk": 70, "def": 50, "spa": 50, "spd": 50, "spe": 40}
# pret pokeemerald c65e93f2, src/data/pokemon/species_info.h:7799-7819 SPECIES_MUDKIP:
# baseHP 50, baseAttack 70, baseDefense 50, baseSpeed 40, baseSpAttack 50, baseSpDefense 50
# (tools/gen3_fixtures.py's own MUDKIP comment, ~964-972, glosses this as "50/70/50/40/50/50"
# in hp/atk/def/spa/spd/spe order, which transposes speed and special attack -- both are 50
# except speed, so it never showed up there; this test's own formula check catches it).
_MUDKIP_LEVEL = 5
_MUDKIP_IV = 15  # tools/gen3_fixtures.py STARTER_IV


def test_gen3_emerald_calc_stats_decodes_real_save_party_mon_0():
    fixture = os.path.join(os.path.dirname(__file__), "..", "fixtures", "gen3", "emerald_battle.sav")
    with open(fixture, "rb") as fh:
        image = fh.read()

    sb1 = gen3_codec.parse_flash(image, title=gen3_codec.TITLE_EMERALD)["sb1"]
    count = sb1[gen3_codec.SB1_PARTY_COUNT_OFFSET_EMERALD]
    assert count >= 1, "fixture save has no party mon 0 to read"
    start = gen3_codec.SB1_PARTY_OFFSET_EMERALD
    blob = sb1[start:start + gen3_codec.PARTY_MON_SIZE]

    EMERALD = Gen3Adapter(rom_type="emerald")
    cs = EMERALD.calc_stats({"key": "k", "level": _MUDKIP_LEVEL, "blob_hex": blob.hex()})
    assert cs is not None

    assert cs["ivs"] == dict.fromkeys(_MUDKIP_BASE, _MUDKIP_IV)
    assert cs["evs"] == dict.fromkeys(_MUDKIP_BASE, 0)  # freshly-received starter, no EVs yet

    for stat, base in _MUDKIP_BASE.items():
        expected = _g3_stat(base, _MUDKIP_IV, 0, _MUDKIP_LEVEL, is_hp=(stat == "hp"))
        assert cs["stats"][stat] == expected, stat


def test_gen3_calc_stats_none_on_missing_or_bad_blob():
    assert VANILLA.calc_stats({"key": "k", "level": 50}) is None
    assert VANILLA.calc_stats({"key": "k", "level": 50, "blob_hex": ""}) is None
    assert VANILLA.calc_stats({"key": "k", "level": 50, "blob_hex": "zz"}) is None
    assert VANILLA.calc_stats({"key": "k", "level": 50, "blob_hex": "00" * 10}) is None  # too short


# ---------------------------------------------------------------------------
# /api/calc/mons entry (_build_mon_entry): calc_stats rides along, or is None.
# ---------------------------------------------------------------------------

def test_build_mon_entry_carries_calc_stats():
    calc_stats = {"ivs": {"hp": 31}, "evs": {}, "stats": {}}
    entry = _build_mon_entry("k", {"species_id": 4, "level": 50, "calc_stats": calc_stats}, VANILLA)
    assert entry["calc_stats"] == calc_stats

    entry_none = _build_mon_entry("k2", {"species_id": 4, "level": 50}, VANILLA)
    assert entry_none["calc_stats"] is None


def test_gen1_enemy_without_blob_uses_raw_dvs_and_no_stat_exp():
    """A wild Gen 1 foe sends only its raw DV word: 0 stat exp, stats unknown."""
    cs = Gen1Adapter().calc_stats({"key": "", "level": 5, "dvs_raw": 0x9888})
    assert cs["dvs"] == {"atk": 9, "def": 8, "spe": 8, "spc": 8}
    assert cs["stat_exp"] == {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0}
    assert "stats" not in cs


def test_enemy_without_max_hp_is_unknown_not_full():
    """No maxHP from the client means unknown HP, not the old forced 100%."""
    entry = _build_mon_entry("foe-0", {"species_id": 4, "level": 5, "hp": 12}, VANILLA)
    assert entry["maxHP"] is None and entry["hp_pct"] is None
