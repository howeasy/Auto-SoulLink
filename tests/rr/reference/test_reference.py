"""Pinned-ROM tests; inputs come from tests/rr/conftest.py, without defaults here."""
from __future__ import annotations

import json

import pytest

from tools.rr import reference as rr


@pytest.fixture(scope="module")
def rom(rr_rom_path):
    # Missing or changed required evidence is a failure, never a skip.
    data = rr_rom_path.read_bytes()
    rr.validate_rom(data)
    return data


@pytest.fixture(scope="module")
def artifacts(rom, rr_repo):
    return rr.build_artifacts(rom, rr.load_sources(rr_repo))


def parsed(artifacts, name):
    return json.loads(artifacts[name])


def test_actual_pinned_rom_and_all_anchor_checks(rom, artifacts):
    manifest = parsed(artifacts, "rr41_reference_manifest.json")
    assert manifest["rom"]["sha256"] == rr.BASE_SHA256
    assert len(manifest["anchors"]) == len(rr.ANCHORS)
    assert manifest["status"] == "baseline_only_not_release_approval"
    assert manifest["shiny"]["xor_threshold_exclusive"] == 8
    assert len(manifest["shiny"]["active_palette_compare_addresses"]) == 2


def test_altered_rom_is_rejected_in_memory(rom):
    changed = bytearray(rom)
    changed[0x100] ^= 1
    with pytest.raises(rr.ReferenceError, match="SHA-256 mismatch"):
        rr.build_artifacts(bytes(changed), {})


def test_truncated_rom_is_rejected(rom):
    with pytest.raises(rr.ReferenceError, match="Expected a"):
        rr.validate_rom(rom[:-1])


@pytest.mark.parametrize("species_id,ratio", [(147, 127), (246, 127), (303, 255), (468, 31)])
def test_playable_gender_examples(artifacts, species_id, ratio):
    records = parsed(artifacts, "rr41_species.json")["records"]
    assert records[species_id]["gender_ratio"] == ratio


@pytest.mark.parametrize("members", [(193, 522), (489, 490), (1113, 1114, 1115),
                                      (123, 1273), (1183, 1184, 1207)])
def test_permanent_evolution_examples_are_connected(artifacts, members):
    data = parsed(artifacts, "rr41_evolution_families.json")
    assert any(set(members) <= set(family["members"]) for family in data["families"])
    assert data["form_aliases"] == []
    assert all(1 <= edge["method_id"] < 0xFD for edge in data["permanent_edges"])


def test_placeholders_sentinels_and_missing_catalog_names_are_explicit(artifacts):
    data = parsed(artifacts, "rr41_species.json")
    assert data["records"][0]["classification"] == "none_sentinel"
    assert data["records"][412]["classification"] == "egg_sentinel"
    assert all(data["records"][sid]["classification"] == "zero_record_placeholder"
               for sid in range(252, 277))
    assert data["records"][1356]["rom_display_name"] == "Ursaluna"
    assert data["records"][1375]["rom_display_name"] == "Chillet"
    for row in data["records"]:
        if row["classification"] == "rom_named_record_missing_catalog":
            assert row["catalog_name"] is None and row["rom_display_name"]
    assert len(data["records"]) == 1376
    assert data["reviewed_rom_domain"]["last"] == 1375


def test_type_translation_preserves_rom_evidence(artifacts):
    records = parsed(artifacts, "rr41_species.json")["records"]
    assert records[35]["types_rom"] == [23, 23]
    assert records[35]["types_canonical"] == [18, 18]
    assert records[26]["types_canonical"] == [13, 0]


def test_extended_rom_targets_have_evolution_evidence_without_guessed_names(artifacts):
    data = parsed(artifacts, "rr41_evolution_families.json")
    assert not data["coverage_gaps"]
    for members in [(1132, 1363, 1371), (1176, 1369), (1361, 1362)]:
        assert any(set(members) <= set(row["members"]) for row in data["families"])
    assert data["form_aliases"] == []


def test_species_extent_has_independent_following_asset_and_sound_table_evidence(artifacts):
    manifest = parsed(artifacts, "rr41_reference_manifest.json")
    tables = manifest["tables"]
    assert tables["species_count_including_sentinels"] == 1376
    assert int(tables["base_stats_end_exclusive"], 16) - int(tables["base_stats_address"], 16) == 1376 * 28
    assert int(tables["species_names_end_exclusive"], 16) - int(tables["species_names_address"], 16) == 1376 * 11


def test_all_twenty_five_box_pointers_and_ranges(artifacts):
    boxes = parsed(artifacts, "rr41_compressed_boxes.json")
    assert boxes["box_count"] == 25
    assert [int(row["data_address"], 16) for row in boxes["boxes"]] == list(rr.EXPECTED_BOX_POINTERS)
    for row in boxes["boxes"]:
        assert int(row["end_address_exclusive"], 16) - int(row["data_address"], 16) == 1740


def test_mode_flags_and_default_admission_evidence(artifacts):
    modes = parsed(artifacts, "rr41_modes.json")
    flags = {row["name"]: row for row in modes["flags"]}
    assert flags["minimal_grinding"]["ram_byte"] == "0x0203B25A"
    assert flags["minimal_grinding"]["bit_mask"] == 4
    assert flags["restricted"]["ram_byte"] == "0x0203B25B"
    assert flags["restricted"]["bit_mask"] == 16
    assert modes["planned_mode_pairings"] == [[False, False], [True, True]]
    assert modes["runtime_values_observed"] is False


def test_cli_outputs_deterministic_across_directories_and_match_manifest(
    tmp_path, rr_repo, rr_rom_path,
):
    directories = [tmp_path / "one", tmp_path / "two"]
    for output in directories:
        assert rr.main(["--rom", str(rr_rom_path), "--repo", str(rr_repo),
                        "--output-dir", str(output)]) == 0
    first = {path.name: path.read_bytes() for path in directories[0].iterdir()}
    second = {path.name: path.read_bytes() for path in directories[1].iterdir()}
    assert first == second
    assert len(first) == 6
    manifest = json.loads(first["rr41_reference_manifest.json"])
    for item in manifest["files"]:
        assert rr.sha256(first[item["name"]]) == item["sha256"]
        assert len(first[item["name"]]) == item["size_bytes"]


def test_output_inside_repository_rejected_before_writing(
    artifacts, rr_repo, rr_rom_path,
):
    with pytest.raises(rr.ReferenceError, match="outside"):
        rr.write_artifacts(artifacts, rr_repo / "must-not-be-created", rr_repo, rr_rom_path)
