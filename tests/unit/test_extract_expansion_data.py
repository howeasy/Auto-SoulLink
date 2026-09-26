"""X1 HEADER/CONTROL evidence, with no ROM/source dependency at collection time.

The expansion fixture is a deliberately artificial layout, NOT expansion ABI
evidence. Real expansion offsets remain the build probe's responsibility.
"""

import copy
import hashlib
import os
import sys
from pathlib import Path

import pytest

from tools import extract_expansion_data as ex


def control_inputs(rom_path, source):
    # Keep absence handling narrow: a present corrupt ROM/cache is never a skip.
    if not rom_path.exists():
        pytest.skip(f"Emerald ROM absent: {rom_path}")
    ex.require(hashlib.sha1(rom_path.read_bytes()).hexdigest() == ex.VANILLA_SHA1,
               f"Emerald ROM sha1 mismatch: {rom_path}")
    if not source.exists():
        pytest.skip(f"pokeemerald not cloned: {source}")
    ex.clean_source(source)
    return rom_path.read_bytes(), source


@pytest.fixture(scope="module")
def control():
    rom_path = Path(os.environ.get("SLINK_EMERALD_ROM", ex.ROOT / "Pokemon - Emerald Version (USA, Europe).gba"))
    source = Path(os.environ.get("SLINK_POKEEMERALD", ex.ROOT / ".cache/pret/pokeemerald"))
    data, source = control_inputs(rom_path, source)
    layout = ex.vanilla_layout(source, ex.ROOT / "data/gen3/pret/pokeemerald.sym")
    return data, layout, ex.charmap(source), source


def test_vanilla_control_all_source_tables(control):
    data, layout, chars, source = control
    pack = ex.extract(data, layout, chars)
    assert pack["counts"] == {"species": 412, "moves": 355, "items": 377, "abilities": 78}
    assert pack["rhh_header"] is None
    differences = ex.source_control(pack, source)
    assert all(not rows for rows in differences.values()), differences
    # Baby roots, branching families, and split Nincada evolution are useful anchors.
    assert pack["species"][25]["family"] == 172
    assert {pack["species"][i]["family"] for i in (133, 134, 135, 136, 196, 197)} == {133}
    assert pack["species"][302]["family"] == 301  # Ninjask -> Nincada
    assert pack["species"][303]["family"] == 301  # Shedinja -> Nincada


def test_vanilla_server_disagreements_are_explicit(control):
    data, layout, chars, _ = control
    report = ex.server_crosscheck(ex.extract(data, layout, chars))
    for key in ("species_names", "types", "national_dex", "abilities", "emerald_moves", "emerald_overlay_items"):
        assert report[key] == []
    assert report["families"] == [
        {"id": 113, "rom": 113, "server": 493}, {"id": 122, "rom": 122, "server": 492},
        {"id": 143, "rom": 143, "server": 499}, {"id": 185, "rom": 185, "server": 491},
        {"id": 226, "rom": 226, "server": 511}, {"id": 242, "rom": 113, "server": 493},
        {"id": 363, "rom": 363, "server": 459}, {"id": 411, "rom": 411, "server": 486},
    ]
    assert report["moves"] == [{"id": 267, "field": "accuracy", "rom": 95, "server": 0}]
    assert report["items"] == [{"id": 273, "rom": "{POKEBLOCK} CASE", "server": "Pokéblock Case"}]
    assert len(report["items_missing"]) == 70
    assert [row for row in report["items_missing"] if row["rom"] != "????????"] == [
        {"id": 375, "rom": "MAGMA EMBLEM"}, {"id": 376, "rom": "OLD SEA MAP"}]


@pytest.mark.parametrize("table,key", [("species", "baseHP"), ("species", "family"),
                                      ("species", "national_dex"), ("moves", "power"),
                                      ("items", "price"), ("abilities", "name")])
def test_control_oracle_detects_changed_output(control, table, key):
    data, layout, chars, source = control
    pack = ex.extract(data, layout, chars)
    pack[table][1][key] = "corrupt" if key == "name" else -1
    assert any(ex.source_control(pack, source).values())


