"""RF-1 finding 2: permitted ability filling must not erase an existing ability."""
from __future__ import annotations

import pytest

from server import upr_pipeline
from server.adapters.gen3_frlge import ForbiddenRomTables, Gen3Adapter
from server.adapters.gen3_rom_tables import FRLG_ZERO_SECOND_ABILITY_SPECIES
from tests.unit.test_gen3_rom_content_lua import symbols
from tests.unit.test_gen3_rom_ingest import _clean, _payload


def changed_second_ability(title, species, value):
    raw = bytearray(_clean(title))
    base = symbols(title, len(raw))["gSpeciesInfo"]["address"] - 0x08000000
    raw[base + species * 28 + 23] = value
    return bytes(raw)


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_removing_vibravas_existing_second_ability_refuses_and_never_pairs_clean(title):
    # pret species_info.h: Vibrava has {LEVITATE, LEVITATE}, not {LEVITATE, NONE}.
    report = _payload(changed_second_ability(title, 333, 0), title)
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    with pytest.raises(ForbiddenRomTables, match="abilities"):
        adapter.ingest_rom_content(report)
    assert "abilities" in adapter.refused_rom_content(report, artifact_kind="rand")
    assert adapter.pairing_kind_for("rand", report) == "rand"


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_manager_refuses_erasing_an_existing_second_ability(title, tmp_path):
    source, output = tmp_path / "source.gba", tmp_path / "output.gba"
    source.write_bytes(_clean(title))
    output.write_bytes(changed_second_ability(title, 333, 0))
    with pytest.raises(upr_pipeline.UprPipelineError, match="abilities"):
        upr_pipeline._check_content_gen3(str(source), str(output))


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_normalization_mask_is_exactly_the_pinned_original_zero_slots(title):
    raw = _clean(title)
    head = symbols(title, len(raw))["gSpeciesInfo"]
    base = head["address"] - 0x08000000
    expected = {species for species in range(head["count"]) if raw[base + species * 28 + 23] == 0}
    assert expected == FRLG_ZERO_SECOND_ABILITY_SPECIES
    assert 333 not in expected  # Vibrava's original second LEVITATE must survive.


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_upr_filling_only_originally_empty_slots_remains_accepted(title, tmp_path):
    original = _clean(title)
    changed = bytearray(original)
    head = symbols(title, len(changed))["gSpeciesInfo"]
    base = head["address"] - 0x08000000
    edits = 0
    for species in range(head["count"]):
        at = base + species * 28
        if original[at + 23] == 0:
            changed[at + 23] = original[at + 22]
            edits += original[at + 22] != 0
    assert edits > 0, "positive control made no ability fills"
    report = _payload(bytes(changed), title)
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    assert adapter.refused_rom_content(report, artifact_kind="rand") == ""
    assert adapter.pairing_kind_for("rand", report) == "clean"
    assert adapter.ingest_rom_content(report)
    source, output = tmp_path / "source.gba", tmp_path / "output.gba"
    source.write_bytes(original)
    output.write_bytes(changed)
    assert upr_pipeline._check_content_gen3(str(source), str(output))
