"""Reference helper/comparator tests requiring no cartridge or RR CLI options."""
from __future__ import annotations

import json

import pytest

from tools.rr import reference as rr


@pytest.mark.parametrize("address,size", [(rr.ROM_BASE - 1, 1), (rr.ROM_BASE, -1),
                                          (rr.ROM_BASE + 3, 2), (rr.ROM_BASE + 5, 0)])
def test_rom_region_bounds(address, size):
    with pytest.raises(rr.ReferenceError, match="out of bounds"):
        rr.read_region(b"1234", address, size)


def test_end_boundary_and_pointer_target_validation():
    assert rr.read_region(b"1234", rr.ROM_BASE + 4, 0) == b""
    with pytest.raises(rr.ReferenceError, match="Unexpected table pointer"):
        rr.read_pointer(b"\x00" * 8, rr.ROM_BASE, rr.ROM_BASE + 4, 4)


@pytest.mark.parametrize("species_id", [-1, 1376])
def test_species_reader_rejects_rows_outside_verified_tables(species_id):
    with pytest.raises(rr.ReferenceError, match="outside verified ROM table"):
        rr._species_record(b"", species_id, None)


def test_rom_name_decoder_preserves_unknown_bytes_and_does_not_expand_labels():
    assert rr.decode_rom_name(bytes.fromhex("c9dbd9e6e4e3e2ff")) == ("Ogerpon", [])
    assert rr.decode_rom_name(bytes.fromhex("bb01ff")) == ("A<01>", [1])


@pytest.fixture
def controlled_baseline(tmp_path):
    """A small intentionally wrong baseline, independent of future runtime fixes."""
    names = {26: "Raichu", 193: "Yanma", 303: "Shedinja", 312: "Masquerain",
             468: "Combee", 522: "Yanmega", 1355: "Catalog extent marker"}
    payloads = {
        "species_names": json.dumps(names),
        "baseline_python": (
            "GENDER_RATIO: dict[int, int] = {303: 127, 468: 254}\n"
            "EVO_FAMILY: dict[int, int] = {522: 522}\n"
            "raise RuntimeError('workspace code executed')\n"
        ),
        "baseline_types": json.dumps({
            26: [13, 13], 193: [6, 2], 303: [6, 7], 312: [11, 6],
            468: [6, 2], 522: [6, 2],
        }),
    }
    for key, value in payloads.items():
        destination = tmp_path / rr.SOURCE_PATHS[key]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(value, encoding="utf-8")
    sources = rr.load_sources(tmp_path)
    ratios = {303: 255, 468: 31}
    correct_types = {26: [13, 0], 193: [6, 2], 303: [6, 7], 312: [6, 11],
                     468: [6, 2], 522: [6, 2], 1355: [0, 2]}
    species = {"records": [
        {"species_id": sid, "catalog_name": name, "gender_ratio": ratios.get(sid, 127),
         "types_canonical": correct_types[sid]} for sid, name in names.items()
    ]}
    evolutions = {"permanent_edges": [
        {"source_species": 193, "target_species": 522, "method_id": 4,
         "parameter": 45, "auxiliary": 0, "slot": 0, "record_address": "0x00000000"},
    ]}
    return sources, species, evolutions


def test_source_reader_does_not_execute_workspace_python(controlled_baseline):
    result, _, _ = controlled_baseline
    assert result["gender"][468] == 254


def test_comparator_reports_controlled_mismatches(controlled_baseline):
    sources, species, evolutions = controlled_baseline
    report = rr.comparison_report(species, evolutions, sources)
    assert report["counts"] == {
        "named_species_compared": 7, "gender_mismatches": 2, "type_set_mismatches": 1,
        "type_order_only_mismatches": 1, "missing_baseline_types": 1,
        "evolution_rows_split_by_baseline_family": 1,
    }
    assert {row["species_id"] for row in report["gender_mismatches"]} == {303, 468}
    assert report["type_set_mismatches"][0]["species_id"] == 26
    assert report["type_order_only_mismatches"][0]["species_id"] == 312
    assert report["missing_baseline_types"][0]["species_id"] == 1355


def test_comparator_accepts_repaired_baseline(controlled_baseline):
    sources, species, evolutions = controlled_baseline
    for row in species["records"]:
        sid = row["species_id"]
        sources["gender"][sid] = row["gender_ratio"]
        sources["types"][sid] = row["types_canonical"]
    sources["families"][522] = 193
    report = rr.comparison_report(species, evolutions, sources)
    assert report["counts"]["named_species_compared"] == 7
    assert all(value == 0 for name, value in report["counts"].items()
               if name != "named_species_compared")


def test_explicit_documentation_output_allowed_but_runtime_paths_rejected(tmp_path):
    repository = tmp_path / "repo"
    output = repository / "docs" / "rr_reference" / "generated"
    rr.write_artifacts({"example.json": b"{}\n"}, output, repository, tmp_path / "input.gba")
    assert (output / "example.json").read_bytes() == b"{}\n"
    with pytest.raises(rr.ReferenceError, match="outside"):
        rr.write_artifacts({"example.json": b"{}\n"}, repository / "data", repository,
                           tmp_path / "input.gba")
