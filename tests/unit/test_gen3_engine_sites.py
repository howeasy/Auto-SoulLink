"""SOURCE pin checks and refusal controls; these are not emulator receipts."""
import copy
import json
from pathlib import Path

import pytest

from tools import gen_gen3_engine_signals as gen
from tools.pin_gen3_site import ROM_SPECS, find_offsets, load_rom, make_site, pattern_bytes


def test_local_symbols_and_function_sizes_are_supported():
    from tools.pin_gen3_site import parse_symbols

    symbols = parse_symbols("080212ac l 000002f4 Cmd_tryfaintmon\n")
    assert symbols["Cmd_tryfaintmon"] == {"address": 0x080212AC, "size": 0x2F4, "line": 1}


def test_new_vanilla_sites_are_symbol_bounded_and_entry_checked():
    for name in ("fr", "lg"):
        path = ROM_SPECS[name][3]
        if not path.is_file():
            pytest.skip(f"ROM not present at {path}")
        rom = load_rom(name)
        for kind in ("faint", "capture_wild", "pc_deposit", "pc_withdraw", "pc_release",
                     "evolve_species_store", "trade_evolve_species_store", "trade_done", "poison_faint"):
            c = next(c for c in gen.CANDIDATES if c["kind"] == kind)
            result = gen.resolve(c, name, rom)
            assert result["status"] == "PINNED", (name, kind, result)
            site = result["site"]
            fn = site["function"]
            assert 0 <= fn["capture_offset"] < fn["size"]
            assert fn["capture_offset"] % 2 == 0
            assert fn["address"] + fn["capture_offset"] == site["address"] + site["capture_offset"]
            ctx = site["context"]
            assert rom[ctx["rom_offset"]:ctx["rom_offset"] + len(ctx["expected_hex"]) // 2].hex().upper() == ctx["expected_hex"]


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
    candidate = next(c for c in gen.CANDIDATES if c["kind"] == "nature_change")
    result = gen.resolve(candidate, "fr", bytes(0xD0000))
    assert result["status"] == "UNVERIFIED"
    assert "site" not in result


def test_duplicate_local_symbol_name_is_not_guessed():
    from tools.pin_gen3_site import parse_symbols

    assert "local_fn" not in parse_symbols(
        "08001000 l 00000020 local_fn\n08002000 l 00000020 local_fn\n")


def test_capture_beyond_symbol_extent_is_refused(roms):
    if "fr" not in roms:
        pytest.skip(f"ROM not present at {ROM_SPECS['fr'][3]}")
    c = copy.deepcopy(next(c for c in gen.CANDIDATES if c["kind"] == "faint"))
    c["capture"] = 0x10000
    result = gen.resolve(c, "fr", roms["fr"])
    assert result["status"] == "UNVERIFIED"
    assert "size" in result["reason"]


def test_leafgreen_uses_its_own_symbol_and_branch_bytes(roms):
    if "lg" not in roms:
        pytest.skip(f"ROM not present at {ROM_SPECS['lg'][3]}")
    c = next(c for c in gen.CANDIDATES if c["kind"] == "evolve_species_store")
    s = gen.resolve(c, "lg", roms["lg"])["site"]
    assert "pokeleafgreen.sym:" in s["function"]["symbol_source"]
    assert s["expected_hex"] == c["binding"]["anchors"]["lg"]
    assert s["expected_hex"] != c["binding"]["anchors"]["fr"]


def test_rr_retained_mon_given_tail_is_replaced_by_verified_detour(roms):
    if "rr" not in roms:
        pytest.skip(f"ROM not present at {ROM_SPECS['rr'][3]}")
    candidate = next(c for c in gen.CANDIDATES if c["kind"] == "mon_given")
    assert len(find_offsets(roms["rr"], bytes.fromhex(candidate["pattern"]))) == 1
    result = gen.resolve(candidate, "rr", roms["rr"])
    assert result["status"] == "PINNED"
    assert result["site"]["source"] == "cfru_detour"
    assert result["site"]["address"] != 0x08040B80


@pytest.mark.parametrize("name", ("rr", "rr_companion"))
def test_rr_body_pins_have_bound_estimates_and_decoded_trampolines(name):
    from tools.pin_gen3_site import decode_thumb_detour

    if not ROM_SPECS[name][3].is_file():
        pytest.skip(f"ROM not present at {ROM_SPECS[name][3]}")
    rom = load_rom(name)
    for kind in ("mon_given", "pc_move", "pc_withdraw", "pc_box_place", "faint", "capture_wild"):
        c = next(c for c in gen.CANDIDATES if c["kind"] == kind)
        result = gen.resolve(c, name, rom)
        assert result["status"] == "PINNED", result
        site = result["site"]
        body = site["rr_body"]
        pc = site["address"] + site["capture_offset"]
        assert body["address"] <= pc < body["address"] + body["extent_estimate"]
        if site["source"] == "cfru_detour":
            detour = decode_thumb_detour(rom, site["detour"]["address"])
            assert detour["target"] == body["address"]
        assert body["extent_evidence"]


@pytest.mark.parametrize("name", ("rr", "rr_companion"))
def test_rr_faint_and_capture_wild_repinned_off_the_replaced_opcode_table(name):
    """RR selects a replacement battle-script command table at 0x0903EF20; the vanilla
    Cmd_tryfaintmon/Cmd_givecaughtmon command bodies are dead on the selected dispatch
    (docs/gen3/research/rr_opcode_table_audit.md R4). The re-pinned rows must land on the
    live CFRU replacement bodies, not the old dead vanilla addresses."""
    if not ROM_SPECS[name][3].is_file():
        pytest.skip(f"ROM not present at {ROM_SPECS[name][3]}")
    rom = load_rom(name)

    faint = next(c for c in gen.CANDIDATES if c["kind"] == "faint")
    result = gen.resolve(faint, name, rom)
    assert result["status"] == "PINNED", result
    site = result["site"]
    assert site["address"] == 0x0909EED2
    assert site["capture_offset"] == 0
    assert site["rom_offset"] == 0x0109EED2
    assert site["expected_hex"] == "BCE638E00302C5510708E95107084A3D"
    assert site["address"] != 0x080213C8  # old vanilla capture is dead on the selected table

    capture_wild = next(c for c in gen.CANDIDATES if c["kind"] == "capture_wild")
    result = gen.resolve(capture_wild, name, rom)
    assert result["status"] == "PINNED", result
    site = result["site"]
    assert site["address"] == 0x0907DD80
    assert site["capture_offset"] == 8
    assert site["rom_offset"] == 0x0107DD80
    assert site["expected_hex"] == "5A532000FFF704FD374E002822D0374B"
    assert site["address"] != 0x0802D828  # old vanilla capture is dead on the selected table


@pytest.mark.parametrize("name", ("rr", "rr_companion"))
def test_rr_kinds_count_and_old_faint_address_absent_from_pack(name):
    document = json.loads(gen.output_path(ROM_SPECS[name][0]).read_text())
    row = document["titles"][ROM_SPECS[name][1]]["artifacts"][ROM_SPECS[name][2]]
    assert len(row["sites"]) == 19
    # compare EFFECTIVE hook addresses (address + capture_offset): the dead vanilla captures were
    # 0x080213C8 (tryfaintmon) and 0x0802D824 + 4 = 0x0802D828 (givecaughtmon) -- Codex cx-92870c43
    effective = {site["address"] + (site.get("capture_offset") or 0) for site in row["sites"].values()}
    assert 0x080213C8 not in effective
    assert 0x0802D828 not in effective
    assert row["sites"]["faint"]["address"] == 0x0909EED2
    assert row["sites"]["capture_wild"]["address"] == 0x0907DD80


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


def test_detour_decoder_rejects_wrong_register_or_non_thumb_target():
    from tools.pin_gen3_site import decode_thumb_detour

    rom = bytearray(64)
    rom[:8] = bytes.fromhex("0049084721000008")
    assert decode_thumb_detour(rom, 0x08000000)["target"] == 0x08000020
    rom[2:4] = bytes.fromhex("1047")
    with pytest.raises(ValueError, match="same-register"):
        decode_thumb_detour(rom, 0x08000000)
    rom[2:4] = bytes.fromhex("0847")
    rom[4] = 0x20
    with pytest.raises(ValueError, match="not Thumb"):
        decode_thumb_detour(rom, 0x08000000)


def test_changed_detour_literal_cannot_repin_to_another_body(roms):
    if "rr" not in roms:
        pytest.skip(f"ROM not present at {ROM_SPECS['rr'][3]}")
    rom = bytearray(roms["rr"])
    rom[0x40B18:0x40B1C] = (0x090B6E39).to_bytes(4, "little")
    c = next(c for c in gen.CANDIDATES if c["kind"] == "mon_given")
    result = gen.resolve(c, "rr", rom)
    assert result["status"] == "UNVERIFIED"
    assert "target differs" in result["reason"]


@pytest.mark.parametrize("name", ("rr", "rr_companion"))
def test_disabled_rr_poison_is_not_a_fabricated_hp_site(name):
    if not ROM_SPECS[name][3].is_file():
        pytest.skip(f"ROM not present at {ROM_SPECS[name][3]}")
    rom = load_rom(name)
    for kind in ("poison_faint", "poison_hp_before"):
        c = next(c for c in gen.CANDIDATES if c["kind"] == kind)
        result = gen.resolve(c, name, rom)
        assert result["status"] == "UNVERIFIED"
        assert "NO HP mutation" in result["reason"]
        assert result["detour"]["target"] == 0x090B20D4