def test_control_wrong_offsets_fail_against_source(control):
    data, layout, chars, source = control
    bad = copy.deepcopy(layout)
    bad["tables"]["species"]["fields"]["baseHP"]["offset"] = 1
    result = ex.source_control(ex.extract(data, bad, chars), source)
    assert result["species_stats"]


def test_absent_rom_skips_by_name(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="Emerald ROM absent"):
        control_inputs(tmp_path / "absent.gba", tmp_path)


def test_absent_source_skips_by_name(tmp_path, monkeypatch):
    rom = tmp_path / "exists.gba"
    rom.write_bytes(b"test ROM with accepted hash")
    monkeypatch.setattr(ex, "VANILLA_SHA1", hashlib.sha1(rom.read_bytes()).hexdigest())
    with pytest.raises(pytest.skip.Exception, match="pokeemerald not cloned"):
        control_inputs(rom, tmp_path / "absent-source")


@pytest.mark.parametrize("source_exists", [True, False])
def test_present_wrong_rom_fails_never_skips(tmp_path, source_exists):
    rom = tmp_path / "bad.gba"
    rom.write_bytes(b"wrong")
    with pytest.raises(ex.ExtractionError, match="sha1 mismatch"):
        control_inputs(rom, tmp_path if source_exists else tmp_path / "absent-source")


@pytest.mark.parametrize("commit,dirty,reason", [("bad", "", "wrong commit"),
                                                (ex.PRET_COMMIT, " M src/pokemon.c", "dirty")])
def test_present_wrong_source_fails_never_skips(tmp_path, monkeypatch, commit, dirty, reason):
    responses = iter((commit, dirty))
    monkeypatch.setattr(ex.subprocess, "check_output", lambda *args, **kwargs: next(responses))
    with pytest.raises(ex.ExtractionError, match=reason):
        ex.clean_source(tmp_path)


def synthetic_expansion():
    """Small ROM-shaped fixture; intentionally NOT any real compiler's layout."""
    rom = bytearray(0x1000)

    def put(offset, value, width=4):
        rom[offset:offset + width] = value.to_bytes(width, "little")

    put(0x100, 3)
    put(0x104, 2)
    rom[0x108:0x11F] = b"pokemon emerald version"
    for key, address in {"species": 0x500, "moves": 0x900, "items": 0xA00}.items():
        put(0x100 + ex.GF_POINTERS[key], ex.ROM_BASE + address)
    rhh = 0x2A0  # Exercise scanning, never assume RHH follows GF at 0x204.
    rom[rhh:rhh + 6] = b"RHHEXP"
    rom[rhh + 6:rhh + 10] = bytes([1, 17, 0, 1])
    for offset, count in ((10, 2), (12, 3), (14, 2), (20, 2)):
        put(rhh + offset, count, 2)
    put(rhh + 16, ex.ROM_BASE + 0xB00)
    put(rhh + 22, 6, 1)
    for i in range(3):
        pos = 0x500 + i * 40
        rom[pos:pos + 6] = bytes([30 + i] * 6)
        rom[pos + 6:pos + 8] = bytes([11, 12])
        put(pos + 8, 1, 2)
        put(pos + 14, 250 + i, 2)
        put(pos + 16, ex.ROM_BASE + 0xC00 if i == 1 else 0)
        rom[pos + 20:pos + 22] = b"\xBB\xFF"
    for i in range(2):
        pos = 0x900 + i * 24
        put(pos, ex.ROM_BASE + 0xD00)
        put(pos + 8, (300 << 7) | 12, 2)
        put(pos + 10, 95, 2)
        put(pos + 12, 20, 1)
        put(pos + 16, 0xD, 1)  # signed four-bit priority = -3
        put(0xA00 + i * 12, 70000)
        put(0xA04 + i * 12, ex.ROM_BASE + 0xD00)
        rom[0xB00 + i * 6:0xB02 + i * 6] = b"\xBC\xFF"
    rom[0xD00:0xD02] = b"\xBB\xFF"
    put(0xC00, 4, 2)
    put(0xC02, 30, 2)
    put(0xC04, 2, 2)
    put(0xC0C, 0xFFFF, 2)
    f = ex.field
    layout = {
        "schema": 1, "kind": "expansion", "rom_sha1": hashlib.sha1(rom).hexdigest(),
        "provenance": {"status": "SYNTHETIC - no real expansion offsets"},
        "counts": dict.fromkeys(("species", "moves", "items", "abilities"), 999),
        "tables": {
            "species": {"stride": 40, "name": {"offset": 20, "length": 5},
                        "fields": {**{key: f(i) for i, key in enumerate(ex.STAT_FIELDS)},
                                   "types": f(6, count=2), "abilities": f(8, 2, count=3),
                                   "national_dex": f(14, 2), "evolution_pointer": f(16, 4)}},
            "moves": {"stride": 24, "name": {"offset": 0, "length": 6, "pointer": True},
                      "fields": {"type": f(8, 2, bits=5), "power": f(8, 2, shift=7, bits=9),
                                 "accuracy": f(10, 2, bits=7), "pp": f(12), "priority": f(16, bits=4, signed=True)}},
            "items": {"stride": 12, "name": {"offset": 4, "length": 6, "pointer": True},
                      "fields": {"price": f(0, 4)}},
            "abilities": {"stride": 6, "name": {"offset": 0, "length": 6}, "fields": {}},
        },
        "evolutions": {"stride": 12, "max_entries": 4, "end_method": 0xFFFF, "ignored_methods": [],
                       "fields": {"method": f(0, 2), "param": f(2, 2), "target": f(4, 2)}},
    }
    return rom, layout, {b"\xBB": "A", b"\xBC": "B"}


