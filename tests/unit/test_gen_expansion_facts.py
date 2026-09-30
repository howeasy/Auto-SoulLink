"""X1 compiler-object falsifiers plus optional real reference-build checks."""

import copy
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tools import extract_expansion_data as ex, gen_expansion_facts as gen

PACK = ex.ROOT / "data/games/gen3_exp/28877d73"


def model_elf():
    """A tiny ELF32 object with real section/symbol encodings, no ARM execution."""
    values = {
        "x1_size__Demo": struct.pack("<I", 8),
        "x1_zero__Demo": bytes(8),
        "x1_field__Demo__value": struct.pack("<II", 0, 2),
        "x1_mask__Demo__flag": b"\0\0\0\x1c\0\0\0\0",
        "x1_const__COUNT": struct.pack("<I", 7),
    }
    strings, body, symbols = bytearray(b"\0"), bytearray(), bytearray(16)
    for name, raw in values.items():
        symbols += struct.pack("<IIIBBH", len(strings), len(body), len(raw), 1, 0, 1)
        strings += name.encode() + b"\0"
        body += raw
    data = bytearray(52) + body + symbols + strings
    while len(data) % 4:
        data.append(0)
    sections = len(data)
    headers = [
        (0,) * 10,
        (0, 1, 2, 0, 52, len(body), 0, 0, 4, 0),
        (0, 2, 0, 0, 52 + len(body), len(symbols), 3, 0, 4, 16),
        (0, 3, 0, 0, 52 + len(body) + len(symbols), len(strings), 0, 0, 1, 0),
    ]
    for header in headers:
        data += struct.pack("<10I", *header)
    struct.pack_into("<16sHHIIIIIHHHHHH", data, 0, b"\x7fELF\x01\x01\x01" + bytes(9),
                     1, 40, 1, 0, 0, sections, 0, 52, 0, 0, 40, 4, 0)
    return data, values


def test_elf_probe_values_and_bitfield_lane():
    data, expected = model_elf()
    symbols = gen.elf_symbols(data, "x1_")
    assert symbols == expected
    facts = gen.parse_probe(symbols)
    assert facts["constants"] == {"COUNT": 7}
    assert facts["structs"]["Demo"]["fields"] == {"value": {"offset": 0, "size": 2}}
    assert facts["structs"]["Demo"]["bitfields"]["flag"] == {
        "offset": 3, "width": 1, "shift": 2, "bits": 3, "mask": "0x1c",
        "initializer_sha256": gen.sha(expected["x1_mask__Demo__flag"]),
    }


@pytest.mark.parametrize("mutation,reason", [("machine", "expected ELF32"), ("truncated", "truncated ELF"),
                                            ("section", "section outside"), ("relocation", "relocations")])
def test_bad_elf_fails(mutation, reason):
    data, _ = model_elf()
    section_offset = struct.unpack_from("<I", data, 32)[0]
    if mutation == "machine":
        data[18] = 62
    elif mutation == "truncated":
        data = data[:20]
    elif mutation == "section":
        struct.pack_into("<I", data, section_offset + 40 + 16, len(data) + 1)
    else:
        struct.pack_into("<I", data, section_offset + 3 * 40 + 4, 9)
        struct.pack_into("<I", data, section_offset + 3 * 40 + 28, 1)
    with pytest.raises(ex.ExtractionError, match=reason):
        gen.elf_symbols(data, "x1_")


@pytest.mark.parametrize("raw,zero,reason", [(b"\0", b"\0", "empty"), (b"\x05", b"\0", "noncontiguous"),
                                          (b"\x01", b"\x01", "baseline"), (b"\xff" * 5, bytes(5), "lane")])
def test_bad_initializer_mask_fails(raw, zero, reason):
    with pytest.raises(ex.ExtractionError, match=reason):
        gen.mask_field(raw, zero)


def test_overlap_is_not_silently_admitted():
    _, values = model_elf()
    values["x1_mask__Demo__duplicate"] = values["x1_mask__Demo__flag"]
    with pytest.raises(ex.ExtractionError, match="overlapping"):
        gen.parse_probe(values)


def test_committed_facts_are_bound_to_current_probe_and_generator():
    facts = json.loads((PACK / "facts.json").read_text())
    layout = json.loads((PACK / "layout.json").read_text())
    provenance = facts["provenance"]
    assert provenance == layout["provenance"]
    assert provenance["compile"]["probe_sha256"] == gen.source_sha(ex.ROOT / "tools/expansion_offsets.c")
    assert provenance["generator_sha256"] == gen.source_sha(Path(gen.__file__))
    assert provenance["extractor_sha256"] == gen.source_sha(Path(ex.__file__))
    assert provenance["source_commit"] == gen.PIN
    assert layout["rom_sha1"] == "28877d733492299599f2b8fff50493109d72653c"
    assert "-mabi=apcs-gnu" in provenance["compile"]["flags"]["CFLAGS"]
    assert "-fshort-enums" not in provenance["compile"]["flags"]["CFLAGS"]
    assert all(row["compiler"] == row["independent"] for row in facts["symbol_checks"].values())
    assert facts["structs"]["PokemonStorage"]["fields"]["boxes"]["offset"] == 4
    assert facts["structs"]["BattlePokemon"]["size"] == 140
    perish = facts["structs"]["Volatiles"]["bitfields"]["perishSong"]
    timer = facts["structs"]["Volatiles"]["bitfields"]["perishSongTimer"]
    assert perish["bits"] == 1 and timer["bits"] == 2
    assert not (int(perish["mask"], 16) << (8 * perish["offset"])) & (
        int(timer["mask"], 16) << (8 * timer["offset"]))
    assert layout["tables"]["species"]["zero_records"] == [1435]


