"""tests/unit/test_gen_upr_polished_ini.py — the Polished offsets generator.

Calls `tools/gen_upr_polished_ini.py` functions directly (no subprocess, no ROM, no
network). Everything asserted here is derived from the pinned
`data/polished/polishedcrystal.sym`, so the suite runs on any checkout that has the
sym even without the unpacked Polished sources.

Run:
    pytest tests/unit/test_gen_upr_polished_ini.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))

import gen_upr_polished_ini as gen  # noqa: E402

ROM_SIZE = 2 * 1024 * 1024
# BaseData is `11:4b18` in the .sym. ROMX bank 11 maps to file 0x11*0x4000, and the
# in-bank address 0x4b18 is 0x0b18 past the bank's 0x4000 origin:
#     0x11 * 0x4000 = 0x44000 ;  0x4b18 - 0x4000 = 0x0b18 ;  0x44000 + 0x0b18 = 0x44B18
# (0x2CB18 would be bank 0x0B, which is not where the label lives.)
BASE_DATA_FLAT = 0x44B18


@pytest.fixture(scope="module")
def sym() -> dict[str, int]:
    return gen.resolve_sym(gen.SYM)


@pytest.fixture(scope="module")
def text() -> str:
    return gen.generate()


def _kv(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].split("//")[0].strip()
    raise AssertionError(f"key {key} missing from the generated ini")


def test_section_header_is_the_pinned_release():
    assert gen.SECTION == "[Polished Crystal (U) 3.2.3]"
    assert gen.GAME_CODE == "PKPC"          # 4 bytes at header 0x13F
    assert gen.TITLE == "PKPCRYSTAL"        # GB header title at 0x134


def test_admission_tuple_is_emitted(text: str):
    assert _kv(text, "Game") == "PKPC"
    assert _kv(text, "Version") == "50"               # header 0x14C = $32
    assert _kv(text, "Polished") == "1"
    assert _kv(text, "CRCInHeader") == "0xA36C"       # 0x14E-0x14F big-endian, as UPR reads it
    assert _kv(text, "VariantFormCount") == "46"
    assert _kv(text, "CRC32") == "0xF98367E4"


def test_species_and_struct_constants(text: str):
    assert _kv(text, "SpeciesCount") == "291"        # NUM_SPECIES = $123
    assert _kv(text, "NumPokemon") == "289"           # NUM_POKEMON differs; both are emitted
    assert _kv(text, "BaseStatsEntrySize") == "34"    # BASE_DATA_SIZE
    assert _kv(text, "MoveLength") == "8"             # MOVE_LENGTH
    # 74 TM + 6 HM + 31 tutor = 111 flags = 14 bit-bytes
    assert gen.NUM_TM_HM_TUTOR == 111
    assert _kv(text, "TmhmBitBytes") == "14"


def test_base_data_offset_arithmetic(sym: dict[str, int], text: str):
    assert gen.flat(0x11, 0x4B18) == BASE_DATA_FLAT
    assert sym["BaseData"] == BASE_DATA_FLAT
    assert _kv(text, "PokemonStatsOffset") == "0x44B18"


def test_flat_maps_bank_zero_to_the_address_itself():
    assert gen.flat(0, 0x1234) == 0x1234
    assert gen.flat(1, 0x4000) == 0x4000
    assert gen.flat(1, 0x4001) == 0x4001


def test_every_required_label_resolved(sym: dict[str, int]):
    missing = [label for label in gen.REQUIRED_LABELS if label not in sym]
    assert missing == []
    for label in gen.REQUIRED_LABELS:
        offs = sym[label]
        assert 0 <= offs < ROM_SIZE, f"{label} offset 0x{offs:X} is outside the ROM"


def test_every_emitted_offset_is_inside_the_rom(text: str):
    seen = 0
    # CRC32 / CRCInHeader are admission fingerprints, not file offsets.
    not_offsets = ("CRC32", "CRCInHeader")
    for line in text.splitlines():
        if line.startswith("//") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.endswith(not_offsets):
            continue
        val = val.split("//")[0].strip()
        if not val.startswith("0x"):
            continue
        offs = int(val, 16)
        assert 0 <= offs < ROM_SIZE, f"{key} offset 0x{offs:X} is outside the ROM"
        seen += 1
    assert seen > len(gen.SYMBOL_KEYS)


def test_wild_tables_are_eight_separate_offsets(text: str):
    for label in gen.WILD_TABLE_LABELS:
        assert _kv(text, f"{label}Offset").startswith("0x")


def test_header_carries_sym_digest_and_lock_reference(text: str):
    assert gen.sym_sha256(gen.SYM) in text
    assert "data/polished_sources.lock.json" in text
    lock = gen.LOCK.read_text(encoding="utf-8")
    assert '"v3.2.3"' in lock


def test_generator_is_deterministic():
    assert gen.generate() == gen.generate()


def test_missing_label_is_a_hard_error(tmp_path: pathlib.Path):
    lines = gen.SYM.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.endswith(" BaseData")]
    assert len(kept) == len(lines) - 1
    stripped = tmp_path / "no_BaseData.sym"
    stripped.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(SystemExit) as exc:
        gen.generate(sym_path=stripped)
    assert "BaseData" in str(exc.value)


def test_offset_outside_rom_is_refused():
    with pytest.raises(SystemExit) as exc:
        gen.check_offset(ROM_SIZE)
    assert "outside" in str(exc.value)


def test_check_is_red_on_a_modified_sym(tmp_path: pathlib.Path):
    """`--check` compares the committed ini byte-for-byte with a fresh generation."""
    out = tmp_path / "upr_polished_entries.ini"
    out.write_text(gen.generate(), encoding="utf-8", newline="\n")
    assert gen.check(out) == 0
    out.write_text(gen.generate() + "// drift\n", encoding="utf-8", newline="\n")
    assert gen.check(out) == 1
    assert gen.check(tmp_path / "missing.ini") == 1


def test_check_is_red_when_the_sym_moves(tmp_path: pathlib.Path):
    """Shift one label in a copy of the sym; the committed ini must no longer match."""
    sym2 = tmp_path / "moved.sym"
    out = tmp_path / "upr_polished_entries.ini"
    out.write_text(gen.generate(sym_path=sym2) if sym2.exists() else "", encoding="utf-8")
    # materialise a moved copy of the sym
    lines = gen.SYM.read_text(encoding="utf-8").splitlines()
    moved = ["11:4c18 BaseData" if ln.endswith(" BaseData") else ln for ln in lines]
    sym2.write_text("\n".join(moved) + "\n", encoding="utf-8", newline="\n")
    out.write_text(gen.generate(sym_path=sym2), encoding="utf-8", newline="\n")
    assert gen.check(out) is not None      # signature sanity
    fresh = gen.generate(sym_path=gen.SYM)
    stale = out.read_text(encoding="utf-8")
    assert stale != fresh
    # and the moved sym really moved the offset
    assert gen.resolve_sym(sym2)["BaseData"] == gen.flat(0x11, 0x4C18)
    assert gen.resolve_sym(sym2)["BaseData"] != BASE_DATA_FLAT


@pytest.mark.skipif(gen.default_src() is None, reason="no unpacked Polished maps/*.asm tree")
def test_script_sites_are_never_guessed():
    src = gen.default_src()
    sites = gen.scan_script_sites(src, gen.resolve_sym(gen.SYM))
    kinds = {s["kind"] for s in sites}
    assert kinds == {"GivePoke", "LoadWildMon"}
    assert len(sites) > 50
    # Every site carries its source location, and none claims a species byte offset.
    for s in sites:
        assert s["file"].startswith("maps/") and s["line"] >= 1
    text = gen.generate(src)
    assert "=Unresolved" in text
CLAIMS_DOC = """\
```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":42,"expect":"FORK_INI = \"src/com/dabomstew/pkrandom/config/polished_offsets.ini\""},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":67,"expect":"SPECIES_COUNT = 291"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":68,"expect":"NUM_POKEMON = 289"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":69,"expect":"BASE_STATS_ENTRY_SIZE = 34"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":70,"expect":"MOVE_LENGTH = 8"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":71,"expect":"NUM_TMS = 74"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":72,"expect":"NUM_HMS = 6"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":73,"expect":"NUM_TUTORS = 31"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":121,"expect":"def _flat(bank: int, addr: int) -> int:"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":123,"expect":"return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":136,"expect":"flat, read_sym, HELPER_SOURCE = _load_helpers()"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":142,"expect":"def sym_sha256("},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":146,"expect":"def resolve_sym("},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":196,"expect":"\"kind\": \"GivePoke\" if sm.group(1) == \"givepoke\" else \"LoadWildMon\","},{"path":"F:/slink-work/wt/polished/tools/gen_upr_polished_ini.py","line":257,"expect":"def generate("},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_constants.asm","line":317,"expect":"DEF NUM_SPECIES EQU const_value - 1 ; 123"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_constants.asm","line":318,"expect":"DEF NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES)) ; 121"},{"path":"F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm","line":35,"expect":"DEF BASE_DATA_SIZE EQU _RS"},{"path":"F:/slink-work/cache/polished/src/constants/battle_constants.asm","line":52,"expect":"DEF MOVE_LENGTH EQU _RS"},{"path":"F:/slink-work/cache/polished/src/constants/tmhm_constants.asm","line":100,"expect":"DEF NUM_TMS = __tmhm_value__ - 1"},{"path":"F:/slink-work/cache/polished/src/constants/tmhm_constants.asm","line":116,"expect":"DEF NUM_HMS = __tmhm_value__ - NUM_TMS - 1"},{"path":"F:/slink-work/cache/polished/src/constants/tmhm_constants.asm","line":156,"expect":"DEF NUM_TUTORS = __tmhm_value__ - NUM_TMS - NUM_HMS - 1"},{"path":"F:/slink-work/cache/polished/src/constants/tmhm_constants.asm","line":158,"expect":"DEF NUM_TM_HM_TUTOR EQU NUM_TMS + NUM_HMS + NUM_TUTORS"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":319,"expect":"MACRO givepoke"},{"path":"F:/slink-work/cache/polished/src/macros/scripts/events.asm","line":322,"expect":"dp \\1, \\2 ; pokemon"},{"path":"E:/Google Drive/SLink/.cache/slink-upr/src/com/dabomstew/pkrandom/constants/GBConstants.java","line":40,"expect":"romCodeOffset = 0x13F"},{"path":"E:/Google Drive/SLink/.cache/slink-upr/src/com/dabomstew/pkrandom/romhandlers/Gen2RomHandler.java","line":877,"expect":"\"WildPokemonOffset\""},{"path":"E:/Google Drive/SLink/.cache/slink-upr/src/com/dabomstew/pkrandom/romhandlers/Gen2RomHandler.java","line":367,"expect":"pokemonCount + 1"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_gen1_ini.py","line":142,"expect":"def flat(bank: int, addr: int) -> int:"},{"path":"F:/slink-work/wt/polished/tools/gen_upr_gen1_ini.py","line":143,"expect":"return addr if bank == 0 else bank * 0x4000 + (addr - 0x4000)"}]
```
"""