def test_expansion_header_counts_pointers_bitfields_and_families():
    data, layout, chars = synthetic_expansion()
    pack = ex.extract(data, layout, chars)
    assert pack["counts"] == {"species": 3, "moves": 2, "items": 2, "abilities": 2}
    assert pack["rhh_header"]["offset"] == 0x2A0
    assert pack["species"][1]["evolutions"] == [{"method": 4, "param": 30, "target": 2}]
    assert [row["family"] for row in pack["species"]] == [0, 1, 1]
    assert pack["species"][2]["national_dex"] == 252
    assert pack["species"][0]["abilities"] == [1, 0, 0]
    assert pack["moves"][1] == {"id": 1, "name": "A", "type": 12, "power": 300, "accuracy": 95, "pp": 20, "priority": -3}
    assert pack["items"][1] == {"id": 1, "name": "A", "price": 70000}
    assert pack["abilities"][1]["name"] == "B"


@pytest.mark.parametrize("offset,replacement,reason", [
    (0x100, b"\x01", "GF version/language"),
    (0x104, b"\x01", "GF version/language"),
    (0x1BC, b"\0\0\0\x02", "not a ROM pointer"),
    (0x1CC, b"\xF8\x0F\0\x08", "range outside file"),
    (0x2A7, b"\x12", "unsupported RHH version"),
    (0x2AC, b"\0\0", "zero RHH count"),
    (0x2AC, b"\xFF\xFF", "range outside file"),
    (0x2B6, b"\x07", "item name bound"),
    (0x310, b"RHHEXP", "ambiguous RHH"),
    (0x514, b"\xBB" * 5, "lacks EOS"),
    (0x514, b"\xFC\xFF", "unknown/control glyph"),
    (0x900, b"\0" * 4, "not a ROM pointer"),
    (0xC04, b"\xFF\x7F", "invalid evolution target"),
    (0xC0C, b"\x04\0", "unterminated evolution list"),
])
def test_present_malformed_expansion_fails(offset, replacement, reason):
    data, layout, chars = synthetic_expansion()
    data[offset:offset + len(replacement)] = replacement
    layout["rom_sha1"] = hashlib.sha1(data).hexdigest()
    with pytest.raises(ex.ExtractionError, match=reason):
        ex.extract(data, layout, chars)


def test_wrong_layout_rom_binding_fails():
    data, layout, chars = synthetic_expansion()
    data[-1] ^= 1
    with pytest.raises(ex.ExtractionError, match="sha1 does not match"):
        ex.extract(data, layout, chars)


