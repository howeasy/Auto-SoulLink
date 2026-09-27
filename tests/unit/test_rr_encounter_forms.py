"""Regional/form IDs must retain the RR species table's identity."""

import json
from pathlib import Path

import pytest

from tests.unit.test_rr_rom_encounters import load_pinned_rr_rom
from tools import gen_rr_encounters as gen, rr_rom_encounters as rr

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("constant,expected", [
    ("ZIGZAGOON_G", 1222), ("RATTATA_A", 1020), ("MEOWTH_G", 1208),
    ("FARFETCHD_G", 1213), ("MR_MIME_G", 1216), ("DECIDUEYE_H", 1301),
    ("NYMBLE_S", 1200), ("BURMY_SANDY", 707), ("TAUROS_P_WATER", 1235),
    ("ZIGZAGOON", 288), ("DEERLING_SUMMER", 738), ("NONE", 0),
])
def test_rr_form_constant_resolves_without_collapsing_to_base_species(constant, expected):
    names = gen._build_name_to_id(str(ROOT / "data/games/gen3_frlge/rr_species.json"))
    assert gen._resolve_species_id("SPECIES_" + constant, names) == expected


def test_unknown_form_is_a_named_failure_even_when_the_base_name_exists():
    with pytest.raises(ValueError, match="SPECIES_ZIGZAGOON_UNKNOWN_FORM"):
        gen._resolve_species_id("SPECIES_ZIGZAGOON_UNKNOWN_FORM", {"zigzagoon": 288})


@pytest.fixture(scope="module")
def rr_rom():
    return load_pinned_rr_rom()


@pytest.mark.parametrize("area", ["route_1", "route_2", "mt_moon", "berry_forest"])
def test_every_sample_area_method_species_matches_rr_rom_slots(rr_rom, area):
    decoded = rr.decode_encounters(rr_rom)
    area_map = json.loads((ROOT / "data/games/gen3_frlge/area_map.json").read_text())
    actual = rr.primary_area_slots(decoded, area_map)
    committed = json.loads((ROOT / "data/games/gen3_frlge/rr_encounters.json").read_text())
    assert area in actual
    assert set(committed[area]) == set(actual[area])
    for method, entries in committed[area].items():
        assert [(r["species_id"], r["min_level"], r["max_level"]) for r in entries] == [
            (r["species_id"], r["min_level"], r["max_level"]) for r in actual[area][method]
        ], (area, method)
