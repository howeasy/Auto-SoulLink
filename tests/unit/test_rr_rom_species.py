"""Missing RR species must be named from ROM records plus pinned display metadata."""

import json
from pathlib import Path

import pytest

from tests.unit.test_rr_rom_encounters import load_pinned_rr_rom

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def rom():
    return load_pinned_rr_rom()


def test_all_actual_wild_species_resolve_to_a_named_catalog_entry(rom):
    from tools.rr_rom_encounters import decode_encounters

    names = json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text())
    ids = {s["species_id"] for rows in decode_encounters(rom)["tables"].values()
           for h in rows for info in h["habitats"].values() for s in info["slots"]} - {0}
    assert {sid for sid in ids if str(sid) not in names} == set()
    assert names["1361"] == "Poltchageist"
    assert names["1371"] == "Hydrapple"


def test_tail_records_and_display_metadata_are_bound_to_actual_rom_stats(rom):
    from tools.rr_rom_species import extend_names, species_record

    names = {int(k):v for k,v in json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text()).items()}
    existing = {k:v for k,v in names.items() if k<=1355}
    proof = json.loads((ROOT / "data/gen3_rr_species_rom.json").read_text())
    metadata = {row["species_id"]:{"ID":row["species_id"],"key":row["display_name"],"stats":row["stats"]}
                for row in proof["added"]}
    regenerated, actual = extend_names(rom,existing,metadata)
    assert regenerated == names
    assert [r["species_id"] for r in actual["added"]] == list(range(1356,1376))
    assert species_record(rom,1361)["rom_name"] == "Polchageis"
    metadata[1361]["stats"] = [1]*6
    with pytest.raises(ValueError,match="1361.*display metadata"):
        extend_names(rom,existing,metadata)


def test_display_metadata_parser_never_executes_expressions():
    from tools.rr_rom_species import display_metadata

    assert display_metadata("{'species':{1:{'name':'x','flag':true,'empty':null}}}")[1]["flag"] is True
    with pytest.raises(ValueError,match="non-data expression"):
        display_metadata("{'species': __import__('os')}")


def test_production_species_types_exists_for_every_wild_species(rom):
    from server.pokemon_data import species_types
    from tools.rr_rom_encounters import decode_encounters

    ids = {s["species_id"] for rows in decode_encounters(rom)["tables"].values()
           for h in rows for info in h["habitats"].values() for s in info["slots"]} - {0}
    assert sorted(s for s in ids if species_types(s, is_rr=True) is None) == []


def test_every_rom_type_round_trips_through_the_explicit_canonical_conversion(rom):
    from server.pokemon_data import species_types, type_name
    from tools.gen_rr_types import RR_TO_CANONICAL_TYPE, types_from_rom
    from tools.rr_rom_species import species_record

    catalog = json.loads((ROOT / "data/games/gen3_frlge/rr_species.json").read_text())
    generated, _ = types_from_rom(rom, catalog)
    reverse = {v:k for k,v in RR_TO_CANONICAL_TYPE.items()}
    assert len(reverse) == len(RR_TO_CANONICAL_TYPE)
    seen = set()
    for sid,pair in generated.items():
        raw = species_record(rom,sid)["types"]
        seen.update(raw)
        assert [reverse[t] for t in pair] == raw
        assert species_types(sid,is_rr=True) == pair
        assert all(type_name(t) != "???" for t in pair)
    assert seen == set(range(18)) - {9} | {23}
    assert RR_TO_CANONICAL_TYPE[23] == 18 and type_name(18) == "Fairy"
    assert species_types(26, is_rr=False) == (13,13)
    assert species_types(26, is_rr=True) == (13,0)
    changed = bytearray(rom)
    at = species_record(rom,1361)["base_stats_address"] - 0x08000000 + 6
    changed[at] = 255
    with pytest.raises(ValueError,match="unmapped raw type 255"):
        types_from_rom(bytes(changed),catalog)
