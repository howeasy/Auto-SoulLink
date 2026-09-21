"""SOURCE pin checks and refusal controls; these are not emulator receipts."""
import copy
import json
from pathlib import Path

import pytest

from tools import gen_gen3_engine_signals as gen
from tools.pin_gen3_site import ROM_SPECS, find_offsets, load_rom, make_site, pattern_bytes


@pytest.fixture(scope="module")
def roms():
    return {name: load_rom(name) for name, spec in ROM_SPECS.items() if spec[3].is_file()}


@pytest.mark.parametrize("name", ROM_SPECS)
def test_pinned_sites_match_admitted_rom(name):
    path = ROM_SPECS[name][3]
    if not path.is_file():
        pytest.skip(f"ROM not present at {path}")
    rom = load_rom(name)
    document = json.loads(gen.output_path(ROM_SPECS[name][0]).read_text())
    row = document["titles"][ROM_SPECS[name][1]]["artifacts"][ROM_SPECS[name][2]]
    assert row["rom_sha1"] == ROM_SPECS[name][4]
    assert row["sites"], "empty pin table must not pass vacuously"
    resolved = {c["kind"]: gen.resolve(c, name, rom) for c in gen.CANDIDATES}
    assert set(row["sites"]) == {k for k, r in resolved.items() if r["status"] == "PINNED"}
    for kind, site in row["sites"].items():
        assert resolved[kind]["status"] == "PINNED"
        assert site == resolved[kind]["site"]
        assert site["address"] % 2 == site["capture_offset"] % 2 == 0
        data = bytes.fromhex(site["expected_hex"])
        assert 8 <= len(data) <= 16
        assert rom[site["rom_offset"]:site["rom_offset"] + len(data)] == data
        assert site["address"] == 0x08000000 + site["rom_offset"]
    assert "UNVERIFIED" not in json.dumps(document)


def test_search_includes_overlapping_occurrences():
    assert find_offsets(b"AAAAA", b"AAA") == [0, 1, 2]


def test_search_never_chooses_first_of_duplicate_hits():
    candidate = copy.deepcopy(gen.CANDIDATES[0])
    pattern = bytes.fromhex(candidate["patterns"]["fr"])
    result = gen.resolve(candidate, "fr", pattern + pattern)
    assert result["status"] == "UNVERIFIED"
    assert "site" not in result


def test_unknown_semantic_kind_never_emitted_even_if_bytes_exist():
    candidate = next(c for c in gen.CANDIDATES if c["kind"] == "evolve_species_store")
    result = gen.resolve(candidate, "fr", bytes(0xD0000))
    assert result["status"] == "UNVERIFIED"
    assert "site" not in result


def test_rr_retained_mon_given_tail_does_not_hide_entry_detour(roms):
    if "rr" not in roms:
        pytest.skip(f"ROM not present at {ROM_SPECS['rr'][3]}")
    candidate = next(c for c in gen.CANDIDATES if c["kind"] == "mon_given")
    assert len(find_offsets(roms["rr"], bytes.fromhex(candidate["pattern"]))) == 1
    result = gen.resolve(candidate, "rr", roms["rr"])
    assert result["status"] == "UNVERIFIED"
    assert "context" in result["reason"]


def test_wrong_anchor_and_thumb_bl_interior_refused():
    pattern = pattern_bytes("00F000F800BF00BF")
    with pytest.raises(ValueError, match="inside an instruction"):
        make_site(pattern, 0, pattern, capture_offset=2)
    with pytest.raises(ValueError, match="differs"):
        make_site(bytes(8), 0, pattern)
    with pytest.raises(ValueError, match="unaligned"):
        make_site(b"x" + pattern, 1, pattern)
    with pytest.raises(ValueError, match="8..16"):
        pattern_bytes("00")


def test_rom_identity_mismatch_is_not_a_skip(monkeypatch):
    monkeypatch.setattr(Path, "read_bytes", lambda self: bytes(16))
    with pytest.raises(ValueError, match="SHA-1"):
        load_rom("fr")


def test_unique_odd_match_cannot_be_promoted():
    candidate = copy.deepcopy(gen.CANDIDATES[0])
    pattern = bytes.fromhex(candidate["patterns"]["fr"])
    assert gen.resolve(candidate, "fr", b"x" + pattern)["status"] == "UNVERIFIED"
