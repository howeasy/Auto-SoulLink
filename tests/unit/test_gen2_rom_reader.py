"""Independent Lua ROM-reader controls from pinned Gen 2 ASM and actual ROMs.

The source controls were frozen independently before adding Python/Lua equality.
Only the final equality fixtures import the Python scanner's public entry point.
Missing real source-build inputs fail, never skip. Constants/expected vectors
below were derived from the named sources, independently of the Python reader.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
LUA_PATH = ROOT / "lua/gen2/rom.lua"
ARTIFACTS = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}


def native(value):
    if not hasattr(value, "keys"):
        return value
    keys = list(value.keys())
    if not keys or all(isinstance(key, int) for key in keys):
        assert sorted(keys) == list(range(1, len(keys) + 1))
        return [native(value[index]) for index in range(1, len(keys) + 1)]
    return {key: native(value[key]) for key in keys}


@pytest.fixture(scope="module", params=ARTIFACTS)
def cartridge(request):
    title = request.param
    artifact = ARTIFACTS[title]
    lock = json.loads((ROOT / "data/gen2_sources.lock.json").read_text())
    spec = lock["outputs"][artifact]
    source = ROOT / ".cache/gen2-build" / spec["source"]
    image = (source / spec["filename"]).read_bytes()
    symbols = (ROOT / "data/gen2" / f"{artifact}.sym").read_bytes()
    linker = (ROOT / "data/gen2" / f"{artifact}.map").read_bytes()
    assert hashlib.sha1(image).hexdigest() == spec["sha1"]
    assert hashlib.sha256(symbols).hexdigest() == spec["sym_sha256"]
    assert hashlib.sha256(linker).hexdigest() == spec["map_sha256"]
    rom, ram = {}, {}
    for line in symbols.decode().splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if not match:
            continue
        bank, address = int(match[1], 16), int(match[2], 16)
        name = match[3]
        if address < 0x8000:
            flat = address if bank == 0 else bank * 0x4000 + address - 0x4000
            rom[name] = {"bank": bank, "addr": address, "flat": flat}
        elif name.startswith("wRoamMon"):
            ram[name] = address
    # constants/pokemon_data_constants.asm, constants/map_data_constants.asm,
    # data/wild/fish.asm TimeFishGroups, engine/overworld/wildmons.asm InitRoamMons.
    profile = {
        "title": title, "rom": rom, "ram": ram,
        "derived": {
            "rom_size": len(image), "species_count": 251, "base_stats_stride": 32,
            "num_grassmon": 7, "num_watermon": 3, "num_fishgroups": 13,
            "num_treemon_sets": 8 if title == "crystal" else 6,
            "treemon_set_rock": 7 if title == "crystal" else 3,
            # GetTreeMons cp bound: C engine/events/treemons.asm:100, G :101.
            "treemon_enabled_limit": 8 if title == "crystal" else 4,
            "num_time_fishgroups": 22, "num_roammon_maps": 16,
            "roamer_count": 2 if title == "crystal" else 3,
        },
    }
    return title, image, profile


def reader(image, profile, *, overrides=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(LUA_PATH.read_text(encoding="utf-8"))

    def read(flat, domain):
        assert domain == "ROM", "reader must never touch live memory"
        assert isinstance(flat, int) and 0 <= flat < len(image), "ROM read outside image"
        return (overrides or {}).get(flat, image[flat])

    result = module.new(lua.table_from(profile, recursive=True), lua.table_from({"read_u8": read}))
    return result


@pytest.fixture
def rom_reader(cartridge):
    _, image, profile = cartridge
    return reader(image, profile)


def test_source_base_stat_vectors_and_gender_bytes(rom_reader):
    # Both pinned data/pokemon/base_stats/{bulbasaur,magnemite,nidoran_f,celebi}.asm.
    bulbasaur = native(rom_reader.base_stats(1))
    assert {key: bulbasaur[key] for key in (
        "species", "hp", "attack", "defense", "speed", "special_attack", "special_defense",
        "type1", "type2", "catch_rate", "base_exp", "gender_ratio", "hatch_cycles",
        "growth_rate", "egg_group1", "egg_group2",
    )} == {
        "species": 1, "hp": 45, "attack": 49, "defense": 49, "speed": 45,
        "special_attack": 65, "special_defense": 65, "type1": 22, "type2": 3,
        "catch_rate": 45, "base_exp": 64, "gender_ratio": 31, "hatch_cycles": 20,
        "growth_rate": 3, "egg_group1": 1, "egg_group2": 7,
    }
    magnemite = native(rom_reader.base_stats(81))
    assert (magnemite["special_attack"], magnemite["special_defense"], magnemite["gender_ratio"]) == (95, 55, 255)
    assert rom_reader.base_stats(29)["gender_ratio"] == 254
    celebi = native(rom_reader.base_stats(251))
    assert celebi["species"] == 251 and celebi["hp"] == 100 and celebi["gender_ratio"] == 255
    assert len(celebi["tmhm_bytes"]) == 8


def test_source_wild_vectors_include_time_and_swarm_tables(cartridge, rom_reader):
    title, _, _ = cartridge
    wild = native(rom_reader.wild())
    # Johto grass first map: Sprout Tower 2F, group3/map2, Rattata/Gastly.
    first = wild["grass"][:3]
    assert [row["time"] for row in first] == ["morning", "day", "night"]
    assert all((row["map_group"], row["map_number"], row["rate"]) == (3, 2, 5) for row in first)
    assert first[0]["slots"][0] == {"species": 19, "level": 3}
    assert first[2]["slots"][0] == {"species": 92, "level": 3}
    water = wild["water"][0]
    assert (water["map_group"], water["map_number"], water["time"]) == (3, 22, "all")
    assert water["slots"] == [
        {"species": 194, "level": 15}, {"species": 195, "level": 20},
        {"species": 195, "level": 15},
    ]
    assert wild["grass_probabilities"] == [
        {"threshold": threshold, "slot_offset": index * 2}
        for index, threshold in enumerate((30, 60, 80, 90, 95, 99, 100))
    ]
    assert any(row["table"] == "SwarmGrassWildMons" for row in wild["grass"])
    assert any(row["table"] == "SwarmWaterWildMons" for row in wild["water"]) == (title != "crystal")


def test_source_tree_and_rock_vectors_preserve_title_differences(cartridge, rom_reader):
    title, _, _ = cartridge
    tree = native(rom_reader.tree())
    assert len(tree["headbutt_maps"]) == 34
    assert len(tree["rock_smash_maps"]) == 4
    assert len(tree["sets"]) == (7 if title == "crystal" else 3)
    assert tree["enabled_set_limit"] == (8 if title == "crystal" else 4)
    assert [row["set_id"] for row in tree["sets"]] == list(range(1, 8 if title == "crystal" else 4))
    rock = next(row for row in tree["sets"] if row["kind"] == "rock_smash")
    assert rock["common"] == [
        {"weight": 90, "species": 98, "level": 15},
        {"weight": 10, "species": 213, "level": 15},
    ]
    assert rock["rare"] == []  # Source explicitly contains only one rock table.
    if title != "crystal":
        forest = next(row for row in tree["sets"] if row["set_id"] == 1)
        assert forest["common"][0]["species"] == (10 if title == "gold" else 13)


def test_source_fishing_vectors_preserve_thresholds_and_time_indirection(rom_reader):
    fish = native(rom_reader.fishing())
    assert len(fish["groups"]) == 13 and len(fish["time_groups"]) == 22
    shore = fish["groups"][0]
    assert shore["group_id"] == 1 and shore["bite_threshold"] == 128
    assert shore["old"] == [
        {"threshold": 179, "species": 129, "level": 10},
        {"threshold": 217, "species": 129, "level": 10},
        {"threshold": 255, "species": 98, "level": 10},
    ]
    assert shore["good"][-1] == {"threshold": 255, "species": 0, "level": 0}
    assert fish["time_groups"][0] == {
        "group_id": 0, "day": {"species": 222, "level": 20},
        "night": {"species": 120, "level": 20},
    }


def test_source_roamer_initializers_and_graph(cartridge, rom_reader):
    title, _, _ = cartridge
    roamers = native(rom_reader.roamers())
    expected = [
        {"species": 243, "level": 40, "map_group": 2, "map_number": 5},
        {"species": 244, "level": 40, "map_group": 10, "map_number": 4},
    ]
    if title != "crystal":
        expected.append({"species": 245, "level": 40, "map_group": 1, "map_number": 12})
    assert roamers["initial"] == expected
    assert len(roamers["maps"]) == 16
    assert [len(row["destinations"]) for row in roamers["maps"]] == [2, 2, 3, 3, 2, 2, 2, 4, 3, 3, 1, 4, 2, 3, 2, 2]


def test_complete_scan_names_open_boundaries(cartridge, rom_reader):
    title, _, _ = cartridge
    result = native(rom_reader.scan_all())
    assert result["schema"] == "gen2-rom-tables-v1" and result["title"] == title
    assert len(result["base_stats"]) == 251
    assert result["open_obligations"] == [
        "fishing_map_association", "contest_encounters", "runtime_encounter_selection",
    ]


@pytest.mark.parametrize("species", (0, 252, 253, -1, 1.5))
def test_invalid_species_and_egg_sentinel_refuse(rom_reader, species):
    with pytest.raises(LuaError, match="species"):
        rom_reader.base_stats(species)


def test_missing_symbol_and_inconsistent_bank_refuse(cartridge):
    _, image, original = cartridge
    profile = copy.deepcopy(original)
    del profile["rom"]["FishGroups"]
    with pytest.raises(LuaError, match="FishGroups"):
        reader(image, profile).fishing()
    profile = copy.deepcopy(original)
    profile["rom"]["BaseData"]["bank"] += 1
    with pytest.raises(LuaError, match="BaseData"):
        reader(image, profile).base_stats(1)


@pytest.mark.parametrize("fault", ("base_species", "fish_pointer", "tree_weight", "roamer_opcode"))
def test_malformed_record_pointer_weights_and_opcode_refuse(cartridge, fault):
    _, original, profile = cartridge
    image = bytearray(original)
    if fault == "base_species":
        image[profile["rom"]["BaseData"]["flat"]] = 0
        method, args = "base_stats", (1,)
    elif fault == "fish_pointer":
        flat = profile["rom"]["FishGroups"]["flat"]
        image[flat + 1:flat + 3] = b"\x00\xc0"  # WRAM, never a ROM pointer.
        method, args = "fishing", ()
    elif fault == "tree_weight":
        symbol = profile["rom"]["TreeMons"]
        pointer = int.from_bytes(image[symbol["flat"] + 2:symbol["flat"] + 4], "little")
        flat = symbol["bank"] * 0x4000 + pointer - 0x4000
        image[flat] = 101
        method, args = "tree", ()
    else:
        image[profile["rom"]["InitRoamMons"]["flat"]] = 0x00
        method, args = "roamers", ()
    with pytest.raises(LuaError):
        getattr(reader(image, profile), method)(*args)


def test_declared_rom_bounds_prevent_callback_overread(cartridge):
    _, image, original = cartridge
    profile = copy.deepcopy(original)
    profile["derived"]["rom_size"] = profile["rom"]["BaseData"]["flat"] + 4
    with pytest.raises(LuaError, match="bound"):
        reader(image, profile).base_stats(1)


@pytest.mark.parametrize("field,value", (("species_count", 250), ("base_stats_stride", 33)))
def test_unqualified_profile_geometry_cannot_return_partial_success(cartridge, field, value):
    _, image, original = cartridge
    profile = copy.deepcopy(original)
    profile["derived"][field] = value
    with pytest.raises(LuaError, match="geometry"):
        reader(image, profile).base_stats(1)


def test_fishing_time_index_must_stay_inside_declared_time_table(cartridge):
    _, original, profile = cartridge
    image = bytearray(original)
    symbol = profile["rom"]["FishGroups"]
    pointer = int.from_bytes(image[symbol["flat"] + 3:symbol["flat"] + 5], "little")
    good_rod = symbol["bank"] * 0x4000 + pointer - 0x4000
    # Shore Good's fourth entry is the time-group indirection in both pinned sources.
    image[good_rod + 11] = profile["derived"]["num_time_fishgroups"]
    with pytest.raises(LuaError, match="time group"):
        reader(image, profile).fishing()


@pytest.fixture(scope="module")
def python_scan():
    # F4 comparison began only after independent decoder freezes:
    # Lua dd1cb30e1829 / Python be08de820761. Import the pure leaf, not the
    # legacy adapter package's eager imports. Never use it as a Lua test oracle
    # for the independent source-known controls above.
    name = "gen2_rom_scan_for_independent_equality"
    spec = importlib.util.spec_from_file_location(name, ROOT / "server/adapters/gen2_rom_scan.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module.scan_all
    finally:
        del sys.modules[name]


@pytest.fixture(scope="module")
def generated_profile(cartridge):
    title, image, _ = cartridge
    wrapper = json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text())
    assert wrapper["schema"] == "gen2-profile-v1"
    assert set(wrapper["titles"]) == {title}
    selected = wrapper["titles"][title]
    source = wrapper["source"]
    assert selected["title"] == title and selected["artifact"] == ARTIFACTS[title]
    assert selected["rom_sha1"] == source["rom_sha1"] == hashlib.sha1(image).hexdigest()
    assert source["lock_sha256"] == hashlib.sha256((ROOT / "data/gen2_sources.lock.json").read_bytes()).hexdigest()
    assert source["build_provenance_sha256"] == hashlib.sha256(
        (ROOT / "data/gen2/build_provenance.json").read_bytes()
    ).hexdigest()
    return selected


def assert_reader_equality(lua_result, python_result, title):
    metadata = {
        "schema": "gen2-rom-tables-v1",
        "title": title,
        "open_obligations": [
            "fishing_map_association", "contest_encounters", "runtime_encounter_selection",
        ],
    }
    families = ("base_stats", "wild", "tree", "fishing", "roamers")
    assert set(lua_result) == set(python_result) == set(metadata) | set(families)
    for name, expected in metadata.items():
        assert lua_result[name] == python_result[name] == expected, name
    for name in families:
        assert lua_result[name] == python_result[name], f"independent reader mismatch: {name}"


def test_generated_profile_full_python_lua_equality(cartridge, generated_profile, python_scan):
    title, image, _ = cartridge
    lua_result = native(reader(image, generated_profile).scan_all())
    python_result = python_scan(image, generated_profile)
    assert_reader_equality(lua_result, python_result, title)


def test_equality_oracle_detects_one_valid_lua_rom_read_difference(
    cartridge, generated_profile, python_scan,
):
    title, image, _ = cartridge
    expected = python_scan(image, generated_profile)
    # Establish equality first; a generic reader/fixture failure cannot close this control.
    positive = native(reader(image, generated_profile).scan_all())
    assert_reader_equality(positive, expected, title)

    # A valid alternate HP byte at the source-derived Bulbasaur record, returned
    # only to Lua. Species/layout/bounds and underlying ROM/profile hashes stay
    # valid. This checks the equality oracle rather than an input hash refusal.
    flat = generated_profile["rom"]["BaseData"]["flat"] + 1
    changed = native(reader(image, generated_profile, overrides={flat: image[flat] + 1}).scan_all())
    assert changed["base_stats"][0]["hp"] == positive["base_stats"][0]["hp"] + 1
    restored = copy.deepcopy(changed)
    restored["base_stats"][0]["hp"] = positive["base_stats"][0]["hp"]
    assert restored == positive, "negative control must change exactly one decoded field"
    with pytest.raises(AssertionError, match="independent reader mismatch: base_stats"):
        assert_reader_equality(changed, expected, title)


def test_roaming_map_terminator_must_remain_in_table_bank(cartridge, generated_profile, python_scan):
    title, original, _ = cartridge
    # Pinned data/wild/roammon_maps.asm: 16 rows with 40 total destinations.
    # The body is 16*(group+number+count+zero) + 40*2 = 144 bytes, then $ff.
    start = generated_profile["rom"]["RoamMaps"]["flat"]
    body = original[start:start + 144]
    assert original[start + 144] == 255
    expected = python_scan(original, generated_profile)
    bank, bank_end = 126, 127 * 0x4000
    assert bank_end < len(original)

    def relocated(terminator_in_bank):
        profile = copy.deepcopy(generated_profile)
        flat = bank_end - len(body) - int(terminator_in_bank)
        profile["rom"]["RoamMaps"] = {
            "bank": bank, "addr": 0x4000 + flat - bank * 0x4000, "flat": flat,
        }
        image = bytearray(original)
        image[flat:flat + len(body) + 1] = body + b"\xff"
        # This is an explicitly synthetic relocation profile, not an admitted
        # cartridge. Keep its byte identity consistent to reach both parsers.
        profile["rom_sha1"] = hashlib.sha1(image).hexdigest()
        return bytes(image), profile

    # Valid relocation changes no decoded fact; both independently frozen readers
    # must accept a terminator in the last byte of the table's own bank.
    positive, profile = relocated(True)
    assert python_scan(positive, profile) == expected
    assert_reader_equality(native(reader(positive, profile).scan_all()), expected, title)

    # The same intact table body now ends at the bank boundary. The only $ff
    # following it belongs to the next bank, so neither reader may consume it.
    negative, profile = relocated(False)
    with pytest.raises(ValueError):
        python_scan(negative, profile)
    with pytest.raises(LuaError, match="bound"):
        reader(negative, profile).roamers()


@pytest.mark.parametrize("value", (None, 1, 9, "rock", 2.5))
def test_tree_enabled_limit_fact_is_required_and_bounded(cartridge, value):
    _, image, original = cartridge
    profile = copy.deepcopy(original)
    if value is None:
        del profile["derived"]["treemon_enabled_limit"]
    else:  # "rock" would disable the rock-smash set.
        profile["derived"]["treemon_enabled_limit"] = (
            profile["derived"]["treemon_set_rock"] if value == "rock" else value)
    with pytest.raises(LuaError):
        reader(image, profile).tree()
