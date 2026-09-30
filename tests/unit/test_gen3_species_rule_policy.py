"""RF-5: every SpeciesInfo byte has an explicit policy; gender is a shared rule."""
import json
from pathlib import Path

import pytest

from server import upr_gen3_write_domain as W, upr_pipeline
from server.adapters import gen3_rom_tables as R
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer
from tests.unit.test_gen3_rand_admission import client, hello
from tests.unit.test_gen3_rom_content_lua import symbols
from tests.unit.test_gen3_rom_ingest import _clean, _payload

ROOT = Path(__file__).resolve().parents[2]


def _facts():
    return json.loads((ROOT / "data/games/gen3_frlg/species_rules.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
@pytest.mark.parametrize("boundary", ("manager", "admission", "pairing"))
@pytest.mark.asyncio
async def test_changed_gender_ratio_is_refused_and_cannot_pair_clean(tmp_path, title, boundary):
    original = _clean(title)
    raw = bytearray(original)
    head = symbols(title, len(raw))["gSpeciesInfo"]["address"] - 0x08000000
    offset = head + 28 + 16  # pret pokemon.h: SpeciesInfo.genderRatio is 0x10, NOT friendship at 0x12
    assert raw[offset] == 31  # pinned Bulbasaur threshold
    raw[offset] = 127
    report = _payload(bytes(raw), title)
    if boundary == "manager":
        source, output = tmp_path / "clean.gba", tmp_path / "changed.gba"
        source.write_bytes(original)
        output.write_bytes(raw)
        with pytest.raises(upr_pipeline.UprPipelineError, match="gender ratios"):
            upr_pipeline._check_content_gen3(str(source), str(output))
    elif boundary == "pairing":
        assert Gen3Adapter.pairing_kind_for("rand", report) == "rand"
    else:
        server = SLinkServer(data_dir=str(tmp_path / "run"))
        async with client(server) as send:
            reply = await send(hello(title, "rand", rom_content=report))
        assert server.admission["a"]["state"] == "rejected"
        assert "gender ratios" in server.admission["a"]["reason"]
        assert reply["commands"] == [{"cmd": "noop", "refused": "admission"}]


def test_all_species_info_bytes_are_classified_and_drive_the_projection():
    rows = _facts()["bytes"]
    assert [r["offset"] for r in rows] == list(range(28))
    assert all(r["name"] and type(r["projected"]) is bool and "Ruling 31" in r["reason"] for r in rows)
    assert R.SPECIES_RULE_BYTES == tuple(r["offset"] for r in rows if r["projected"])
    assert R.SPECIES_RULE_BYTES == (0, 1, 2, 3, 4, 5, 6, 7, 16, 19, 22, 23)
    assert rows[16]["name"] == "genderRatio" and rows[18]["name"] == "friendship"
    assert {r["offset"] for r in rows if r["allowed_write_domains"]} == {8, 12, 13, 14, 15}


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_allowed_writes_respect_every_classified_species_byte(title):
    facts = _facts()
    base = facts["titles"][title]["species_info_address"] - R.ROM_BASE
    end = base + facts["titles"][title]["species_count"] * 28
    rows = facts["bytes"]
    for domain, components in W.load_model()["titles"][title]["domains"].items():
        if domain in W.FORBIDDEN_DOMAINS:
            continue
        for component in components:
            for start, stop in W._ranges([component]):
                for address in range(max(base, start), min(end, stop)):
                    offset = (address - base) % 28
                    row = rows[offset]
                    if row["projected"]:
                        # The only permitted overlap with fixed rules is the named fork baseline.
                        assert domain == "baseline", (domain, row)
                        assert (component.get("id") == "deoxys_stats" and offset < 6
                                or component.get("id") == "ability2_normalisation" and offset == 23)
                    else:
                        # Ruling 31 deliberately opens catchRate/items. All OTHER unprojected
                        # bytes must be disjoint from every allowed write-domain span.
                        assert domain in row["allowed_write_domains"], (domain, row)


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_ability_fill_domains_equal_the_original_empty_slots_for_writable_species(title):
    facts = _facts()
    base = facts["titles"][title]["species_info_address"] - R.ROM_BASE
    component, = [c for c in W.load_model()["titles"][title]["domains"]["baseline"]
                  if c.get("id") == "ability2_normalisation"]
    actual = {i - base for start, end in W._ranges([component]) for i in range(start, end)}
    # The fork's records loop starts at 1 (upr_gen3_write_domain.build_title), never SPECIES_NONE.
    expected = {species * 28 + 23 for species in R.FRLG_ZERO_SECOND_ABILITY_SPECIES if species != 0}
    assert actual == expected
    assert len(actual) == 283 and 23 not in actual and 0 in R.FRLG_ZERO_SECOND_ABILITY_SPECIES


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_allowed_output_keeps_gender_ratios_and_is_accepted_by_both_readers(tmp_path, title):
    from tests.unit.test_gen3_rom_ingest import _randomized

    clean, allowed = _clean(title), _randomized(title, "allowed")
    info = symbols(title, len(clean))["gSpeciesInfo"]
    base = info["address"] - R.ROM_BASE
    assert clean[base + 16:base + info["size"]:28] == allowed[base + 16:base + info["size"]:28]
    source, output = tmp_path / "clean.gba", tmp_path / "allowed.gba"
    source.write_bytes(clean)
    output.write_bytes(allowed)
    assert upr_pipeline._check_content_gen3(str(source), str(output))
    report = _payload(allowed, title)
    adapter = Gen3Adapter(rom_type=title, artifact_kind="rand")
    assert adapter.refused_rom_content(report, artifact_kind="rand") == ""
    assert adapter.ingest_rom_content(report)
