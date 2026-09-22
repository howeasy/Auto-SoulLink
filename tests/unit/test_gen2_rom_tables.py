"""ASM-known byte vectors and actual pinned ROM controls for Python's F-4 half.

No Lua source, legacy generated tables, or emulator contributes the expected data.
Actual-source tests require the verified P1 artifacts: missing inputs fail visibly.
"""
import copy
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# P2 reads facts without activating legacy GameRules adapters. Importing the package
# eagerly initializes those adapters and their old generated-data consumers.
_spec = importlib.util.spec_from_file_location("gen2_rom_scan", ROOT / "server/adapters/gen2_rom_scan.py")
_scanner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scanner)
OPEN_OBLIGATIONS, Rom, RomScanError, rom_offset = (
    _scanner.OPEN_OBLIGATIONS, _scanner.Rom, _scanner.RomScanError, _scanner.rom_offset,
)
SYMBOLS = (
    "BaseData", "JohtoGrassWildMons", "KantoGrassWildMons", "SwarmGrassWildMons",
    "JohtoWaterWildMons", "KantoWaterWildMons", "SwarmWaterWildMons",
    "GrassMonProbTable", "WaterMonProbTable", "TreeMonMaps", "RockMonMaps", "TreeMons",
    "FishGroups", "TimeFishGroups", "RoamMaps", "InitRoamMons",
)


def constants(title):
    # C/G constants/pokemon_data_constants.asm:1-32,179-199; C/G fish.asm final table.
    return {"NUM_POKEMON": 251, "BASE_DATA_SIZE": 32, "BASE_TMHM": 24, "NUM_GRASSMON": 7,
            "NUM_WATERMON": 3, "GRASS_WILDDATA_LENGTH": 47, "WATER_WILDDATA_LENGTH": 9,
            "NUM_TREEMON_SETS": 8 if title == "crystal" else 6,
            "TREEMON_SET_ROCK": 7 if title == "crystal" else 3,
            "NUM_FISHGROUPS": 13, "FISHGROUP_DATA_LENGTH": 7, "NUM_TIME_FISHGROUPS": 22,
            "NUM_ROAMMON_MAPS": 16}


def with_hash(rom, profile):
    profile = copy.deepcopy(profile)
    profile["rom_sha1"] = hashlib.sha1(rom).hexdigest()
    return Rom(bytes(rom), profile)