def test_expansion_layout_cannot_be_omitted_or_disguised_as_vanilla():
    data, layout, chars = synthetic_expansion()
    layout["kind"] = "vanilla"
    with pytest.raises(ex.ExtractionError, match="kind mismatch"):
        ex.extract(data, layout, chars)


def test_layout_missing_required_stat_fails():
    data, layout, chars = synthetic_expansion()
    del layout["tables"]["moves"]["fields"]["power"]
    with pytest.raises(ex.ExtractionError, match="missing required moves"):
        ex.extract(data, layout, chars)


def test_layout_field_overflow_fails():
    data, layout, chars = synthetic_expansion()
    layout["tables"]["moves"]["fields"]["power"]["shift"] = 8
    with pytest.raises(ex.ExtractionError, match="invalid numeric layout"):
        ex.extract(data, layout, chars)


def test_family_root_is_not_minimum_species_and_is_order_independent():
    rows = [{"id": i, "evolutions": []} for i in range(5)]
    rows[4]["evolutions"] = [{"method": 1, "target": 1}]
    rows[1]["evolutions"] = [{"method": 1, "target": 2}, {"method": 1, "target": 3}]
    ex.families(rows)
    assert [row["family"] for row in rows] == [0, 4, 4, 4, 4]


def test_family_ignores_configured_non_evolution_method():
    rows = [{"id": i, "evolutions": []} for i in range(3)]
    rows[1]["evolutions"] = [{"method": 99, "target": 2}]
    ex.families(rows, ignored_methods=[99])
    assert [row["family"] for row in rows] == [0, 1, 2]


def test_decode_multibyte_glyph_and_apostrophe():
    assert ex.decode_name(b"\x55\x56\x57\x58\x59\xB4\xFF", {
        b"\x55\x56\x57\x58\x59": "{POKEBLOCK}", b"\xB4": "'"}) == "{POKEBLOCK}'"


def test_synthetic_vanilla_without_rhh():
    data, layout, chars = synthetic_expansion()
    data[0x2A0:0x2B8] = bytes(24)
    data[0x1C0:0x1C4] = (ex.ROM_BASE + 0xB00).to_bytes(4, "little")
    data[0xC00:0xC30] = bytes(48)
    data[0xC0C:0xC12] = bytes([4, 0, 30, 0, 2, 0])
    data[0xE00:0xE04] = bytes([251, 0, 252, 0])
    layout.update(kind="vanilla", rom_sha1=hashlib.sha1(data).hexdigest(),
                  counts={"species": 3, "moves": 2, "items": 2, "abilities": 2},
                  national_dex={"address": ex.ROM_BASE + 0xE00})
    layout["evolutions"].update(address=ex.ROM_BASE + 0xC00, slots=1, end_method=0)
    pack = ex.extract(data, layout, chars)
    assert pack["rhh_header"] is None
    assert pack["kind"] == "vanilla"
    assert pack["counts"]["species"] == 3
    assert pack["species"][2]["national_dex"] == 252
    assert pack["species"][1]["evolutions"] == [{"method": 4, "param": 30, "target": 2}]
    assert pack["species"][2]["family"] == 1


def test_rhh_outside_preferred_window_and_duplicate_outside_window():
    data, layout, chars = synthetic_expansion()
    data[0xF00:0xF18] = data[0x2A0:0x2B8]
    data[0x2A0:0x2B8] = bytes(24)
    layout["rom_sha1"] = hashlib.sha1(data).hexdigest()
    assert ex.extract(data, layout, chars)["rhh_header"]["offset"] == 0xF00
    data[0xFA0:0xFA6] = b"RHHEXP"
    with pytest.raises(ex.ExtractionError, match="ambiguous RHH"):
        ex.parse_headers(ex.Rom(data))


def test_expansion_missing_rhh_is_named():
    data, layout, chars = synthetic_expansion()
    data[0x2A0:0x2A6] = bytes(6)
    layout["rom_sha1"] = hashlib.sha1(data).hexdigest()
    with pytest.raises(ex.ExtractionError, match="RHH header not found"):
        ex.extract(data, layout, chars)


