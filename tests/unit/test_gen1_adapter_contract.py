"""Gen 1 adapter contract checked against pret source, independently of shipped JSON."""

from __future__ import annotations

import inspect
import json
import random
import re
from pathlib import Path

import pytest

from server.adapters import game_id_for_rom_type, gen1_codec, get_adapter
from server.adapters.base import GamePresentationAdapter, GameRulesAdapter
from server.adapters.gen1_rby import Gen1Adapter
from server.data.items.gen1 import ITEM_NAMES

ROOT = Path(__file__).resolve().parents[2]
PRET = ROOT / ".cache" / "pret" / "pokered"
DATA = ROOT / "data" / "games" / "gen1_rby"


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repository's disk-writing state fixture in this read-only suite."""
    yield


def _source(rel: str) -> str:
    if not PRET.is_dir():
        pytest.skip(f"pret pokered checkout absent: {PRET}")
    return (PRET / rel).read_text(encoding="utf-8")


def _json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _constants(rel: str, pattern: str) -> dict[str, int]:
    """Parse pret order/explicit IDs; no adapter mapping or generated JSON input."""
    matches = re.finditer(pattern, _source(rel), re.M)
    return {m[1]: i for i, m in enumerate(matches)}


def _dex_order() -> dict[int, int]:
    dex_defs = _constants("constants/pokedex_constants.asm", r"^\s*const (DEX_\w+)")
    table = re.findall(r"^\s*db (DEX_\w+|0)(?:\s*;.*)?$",
                       _source("data/pokemon/dex_order.asm"), re.M)
    assert len(dex_defs) == 151 and len(table) == 190
    return {i: dex_defs[name] + 1 if name != "0" else 0
            for i, name in enumerate(table, 1)}


def _types() -> dict[int, tuple[int, int]]:
    consts = {}
    for name, value in re.findall(r"^\s*const (\w+)\s*; \$([0-9A-Fa-f]+)",
                                  _source("constants/type_constants.asm"), re.M):
        consts[name] = int(value, 16)
    dex = {name: i + 1 for name, i in _constants(
        "constants/pokedex_constants.asm", r"^\s*const (DEX_\w+)").items()}
    result = {}
    for path in (PRET / "data" / "pokemon" / "base_stats").glob("*.asm"):
        src = path.read_text(encoding="utf-8")
        identity = re.search(r"^\s*db (DEX_\w+) ; pokedex id", src, re.M)
        types = re.search(r"^\s*db (\w+),\s*(\w+) ; type", src, re.M)
        assert identity and types, path
        result[dex[identity[1]]] = (consts[types[1]], consts[types[2]])
    assert sorted(result) == list(range(1, 152))
    return result


def _families(order: dict[int, int]) -> dict[int, int]:
    species_const = {}
    for line in _source("constants/pokemon_constants.asm").splitlines():
        match = re.match(r"\s*const (\w+)\s*; \$([0-9A-Fa-f]{2})\b", line)
        if match:
            species_const[match[1]] = int(match[2], 16)
    assert len(species_const) >= 151
    labels = {_norm(name): internal for name, internal in species_const.items()}
    parent = {dex: dex for dex in range(1, 152)}

    def find(value):
        while parent[value] != value:
            value = parent[value]
        return value

    src = _source("data/pokemon/evos_moves.asm")
    for block in re.finditer(r"^(\w+)EvosMoves:\s*\n(.*?)(?=^\w+EvosMoves:|\Z)",
                             src, re.M | re.S):
        source_idx = labels.get(_norm(block[1]))
        if not source_idx or not order.get(source_idx):
            continue
        evolution_section = block[2].split("db 0", 1)[0]
        for row in re.findall(r"^\s*db EVOLVE_\w+\s*,\s*(.+)$", evolution_section, re.M):
            target = row.split(",")[-1].strip()
            target_idx = species_const.get(target)
            assert target_idx is not None, (block[1], target)
            left, right = find(order[source_idx]), find(order[target_idx])
            parent[max(left, right)] = min(left, right)
    return {dex: find(dex) for dex in range(1, 152)}


def _maps() -> dict[str, int]:
    names = re.findall(r"^\s*map_const (\w+),", _source("constants/map_constants.asm"), re.M)
    assert len(names) > 200
    return {name: index for index, name in enumerate(names)}