@pytest.fixture
def vector():
    """Relocated bank-one bytes exercise pointer use without real-ROM addresses."""
    rom = bytearray(0x8000)
    profile = {"title": "crystal", "rom": {}, "ram": {}, "constants": constants("crystal")}
    position = 0x4000

    def put(name, data):
        nonlocal position
        start = position
        rom[start:start + len(data)] = data
        position += len(data)
        profile["rom"][name] = {"bank": 1, "addr": start, "flat": start}
        return start

    # Bulbasaur expected fields from both pins' data/pokemon/base_stats/bulbasaur.asm.
    base = bytes([1, 45, 49, 49, 45, 65, 65, 22, 3, 45, 64, 0, 0, 31,
                  100, 20, 5, 0x55, 0, 0, 0, 0, 3, 0x17]) + bytes(range(8))
    put("BaseData", b"".join(bytes([species]) + base[1:] for species in range(1, 252)))
    # Crystal Sprout Tower 2F, source johto_grass.asm:5-30; numeric map is relocated.
    grass = bytes([1, 2, 5, 5, 5]) + bytes([3, 19, 4, 19, 5, 19, 3, 19, 6, 19, 5, 19, 5, 19]) * 2
    grass += bytes([3, 92, 4, 92, 5, 92, 3, 19, 6, 92, 5, 19, 5, 19])
    put("JohtoGrassWildMons", grass + b"\xff")
    put("KantoGrassWildMons", b"\xff")
    put("SwarmGrassWildMons", b"\xff")
    put("JohtoWaterWildMons", bytes([1, 3, 5, 15, 194, 20, 195, 15, 195, 255]))
    put("KantoWaterWildMons", b"\xff")
    put("SwarmWaterWildMons", b"\xff")
    put("GrassMonProbTable", bytes([30, 0, 60, 2, 80, 4, 90, 6, 95, 8, 99, 10, 100, 12]))
    put("WaterMonProbTable", bytes([60, 0, 90, 2, 100, 4]))
    # Weighted lists from Crystal TreeMonSet_Canyon and TreeMonSet_Rock.
    common = bytes([50, 21, 10, 15, 21, 10, 15, 21, 10, 10, 190, 10, 5, 190, 10, 5, 190, 10, 255])
    rare = bytes([50, 21, 10, 15, 214, 10, 15, 214, 10, 10, 190, 10, 5, 190, 10, 5, 190, 10, 255])
    common_address = put("fixture_tree", common + rare)
    rock_address = put("fixture_rock", bytes([90, 98, 15, 10, 213, 15, 255]))
    put("TreeMons", b"\0\0" + common_address.to_bytes(2, "little") * 6 + rock_address.to_bytes(2, "little"))
    put("TreeMonMaps", bytes([1, 2, 1, 1, 3, 0, 255]))
    put("RockMonMaps", bytes([1, 4, 7, 255]))
    # fish.asm Shore Old: raw inclusive thresholds; Good contains a time-group token.
    old = put("fixture_old", bytes([179, 129, 10, 217, 129, 10, 255, 98, 10]))
    good = put("fixture_good", bytes([89, 129, 20, 178, 98, 20, 230, 98, 20, 255, 0, 0]))
    sup = put("fixture_super", bytes([102, 98, 40, 178, 0, 1, 230, 98, 40, 255, 99, 40]))
    put("FishGroups", (b"\x80" + b"".join(n.to_bytes(2, "little") for n in (old, good, sup))) * 13)
    put("TimeFishGroups", bytes([222, 20, 120, 20, 222, 40, 120, 40]) + bytes([60, 20, 60, 20]) * 20)
    put("RoamMaps", b"".join(bytes([1, i, 1, 1, i % 16 + 1, 0]) for i in range(1, 17)) + b"\xff")
    ram = profile["ram"]
    for index in (1, 2):
        for offset, field in enumerate(("Species", "Level", "MapGroup", "MapNumber", "HP")):
            ram[f"wRoamMon{index}{field}"] = 0xd000 + index * 10 + offset

    def store(index, field):
        return b"\xea" + ram[f"wRoamMon{index}{field}"].to_bytes(2, "little")

    code = b"\x3e\xf3" + store(1, "Species") + b"\x3e\xf4" + store(2, "Species")
    code += b"\x3e\x28" + store(1, "Level") + store(2, "Level")
    for index, number in ((1, 14), (2, 9)):
        code += b"\x3e\x01" + store(index, "MapGroup") + bytes([0x3e, number]) + store(index, "MapNumber")
    code += b"\xaf" + store(1, "HP") + store(2, "HP") + b"\xc9"
    put("InitRoamMons", code)
    return rom, profile


def test_source_known_vectors_preserve_all_families(vector):
    result = with_hash(*vector).scan_all()
    base = result["base_stats"][0]
    assert [base[k] for k in ("hp", "attack", "defense", "speed", "special_attack", "special_defense")] == [45, 49, 49, 45, 65, 65]
    assert (base["hatch_cycles"], base["growth_rate"], base["egg_group1"], base["egg_group2"]) == (20, 3, 1, 7)
    assert base["tmhm_bytes"] == list(range(8))
    grass = result["wild"]["grass"]
    assert [row["time"] for row in grass] == ["morning", "day", "night"]
    assert [row["slots"][0] for row in grass] == [{"species": 19, "level": 3}, {"species": 19, "level": 3}, {"species": 92, "level": 3}]
    assert result["wild"]["water"][0]["slots"][1] == {"species": 195, "level": 20}
    assert result["tree"]["sets"][0]["rare"][1] == {"weight": 15, "species": 214, "level": 10}
    assert result["tree"]["sets"][-1]["rare"] == []
    assert result["fishing"]["groups"][0]["good"][-1] == {"threshold": 255, "species": 0, "level": 0}
    assert result["fishing"]["time_groups"][0]["night"] == {"species": 120, "level": 20}
    assert result["roamers"]["initial"] == [{"species": 243, "level": 40, "map_group": 1, "map_number": 14}, {"species": 244, "level": 40, "map_group": 1, "map_number": 9}]
    assert len(result["roamers"]["maps"]) == 16
    assert result["open_obligations"] == list(OPEN_OBLIGATIONS)


@pytest.mark.parametrize("bank,address", [(0, 0x4000), (1, 0x3fff), (1, 0x8000), (-1, 0), (True, 0)])
def test_non_rom_or_ambiguous_addresses_refuse(bank, address):
    with pytest.raises(RomScanError):
        rom_offset(bank, address)


