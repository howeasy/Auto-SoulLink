"""Regional/form IDs must retain the RR species table's identity."""

import json
import struct
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


@pytest.mark.parametrize("area", ["route_1", "route_2", "route_22", "route_8", "route_10", "route_24", "route_25", "mt_moon", "berry_forest"])
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


def test_every_shipped_slot_and_probability_has_its_own_rom_witness(rr_rom):
    catalog = json.loads((ROOT / "data/games/gen3_frlge/rr_encounters.json").read_text())
    proof = json.loads((ROOT / "data/gen3_rr_encounters_rom.json").read_text())
    names = json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text())
    rates = {"land": [20,20,10,10,10,10,5,5,4,4,1,1], "water": [60,30,5,4,1],
             "rock_smash": [60,30,5,4,1], "fishing": [70,30,60,20,20,40,40,15,4,1]}
    checked = 0
    witnessed = set()
    decoded = rr.decode_encounters(rr_rom)
    header_sets = {label:{r["address"] for r in rows} for label,rows in decoded["tables"].items()}
    for area, methods in catalog.items():
        assert set(methods) == set(proof["entries"][area])
        for method, rows in methods.items():
            evidence = proof["entries"][area][method]
            assert len(rows) == len(evidence)
            for entry, sources in zip(rows, evidence, strict=True):
                assert entry["species_id"] > 0 and str(entry["species_id"]) in names
                assert entry["name"] and sources
                for source in sources:
                    witnessed.add((source["period"],source["header_address"],source["habitat"],source["slot"]))
                    assert source["selected_from"] in (source["period"],"Fallback")
                    assert source["header_address"] in header_sets[source["selected_from"]]
                    minimum, maximum, sid = struct.unpack_from("<BBH", rr_rom, source["address"]-rr.BASE)
                    assert (entry["species_id"],entry["min_level"],entry["max_level"]) == (sid,minimum,maximum)
                    assert entry["rate"] == rates[source["habitat"]][source["slot"]]
                    assert source["address"] == source["slots_address"] + source["slot"]*4
                    info = source["info_address"]-rr.BASE
                    assert struct.unpack_from("<I",rr_rom,info+4)[0] == source["slots_address"]
                    assert rr_rom[info] == source["encounter_rate"]
                    group, num = rr_rom[source["header_address"]-rr.BASE:source["header_address"]-rr.BASE+2]
                    assert source["map"] == f"{group}:{num}"
                    offset = {"land":4,"water":8,"rock_smash":12,"fishing":16}[source["habitat"]]
                    assert struct.unpack_from("<I",rr_rom,source["header_address"]-rr.BASE+offset)[0] == source["info_address"]
                checked += 1
    assert checked == 3745
    assert proof["unmapped_maps"] == []
    assert rr.full_catalog_diff(rr_rom,rr.client_area_labels()[0],catalog)["mismatched_methods"] == 0
    # Independently enumerate raw header choices to catch an omitted map/slot,
    # not just internally consistent provenance for whatever was generated.
    expected = set()
    fallback = {}
    for h in decoded["tables"]["Fallback"]:
        fallback.setdefault((h["map_group"],h["map_num"]),[]).append(h)
    for period in ("Day","Night"):
        primary = {(h["map_group"],h["map_num"]):h for h in decoded["tables"][period]}
        for key in primary.keys() | fallback.keys():
            for older in fallback.get(key,[{}]):
                for kind,_,_ in rr.HABITATS:
                    current = primary.get(key,{})
                    info = current.get("habitats",{}).get(kind)
                    if info is None:
                        current,info = older,older.get("habitats",{}).get(kind)
                    if info is not None:
                        for slot in info["slots"]:
                            if slot["species_id"]:
                                expected.add((period,current["address"],kind,slot["slot"]))
    assert witnessed == expected


def test_time_specific_fishing_and_fine_location_keys_are_retained(rr_rom):
    catalog = json.loads((ROOT / "data/games/gen3_frlge/rr_encounters.json").read_text())
    beach = catalog["treasure_beach"]
    assert beach["Day Good Rod"] != beach["Night Good Rod"]
    assert "Good Rod" not in beach
    assert catalog["ss_anne_exterior"]["Surfing"]


def test_display_labels_cannot_change_rom_species_levels_or_rates(rr_rom):
    names = {int(k): v for k,v in json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text()).items()}
    areas, _ = rr.client_area_labels()
    original, _ = rr.build_catalog(rr_rom,areas,names)
    renamed, _ = rr.build_catalog(rr_rom,areas,names,{1222:"display-only"})
    for area,methods in original.items():
        for method,rows in methods.items():
            for a,b in zip(rows,renamed[area][method],strict=True):
                assert {k:v for k,v in a.items() if k!="name"} == {k:v for k,v in b.items() if k!="name"}
    assert any(r["name"]=="display-only" for r in renamed["route_1"]["Night"])