def test_pret_species_dex_names_types_and_shipped_index():
    order = _dex_order()
    types = _types()
    names = re.findall(r'^\s*dname "([^"]+)"', _source("data/pokemon/names.asm"), re.M)
    assert len(names) == 190
    adapter = Gen1Adapter()
    shipped = {int(k): int(v) for k, v in _json("species_index.json")[
        "index_to_national"].items()}
    assert shipped == {k: v for k, v in order.items() if v}
    for internal, dex in order.items():
        assert gen1_codec.internal_to_natdex(internal) == dex
        assert adapter.to_national_dex(internal) == dex
        assert adapter.species_types(internal) == (types[dex] if dex else None)
        if dex:
            display = adapter.species_name(internal)
            assert _norm(display) == _norm(names[internal - 1]), (internal, display)
            for glyph in "♂♀":
                if glyph in names[internal - 1]:
                    assert glyph in display
        else:
            assert adapter.species_name(internal).startswith("#")
    assert adapter.to_national_dex(0) == 0
    assert adapter.to_national_dex(191) == 0
    assert adapter.species_types(0) is None


def test_pret_evolution_families_all_151_species():
    order = _dex_order()
    expected = _families(order)
    shipped = {int(k): int(v) for k, v in _json("evolutions.json")["family"].items()}
    assert shipped == expected
    adapter = Gen1Adapter()
    for internal, dex in order.items():
        # the representative comes back in the wire's id space (internal); holes are themselves
        want = gen1_codec.natdex_to_internal(expected[dex]) if dex else internal
        assert adapter.evo_family(internal) == want, (internal, dex)
    assert expected[106] != expected[107]  # no Tyrogue in pret Gen 1
    assert {expected[dex] for dex in (133, 134, 135, 136)} == {133}


def test_pret_items_every_named_id_and_machine_tail():
    constants = _source("constants/item_constants.asm")
    main = constants.split("DEF NUM_ITEMS", 1)[0]
    main_ids = re.findall(r"^\s*const (\w+)\s*; \$([0-9A-Fa-f]{2})\b", main, re.M)
    names = re.findall(r'^\s*li "([^"]+)"', _source("data/items/names.asm"), re.M)
    assert main_ids[0] == ("NO_ITEM", "00") and len(names) >= 83
    adapter = Gen1Adapter()
    for item_const, hex_id in main_ids[1:]:
        item_id = int(hex_id, 16)
        assert item_id < len(names) + 1
        pret_name = names[item_id - 1]
        if set(pret_name) == {"?"}:
            assert item_id not in ITEM_NAMES
            continue
        actual = adapter.item_name(item_id)
        assert item_id in ITEM_NAMES
        assert _norm(actual) == _norm(pret_name), (item_const, item_id, actual, pret_name)
    for kind, start, count in (("HM", 0xC4, 5), ("TM", 0xC9, 50)):
        lines = re.findall(rf"^\s*add_{kind.lower()} (\w+)\s*; \$([0-9A-Fa-f]{{2}})",
                           constants, re.M)
        assert len(lines) == count
        assert [int(value, 16) for _, value in lines] == list(range(start, start + count))
        for index, (move, value) in enumerate(lines, 1):
            assert adapter.item_name(int(value, 16)) == f"{kind}{index:02d}", move


def test_pret_all_165_moves_and_generated_names():
    src = _source("constants/move_constants.asm").split("DEF NUM_ATTACKS", 1)[0]
    constants = re.findall(r"^\s*const (\w+)\s*; [0-9A-Fa-f]{2}\b", src, re.M)
    names = re.findall(r'^\s*li "([^"]+)"', _source("data/moves/names.asm"), re.M)
    assert len(constants) == 166 and constants[0] == "NO_MOVE" and len(names) == 165
    shipped = _json("moves.json")["moves"]
    assert len(shipped) == 165
    adapter = Gen1Adapter()
    for number in range(1, 166):
        row = shipped[number - 1]
        assert row["id"] == number and row["internal_name"] == constants[number]
        assert _norm(row["name"]) == _norm(names[number - 1])
        assert adapter.move_name(number) == row["name"]
        data = adapter.move_data(number)
        assert data and data["name"] == row["name"] and data["pp"] == row["pp"]
    assert adapter.move_name(0) == "" and adapter.move_data(166) is None