def test_header_non_ascii_becomes_extraction_error():
    data, _, _ = synthetic_expansion()
    data[0x108] = 255
    with pytest.raises(ex.ExtractionError, match="UnicodeDecodeError"):
        ex.parse_headers(ex.Rom(data))


@pytest.mark.parametrize("bad_symbol", ["gSpeciesNames", "gMoveNames", "missing"])
def test_bad_symbol_geometry_is_extraction_error(tmp_path, monkeypatch, bad_symbol):
    monkeypatch.setattr(ex, "clean_source", lambda _: None)
    monkeypatch.setattr(ex, "Constants", lambda _: type("TinyConstants", (), {"value": lambda self, key: 1})())
    symbols = {"gSpeciesInfo": 28, "gBattleMoves": 12, "gItems": 44, "gAbilityNames": 2,
               "gSpeciesNames": 2, "gMoveNames": 2, "gEvolutionTable": 8, "sSpeciesToNationalPokedexNum": 0}
    if bad_symbol == "missing":
        del symbols["gSpeciesInfo"]
    else:
        symbols[bad_symbol] += 1
    path = tmp_path / "bad.sym"
    path.write_text("\n".join(f"08000500 g {size:08x} {name}" for name, size in symbols.items()))
    with pytest.raises(ex.ExtractionError, match="KeyError" if bad_symbol == "missing" else bad_symbol):
        ex.vanilla_layout(tmp_path, path)


def test_source_evolution_bad_index_is_extraction_error(tmp_path, monkeypatch):
    values = {"SPECIES_NONE": 0, "SPECIES_BAD": 3, "EVO_LEVEL": 4, "1": 1}
    monkeypatch.setattr(ex, "Constants", lambda _: type("TinyConstants", (), {"value": lambda self, key: values[key]})())
    files = {
        "src/data/text/species_names.h": '[SPECIES_NONE] = _("NONE"),',
        "src/data/pokemon/species_info.h": "#define OLD_UNOWN_SPECIES_INFO {0}\nconst struct X table[] = {[SPECIES_NONE] = {0}};",
        "src/pokemon.c": "static const u16 sSpeciesToNationalPokedexNum[] = {};",
        "src/data/pokemon/evolution.h": "[SPECIES_BAD] = {{EVO_LEVEL, 1, SPECIES_NONE}},",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    pack = {"counts": {"species": 1}, "species": [{"id": 0, "name": "NONE", "types": [0, 0],
            "abilities": [0, 0], "national_dex": 0, **dict.fromkeys(ex.STAT_FIELDS, 0)}]}
    with pytest.raises(ex.ExtractionError, match="IndexError"):
        ex.source_control(pack, tmp_path)


@pytest.mark.parametrize("flags,reason", [([], "--layout is required"), (["--check"], "--check only supports vanilla")])
def test_expansion_cli_refuses_before_source_or_extraction(tmp_path, monkeypatch, flags, reason):
    data, _, _ = synthetic_expansion()
    rom = tmp_path / "exp.gba"
    rom.write_bytes(data)
    monkeypatch.setattr(sys, "argv", ["extract", "--rom", str(rom), *flags])
    monkeypatch.setattr(ex, "extract", lambda *args: pytest.fail("extraction must not start"))
    monkeypatch.setattr(ex, "vanilla_layout", lambda *args: pytest.fail("vanilla source must not be read"))
    with pytest.raises(ex.ExtractionError, match=reason):
        ex.main()


def test_explicit_reserved_zero_record_cannot_hide_nonzero_data():
    data, layout, chars = synthetic_expansion()
    layout["tables"]["species"]["zero_records"] = [2]
    with pytest.raises(ex.ExtractionError, match="declared zero record has data"):
        ex.extract(data, layout, chars)
    data[0x550:0x578] = bytes(40)
    layout["rom_sha1"] = hashlib.sha1(data).hexdigest()
    pack = ex.extract(data, layout, chars)
    assert pack["species"][2]["name"] is None
    assert pack["species"][2]["reserved_zero_record"] is True
    assert pack["species"][2]["national_dex"] == 0