def test_committed_layout_regenerates_without_artifacts():
    facts = json.loads((PACK / "facts.json").read_text())
    layout = json.loads((PACK / "layout.json").read_text())
    assert gen.make_layout(facts, layout["rom_sha1"], facts["provenance"]) == layout
    changed_layout = copy.deepcopy(layout)
    changed_layout["tables"]["species"]["fields"]["baseHP"]["offset"] += 1
    assert gen.make_layout(facts, layout["rom_sha1"], facts["provenance"]) != changed_layout
    changed_facts = copy.deepcopy(facts)
    changed_facts["structs"]["MoveInfo"]["bitfields"]["power"]["shift"] += 1
    assert gen.make_layout(changed_facts, layout["rom_sha1"], facts["provenance"]) != layout


@pytest.mark.parametrize("target", ["layout", "facts"])
def test_layout_guard_rejects_mutated_committed_copy(tmp_path, monkeypatch, target):
    facts = json.loads((PACK / "facts.json").read_text())
    layout = json.loads((PACK / "layout.json").read_text())
    if target == "layout":
        layout["tables"]["species"]["fields"]["baseHP"]["offset"] += 1
    else:
        facts["structs"]["MoveInfo"]["bitfields"]["power"]["shift"] += 1
    (tmp_path / "facts.json").write_text(json.dumps(facts))
    (tmp_path / "layout.json").write_text(json.dumps(layout))
    monkeypatch.setattr(__import__(__name__, fromlist=["PACK"]), "PACK", tmp_path)
    with pytest.raises(AssertionError):
        test_committed_layout_regenerates_without_artifacts()


@pytest.fixture(scope="module")
def reference():
    artifacts = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ex.ROOT / ".cache/expansion-output/reference"))
    if not artifacts.exists():
        pytest.skip("no local reference build output present")  # Existing X0 skip fragment.
    return gen.read_artifacts(artifacts)


def test_reference_compiler_facts_match_rom_headers_sym_and_elf(reference):
    _, rom, symbols, elf = reference
    facts = json.loads((PACK / "facts.json").read_text())
    before = copy.deepcopy(facts["symbol_checks"])
    gen.crosscheck(facts, rom, symbols, elf)
    assert facts["symbol_checks"] == before


@pytest.mark.parametrize("kind", ["pokemon_size", "bag_size", "flags", "species_stride", "symbol"])
def test_wrong_probe_fact_or_symbol_fails_reference_checks(reference, kind):
    _, rom, symbols, elf = reference
    facts = json.loads((PACK / "facts.json").read_text())
    symbols = copy.deepcopy(symbols)
    if kind == "symbol":
        symbols["gParties"]["address"] += 4
    elif kind == "flags":
        facts["structs"]["SaveBlock1"]["fields"]["flags"]["offset"] += 1
    else:
        name = {"pokemon_size": "Pokemon", "bag_size": "Bag", "species_stride": "SpeciesInfo"}[kind]
        facts["structs"][name]["size"] += 4
    with pytest.raises(ex.ExtractionError, match="self-check|symbol/ELF"):
        gen.crosscheck(facts, rom, symbols, elf)


def test_reference_object_matches_generated_fields():
    obj = Path(os.environ.get("SLINK_EXPANSION_PROBE_OBJECT", ex.ROOT / ".cache/x1-probe/probe.o"))
    if not obj.exists():
        pytest.skip("no local reference build output present")
    facts = json.loads((PACK / "facts.json").read_text())
    raw = obj.read_bytes()
    assert gen.sha(raw) == facts["provenance"]["compile"]["object_sha256"]
    decoded = gen.parse_probe(gen.elf_symbols(raw, "x1_"))
    assert decoded["structs"] == facts["structs"]
    assert decoded["constants"] == facts["constants"]


def test_reference_extraction_counts_and_reserved_slot(reference):
    _, rom, _, _ = reference
    source = ex.ROOT / ".cache/expansion-src"
    if not source.exists():
        pytest.skip(f"pokeemerald not cloned: {source}")
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == gen.PIN
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True)
    layout = json.loads((PACK / "layout.json").read_text())
    pack = ex.extract(rom, layout, ex.charmap(source))
    assert pack["counts"] == {"species": 1573, "moves": 848, "items": 874, "abilities": 319}
    for table, count in pack["counts"].items():
        assert len(pack[table]) == pack["rhh_header"][table] == count
    assert pack["species"][292]["name"] == "Shedinja"
    assert pack["species"][292]["national_dex"] == 292
    assert pack["species"][1435]["reserved_zero_record"] is True
    assert pack["species"][1435]["name"] is None
    assert sum(len(row["evolutions"]) for row in pack["species"]) == 695
    facts = json.loads((PACK / "facts.json").read_text())
    assert hashlib.sha256(json.dumps(pack, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == facts["extraction"]["data_sha256"]