def test_pret_all_trainer_classes_and_rival_ids():
    src = _source("constants/trainer_constants.asm")
    constants = re.findall(r"^\s*trainer_const (\w+)\s*; \$([0-9A-Fa-f]{2})",
                           src, re.M)
    names = re.findall(r'^\s*li "([^"]+)"', _source("data/trainers/names.asm"), re.M)
    assert len(constants) == 48 and len(names) == 47
    shipped = _json("trainers.json")["classes"]
    adapter = Gen1Adapter()
    for index, (const, hex_id) in enumerate(constants):
        trainer_id = 200 + int(hex_id, 16)
        assert trainer_id == 200 + index
        display = shipped[str(trainer_id)]
        name, cls = adapter.trainer_info(trainer_id)
        assert cls == display and (name or cls)
        if index:
            expected = names[index - 1]
            if const.startswith("RIVAL"):
                assert _norm(display) == "RIVAL"
            elif const == "UNUSED_JUGGLER":
                assert _norm(display) == "JUGGLER"
            elif const == "ROCKET":
                assert _norm(display).startswith("ROCKET")
            elif const == "FISHER":
                assert _norm(display).startswith("FISH")
            else:
                assert _norm(display) == _norm(expected), (const, display, expected)
    rival = {200 + int(hex_id, 16) for name, hex_id in constants if name.startswith("RIVAL")}
    assert adapter.rival_trainer_ids() == rival == {225, 242, 243}
    assert adapter.trainer_info(999) == ("", "")


