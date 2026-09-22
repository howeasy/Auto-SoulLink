"""Pinned source tables, discriminating title controls and refusal cases."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.gen2_source_data import load_context, rom_offset
from tools.gen_gen2_area_map import build_area_map, constants
from tools.gen_gen2_encounters import (
    build_encounters,
    build_source_tables,
    parse_fishing,
    parse_wild,
    threshold,
)


@pytest.fixture(scope="module")
def built():
    contexts = {title: load_context(title) for title in ("crystal", "gold", "silver")}
    return contexts, {title: build_encounters(ctx) for title, ctx in contexts.items()}


def test_every_family_and_floor_is_retained(built):
    _, packs = built
    for title, pack in packs.items():
        assert len(pack["wild"]["grass"]) == (279 if title == "crystal" else 285)
        assert len(pack["wild"]["water"]) == (62 if title == "crystal" else 63)
        assert len(pack["tree"]["headbutt_maps"]) == 34
        assert len(pack["tree"]["rock_smash_maps"]) == 4
        assert len(pack["fishing"]["groups"]) == 13
        assert len(pack["fishing"]["time_groups"]) == 22
        assert len(pack["roamers"]["maps"]) == 16
        assert len(pack["contest"]["slots"]) == 10
        assert {row["time"] for row in pack["wild"]["grass"]} == {"morning", "day", "night"}
        assert all(len(row["slots"]) == 7 for row in pack["wild"]["grass"])
        assert all(len(row["slots"]) == 3 for row in pack["wild"]["water"])


def test_independent_rom_reader_matches_source_derived_families(built):
    # Leaf import avoids activating the legacy adapter registry. Share only the
    # public normalized contract; the production reader never parses this ASM.
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("independent_gen2_scan", root / "server/adapters/gen2_rom_scan.py")
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    contexts, packs = built
    for title, context in contexts.items():
        selected = json.loads((root / f"data/games/gen2_{title}/profile.json").read_text("utf-8"))["titles"][title]
        decoded = scanner.Rom(context.rom, selected)
        for family in ("wild", "tree", "fishing", "roamers"):
            assert getattr(decoded, family)() == packs[title][family], (title, family)


def test_real_gold_silver_controls_disagree_without_changing_area_identity(built):
    _, packs = built
    gold, silver = packs["gold"], packs["silver"]
    assert gold["map_areas"] == silver["map_areas"]
    assert gold["wild"]["grass"] != silver["wild"]["grass"]
    assert gold["wild"]["water"] != silver["wild"]["water"]
    assert gold["tree"]["sets"] != silver["tree"]["sets"]
    assert gold["fishing"] == silver["fishing"]


def test_roamer_and_contest_and_hatch_policy_never_claims_acquisition(built):
    _, packs = built
    assert [row["species"] for row in packs["crystal"]["roamers"]["initial"]] == [243, 244]
    for title in ("gold", "silver"):
        assert [row["species"] for row in packs[title]["roamers"]["initial"]] == [243, 244, 245]
    for pack in packs.values():
        assert pack["contest"]["area_id"] == "national_park_contest"
        assert pack["policy"]["roamer_consumes_ordinary_area"] is False
        assert pack["policy"]["roamer_area"] == "legend_<species>"
        assert pack["policy"]["egg_hatch_area"] == "gift_daycare"
        assert pack["policy"]["acquisition_events"] == "NOT_ESTABLISHED_BY_TABLES"


def test_crystal_source_empty_water_swarm_is_distinct_from_missing_table(built):
    contexts, packs = built
    assert not any(row["table"] == "SwarmWaterWildMons" for row in packs["crystal"]["wild"]["water"])
    ctx = contexts["crystal"]
    fake = SimpleNamespace(title="crystal", read_source=lambda _: "SwarmWaterWildMons:\n")
    with pytest.raises(ValueError, match="incomplete table"):
        parse_wild(fake, "swarm_water", "water", {}, {})
    at = rom_offset(*ctx.symbol("SwarmWaterWildMons"))
    assert ctx.rom[at] == 255


def test_fishing_aliases_and_time_references_are_retained(built):
    _, packs = built
    for pack in packs.values():
        groups = pack["fishing"]["groups"]
        assert groups[10]["old"] == groups[12]["old"]
        assert groups[0]["good"][-1] == {"threshold": 255, "species": 0, "level": 0}
        assert pack["fishing"]["time_groups"][0] == {
            "group_id": 0, "day": {"species": 222, "level": 20},
            "night": {"species": 120, "level": 20},
        }


def test_rom_disagreement_refuses_even_when_source_is_valid(built):
    contexts, _ = built
    ctx = contexts["gold"]
    rom = bytearray(ctx.rom)
    rom[rom_offset(*ctx.symbol("JohtoGrassWildMons")) + 5] ^= 1
    with pytest.raises(ValueError, match="source disagrees with ROM"):
        build_source_tables(replace(ctx, rom=bytes(rom)))


@pytest.mark.parametrize("body", [
    "db 2 percent\ndb 3, UNKNOWN\ndb 3, RATTATA\ndb 3, RATTATA\nend_water_wildmons\ndb -1",
    "db 2 percent\ndb 101, RATTATA\ndb 3, RATTATA\ndb 3, RATTATA\nend_water_wildmons\ndb -1",
    "db 2 percent\ndb 3, RATTATA\nend_water_wildmons\ndb -1",
    "db 2 percent\ndb 3, RATTATA\ndb 3, RATTATA\ndb 3, RATTATA\nend_water_wildmons",
])
def test_unknown_species_invalid_level_and_truncation_refuse(body):
    fake = SimpleNamespace(title="gold", read_source=lambda _: "Test:\ndef_water_wildmons ROUTE_29\n" + body)
    with pytest.raises(ValueError):
        parse_wild(fake, "test", "water", {"ROUTE_29": {"map_group": 24, "map_number": 3}}, {"RATTATA": 19})


def test_missing_map_name_is_not_silently_dropped():
    fake = SimpleNamespace(title="gold", read_source=lambda _: (
        "Test:\ndef_water_wildmons MISSING\ndb 2 percent\n"
        "db 3, RATTATA\ndb 3, RATTATA\ndb 3, RATTATA\nend_water_wildmons\ndb -1"))
    with pytest.raises(ValueError, match="unknown map name"):
        parse_wild(fake, "test", "water", {}, {"RATTATA": 19})


def test_unknown_fishing_time_group_refuses(built):
    contexts, _ = built
    ctx = contexts["crystal"]
    species_source = ctx.read_source("constants/pokemon_constants.asm").split("DEF NUM_POKEMON", 1)[0]
    species = constants(species_source, "", ctx.title)
    fake = SimpleNamespace(**vars(ctx), symbol=ctx.symbol)
    fake.read_source = lambda path: ctx.read_source(path).replace("time_group 0", "time_group 255")
    with pytest.raises(ValueError, match="invalid fishing thresholds/time reference"):
        parse_fishing(fake, species)


def test_periods_share_their_source_map_area(built):
    contexts, packs = built
    for title, ctx in contexts.items():
        areas = build_area_map(ctx)
        for row in packs[title]["wild"]["grass"]:
            composite = str(row["map_group"] * 256 + row["map_number"])
            assert packs[title]["map_areas"][composite] == areas[composite]["area_id"]


@pytest.mark.parametrize(("text", "expected"), [("2 percent", 5), ("50 percent + 1", 128), ("100 percent", 255)])
def test_byte_threshold_rounding(text, expected):
    assert threshold(text) == expected


@pytest.mark.parametrize("text", ["101 percent", "100 percent + 1", "-1 percent", "whatever"])
def test_bad_threshold_refuses(text):
    with pytest.raises(ValueError):
        threshold(text)