def test_profile_hash_and_required_facts_are_not_optional(vector):
    rom, profile = vector
    with pytest.raises(RomScanError, match="rom_sha1"):
        Rom(bytes(rom), profile)
    reader = with_hash(rom, profile)
    corrupted = bytearray(rom)
    corrupted[0] ^= 1
    with pytest.raises(RomScanError, match="SHA1"):
        Rom(bytes(corrupted), reader.profile)
    del profile["rom"]["FishGroups"]
    with pytest.raises(RomScanError, match="FishGroups"):
        with_hash(rom, profile).scan_all()


@pytest.mark.parametrize("symbol,delta,value,method", [
    ("BaseData", 0, 2, "base"),
    ("GrassMonProbTable", 12, 99, "wild"),
    ("JohtoGrassWildMons", 6, 0, "wild"),
    ("fixture_tree", 0, 90, "tree"),
    ("fixture_old", 3, 179, "fishing"),
    ("fixture_good", 11, 22, "fishing"),
    ("InitRoamMons", 0, 0, "roamers"),
    ("RoamMaps", 5, 255, "roamers"),
])
def test_single_byte_format_divergence_is_red(vector, symbol, delta, value, method):
    rom, profile = vector
    rom[profile["rom"][symbol]["flat"] + delta] = value
    reader = with_hash(rom, profile)
    with pytest.raises(RomScanError):
        reader.base_stats(1) if method == "base" else getattr(reader, method)()


def test_truncated_tables_and_bad_bank_local_pointers_refuse(vector):
    rom, profile = vector
    profile["rom"]["JohtoGrassWildMons"] = {"bank": 1, "addr": 0x7ffe, "flat": 0x7ffe}
    rom[-2:] = b"\x01\x01"
    with pytest.raises(RomScanError, match="truncated"):
        with_hash(rom, profile).wild()
    profile["rom"]["FishGroups"]["flat"] += 1
    with pytest.raises(RomScanError, match="contradictory"):
        with_hash(rom, profile).fishing()


@pytest.fixture(scope="module")
def actual():
    from tools.gen2_source_data import load_context

    result = {}
    for title in ("crystal", "gold", "silver"):
        context = load_context(title, root=ROOT)
        symbols = {name: {"bank": context.symbol(name).bank, "addr": context.symbol(name).address,
                          "flat": rom_offset(*context.symbol(name))} for name in SYMBOLS}
        ram = {name: value.address for name, value in context.symbols.items() if name.startswith("wRoamMon")}
        profile = {"title": title, "rom_sha1": context.source_record()["rom_sha1"],
                   "rom": symbols, "ram": ram, "constants": constants(title)}
        result[title] = (context, Rom(context.rom, profile).scan_all())
    return result


@pytest.mark.parametrize("title", ("crystal", "gold", "silver"))
def test_actual_pinned_rom_known_positives(actual, title):
    context, result = actual[title]
    assert len(result["base_stats"]) == 251
    assert result["base_stats"][0]["hp"] == 45
    assert result["base_stats"][0]["type1"] == 22
    assert result["base_stats"][0]["type2"] == 3
    assert result["base_stats"][0]["gender_ratio"] == 31
    assert result["base_stats"][150]["species"] == 151
    assert len(result["fishing"]["groups"]) == 13
    assert len(result["fishing"]["time_groups"]) == 22
    assert result["tree"]["sets"][-1 if title == "crystal" else 2]["common"] == [{"weight": 90, "species": 98, "level": 15}, {"weight": 10, "species": 213, "level": 15}]
    assert [r["species"] for r in result["roamers"]["initial"]] == ([243, 244] if title == "crystal" else [243, 244, 245])
    assert all(r["level"] == 40 for r in result["roamers"]["initial"])
    assert len(result["roamers"]["maps"]) == 16
    assert context.source_commit in {"7a7881d0d62e0ddbd82dcf10e7116807487ac651", "656583c939d30f920a316177311a502dd222b57c"}


def test_gold_and_silver_are_distinct_and_night_tables_are_preserved(actual):
    gold = actual["gold"][1]
    silver = actual["silver"][1]
    assert gold["wild"]["grass"] != silver["wild"]["grass"]
    assert gold["tree"]["sets"] != silver["tree"]["sets"]
    crystal = actual["crystal"][1]
    assert crystal["wild"]["grass"][0]["slots"][0] == {"species": 19, "level": 3}
    assert crystal["wild"]["grass"][2]["slots"][0] == {"species": 92, "level": 3}