def test_pret_map_ids_gifts_and_fixed_static_encounters():
    maps = _maps()
    area_map = _json("area_map.json")
    assert all(int(map_id) in maps.values() for map_id in area_map)
    adapter = Gen1Adapter()
    scripts = []
    for path in (PRET / "scripts").glob("*.asm"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*call (?:GivePokemon|AddPartyMon)\b", text, re.M):
            scripts.append(path)
    assert len(scripts) == 6  # seven call sites; FightingDojo has two
    for script in scripts:
        normalized = _norm(script.stem)
        candidates = [number for name, number in maps.items() if _norm(name) == normalized]
        assert len(candidates) == 1, script.name
        map_id = candidates[0]
        area_id = area_map.get(str(map_id), {}).get("area_id", f"gift_map_{map_id}")
        assert adapter.is_gift_area(area_id), (script.name, area_id)
    assert "call GivePokemon" in _source("engine/events/prize_menu.asm")
    prize_area = area_map[str(maps["GAME_CORNER_PRIZE_ROOM"])]["area_id"]
    assert adapter.is_gift_area(prize_area)
    for name in ("CELADON_MANSION_ROOF_HOUSE", "MT_MOON_POKECENTER", "SILPH_CO_7F"):
        assert adapter.is_fixed_species_gift(area_map[str(maps[name])]["area_id"])
    for name in ("OAKS_LAB", "FIGHTING_DOJO", "CINNABAR_LAB_FOSSIL_ROOM"):
        assert not adapter.is_fixed_species_gift(area_map[str(maps[name])]["area_id"])
    assert adapter.is_gift_area("gift_route_4") and not adapter.is_gift_area("route_4")

    order = _dex_order()
    consts = {}
    for symbol, hex_id in re.findall(r"^\s*const (\w+)\s*; \$([0-9A-Fa-f]{2})",
                                   _source("constants/pokemon_constants.asm"), re.M):
        consts[symbol] = int(hex_id, 16)
    fixed = {
        "Route12": "SNORLAX", "Route16": "SNORLAX", "PowerPlant": "ZAPDOS",
        "SeafoamIslandsB4F": "ARTICUNO", "VictoryRoad2F": "MOLTRES",
        "CeruleanCaveB1F": "MEWTWO", "PokemonTower6F": "MAROWAK",
    }
    for script, species in fixed.items():
        text = _source(f"scripts/{script}.asm")
        named = species if species != "MAROWAK" else "RESTLESS_SOUL"
        assert f"ld a, {named}" in text, script
        map_id = next(number for name, number in maps.items() if _norm(name) == _norm(script))
        area_id = f"static_{map_id}_{order[consts[species]]}"
        assert adapter.is_gift_area(area_id) and adapter.is_fixed_species_gift(area_id)
    power_objects = _source("data/maps/objects/PowerPlant.asm")
    for species in re.findall(r"object_event .*?,\s*(VOLTORB|ELECTRODE),\s*\d+", power_objects):
        area_id = f"static_{maps['POWER_PLANT']}_{order[consts[species]]}"
        assert adapter.is_gift_area(area_id) and adapter.is_fixed_species_gift(area_id)
    assert not adapter.is_gift_area("static_999_151")


def test_base_contract_arity_routing_and_wire_values():
    docs = (ROOT / "docs/protocol.md").read_text(encoding="utf-8")
    section = docs.split("## 7. Adapter contract", 1)[1].split("### 7.3", 1)[0]
    documented = set(re.findall(r"^\| `([a-z_]+)`", section, re.M))
    documented |= {"trainer_party", "trainer_brief", "move_data"}
    adapter = Gen1Adapter(rom_type="Red")
    for name in documented:
        assert hasattr(adapter, name), name
        base = getattr(GameRulesAdapter, name, None)
        if base is None:
            base = getattr(GamePresentationAdapter, name)
        actual = getattr(Gen1Adapter, name, None) or base
        if isinstance(base, property):
            assert isinstance(actual, property)
        else:
            assert len(inspect.signature(actual).parameters) == len(
                inspect.signature(base).parameters), name
    for rom_type in ("Red", "Blue", "Yellow", "red", "blue", "yellow", "red_ap", "blue_ap"):
        assert game_id_for_rom_type(rom_type) == "gen1_rby"
        assert get_adapter("gen1_rby", rom_type=rom_type).game_id == "gen1_rby"
    assert adapter.party_blob_size() == 66
    assert adapter.mons_per_box == 20 and adapter.memorial_box_index == 11
    assert adapter.stat_stage_labels() == ["ATK", "DEF", "SPD", "SPC", "", "ACC", "EVA"]
    assert adapter.status_token(0x08) == "PSN" and adapter.status_token(0x80) == ""
    assert adapter.gender_from_key("ABCD:1234:99", 153) == ""
    assert adapter.gender_symbol("female") == "" and not adapter.is_shiny("ABCD:1234:99")
    assert not adapter.supports_abilities() and adapter.supports_explode_mode()
    assert adapter.sprite_html(1, 0).count('class="mon-sprite"') == 1
    assert 'data-species="112"' in adapter.sprite_html(1)
    assert "/transparent/112.png" in adapter.sprite_src(1)
    assert adapter.sprite_src(31) == ""  # pret MissingNo hole
    assert Gen1Adapter(rom_type="Yellow").supports_info_panel() is False
    assert adapter.encounter_table("route_1")
    assert {variant: len(areas) for variant, areas in _json("encounter_tables.json").items()} == (
        {"red": 39, "blue": 39, "yellow": 39})


def test_encounter_panel_projects_pret_natdex_to_internal_species():
    adapter = Gen1Adapter(rom_type="red")
    source = _json("encounter_tables.json")["red"]["route_1"]
    shown = adapter.encounter_table("route_1")
    assert shown is not None
    for method, entries in source.items():
        for raw, projected in zip(entries, shown[method], strict=True):
            dex = raw["species_id"]
            assert projected["species_id"] == gen1_codec.natdex_to_internal(dex)
            assert projected["name"] == raw["name"]
            assert f'/transparent/{dex}.png' in adapter.sprite_src(projected["species_id"])

    route1 = _maps()["ROUTE_1"]
    wild = bytes([1] + [5, gen1_codec.natdex_to_internal(1)] * 10 + [0])
    payload = {"variant": "red", "wild": {str(route1): wild.hex()},
               "old_rod": "", "good_rod": "", "super_rod": {}}
    scanned = adapter.ingest_rom_content(payload)
    assert scanned and scanned["route_1"]["Grass"][0]["species_id"] == 1
    assert scanned["route_1"]["Grass"][0]["name"] == "Bulbasaur"
    adapter.use_rom_encounters(scanned)
    projected = adapter.encounter_table("route_1")
    assert projected and projected["Grass"][0]["species_id"] == (
        gen1_codec.natdex_to_internal(1))


def test_key_and_blob_validation_with_codec_random_records():
    adapter = Gen1Adapter()
    rng = random.Random(0xA7BD209F)
    for _ in range(2000):
        blob = bytes(rng.randrange(256) for _ in range(gen1_codec.PARTY_MON_SIZE))
        mon = gen1_codec.decode_party_mon(blob)
        key = gen1_codec.key(mon)
        assert adapter.is_valid_mon_key(key)
        assert adapter.parse_ot_id(key) == f"{mon['ot_id']:04X}"
        wrapped = blob + bytes(2 * gen1_codec.NAME_SIZE)
        assert adapter.validate_party_blob(wrapped) == (adapter.to_national_dex(mon["species"]) > 0)
    for bad in ("", "ABCD:1234", "abcd:1234:99", "ABCDE:1234:99", "ABCD:1234:9"):
        assert not adapter.is_valid_mon_key(bad) and adapter.parse_ot_id(bad) == ""
    assert not adapter.validate_party_blob("zz")
    assert not adapter.validate_party_blob(bytes(65))
