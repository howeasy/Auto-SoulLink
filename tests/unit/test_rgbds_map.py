"""RGBDS v1.0.3 emitter forms and checked-in pureRGB map regression evidence."""

from pathlib import Path

import pytest

from tools.rgbds_map import parse_map

REPO = Path(__file__).resolve().parents[2]

# The emitter is gbdev/rgbds@307846b03ea89ee57bf75f179d5f8051175ac60d,
# src/link/output.cpp, writeMapBank/writeMapSymbols/writeMapSummary.
BASIC = '''SUMMARY:
    ROM0: 4 bytes used / 16380 free

ROM0 bank #0:
    SECTION: $0000-$0003 ($0004 bytes) ["header"]
             $0000 = Header
    EMPTY: $0004-$3fff ($3ffc bytes)
    TOTAL EMPTY: $3ffc bytes
'''


def test_allocations_and_candidates_have_half_open_integer_bounds():
    result = parse_map(BASIC)
    assert result["schema_version"] == 1
    assert result["sections"] == [
        {"type": "ROM0", "bank": 0, "start": 0, "end_exclusive": 4,
         "size": 4, "name": "header"}
    ]
    assert result["gaps"] == [
        {"type": "ROM0", "bank": 0, "start": 4, "end_exclusive": 0x4000,
         "size": 0x3FFC, "status": "CANDIDATE"}
    ]
    assert result["banks"] == [
        {"type": "ROM0", "bank": 0, "start": 0, "end_exclusive": 0x4000,
         "size": 0x4000, "used": 4, "free": 0x3FFC, "bounds_status": "KNOWN"}
    ]
    assert result["ownership"] == result["writer_exclusion"] == "UNKNOWN"
    assert result["persistence"] == "UNKNOWN"


@pytest.mark.parametrize("text", [
    "", "not a map", BASIC.replace("$0000-$0003", "$0003-$0000"),
    BASIC.replace("($0004 bytes)", "($0005 bytes)"),
    BASIC.replace("$0004-$3fff", "$0005-$3fff"),
    BASIC.replace("TOTAL EMPTY: $3ffc", "TOTAL EMPTY: $3ffb"),
    BASIC.replace("ROM0 bank #0", "ROM0 bank #1"),
    BASIC.replace("ROM0 bank #0", "BOGUS bank #0"),
    BASIC.replace("16380 free", "16379 free"),
    BASIC.replace("    TOTAL EMPTY: $3ffc bytes\n", ""),
    BASIC.replace("    EMPTY: $0004-$3fff ($3ffc bytes)\n", ""),
    BASIC.replace("SECTION:", "SECTION BROKEN:"),
    BASIC + "trailing garbage\n",
    BASIC + 'ROM0 bank #0:\n    EMPTY\n',
])
def test_rejects_malformed_or_inconsistent_map(text):
    with pytest.raises(ValueError):
        parse_map(text)


def test_refuses_overlapping_allocations_even_with_union_marker():
    text = '''WRAM0 bank #0:
    SECTION: $c000-$c003 ($0004 bytes) ["first"]
             $c000 = First
             ; Next union
    SECTION: $c002-$c005 ($0004 bytes) ["second"]
    EMPTY: $c006-$cfff ($0ffa bytes)
    TOTAL EMPTY: $0ff8 bytes
'''
    with pytest.raises(ValueError, match="overlap"):
        parse_map(text)


def test_union_and_fragment_symbol_pieces_share_one_allocation():
    text = '''WRAM0 bank #0:
    SECTION: $c000-$c003 ($0004 bytes) ["union"]
             $c000 = One
             ; Next union
             $c000 = Two
             ; Next fragment
             $c004 = End
    EMPTY: $c004-$cfff ($0ffc bytes)
    TOTAL EMPTY: $0ffc bytes
'''
    result = parse_map(text)
    assert len(result["sections"]) == 1
    assert result["banks"][0]["used"] == 4


def test_zero_size_inside_allocation_cannot_create_false_free_bytes():
    # writeMapBank resets prevEndAddr even for a zero-size section. Reproduce
    # its printed EMPTY overlap; only nonzero allocations establish occupancy.
    text = '''ROM0 bank #0:
    SECTION: $0000-$0003 ($0004 bytes) ["allocated"]
    SECTION: $0002 ($0000 bytes) ["label"]
    EMPTY: $0002-$3fff ($3ffe bytes)
    TOTAL EMPTY: $3ffc bytes
'''
    result = parse_map(text)
    assert result["sections"][1]["size"] == 0
    assert result["gaps"][0]["start"] == 4
    assert result["banks"][0]["free"] == 0x3FFC


def test_empty_bank_is_not_synthesized_for_absent_types():
    result = parse_map("VRAM bank #0:\n    EMPTY\n")
    assert len(result["banks"]) == len(result["gaps"]) == 1
    assert result["gaps"][0]["start"] == 0x8000
    assert result["gaps"][0]["end_exclusive"] == 0xA000


def test_empty_expandable_bank_needs_summary_to_resolve_mode():
    result = parse_map("ROM0 bank #0:\n    EMPTY\n")
    assert result["banks"][0]["bounds_status"] == "UNKNOWN"
    assert result["banks"][0]["end_exclusive"] is None
    assert result["gaps"] == []
    resolved = parse_map("SUMMARY:\n    ROM0: 0 bytes used / 32768 free\n"
                         "ROM0 bank #0:\n    EMPTY\n")
    assert resolved["gaps"][0]["end_exclusive"] == 0x8000


@pytest.mark.parametrize(("kind", "bank", "start", "end"), [
    ("ROM0", 0, 0x0000, 0x8000), ("ROMX", 1, 0x4000, 0x8000),
    ("VRAM", 1, 0x8000, 0xA000), ("SRAM", 3, 0xA000, 0xC000),
    ("WRAM0", 0, 0xC000, 0xE000), ("WRAMX", 7, 0xD000, 0xE000),
    ("OAM", 0, 0xFE00, 0xFEA0), ("HRAM", 0, 0xFF80, 0xFFFF),
])
def test_platform_bank_boundaries_and_full_banks(kind, bank, start, end):
    size = end - start
    text = (f'{kind} bank #{bank}:\n'
            f'    SECTION: ${start:04x}-${end - 1:04x} (${size:04x} bytes) ["full"]\n'
            '    TOTAL EMPTY: $0000 bytes\n')
    result = parse_map(text)
    assert result["gaps"] == []
    assert result["banks"][0]["end_exclusive"] == end
    assert result["banks"][0]["free"] == 0


def test_single_byte_hole_zero_size_end_label_and_escaped_section_name():
    text = r'''HRAM bank #0:
    SECTION: $ff80-$fffd ($007e bytes) ["quote\" slash\\ line\n tab\t return\r"]
    EMPTY: $fffe-$fffe ($0001 byte)
    SECTION: $ffff ($0000 bytes) ["end"]
    TOTAL EMPTY: $0001 byte
'''
    result = parse_map(text)
    assert result["sections"][0]["name"] == 'quote" slash\\ line\n tab\t return\r'
    assert result["sections"][1]["start"] == 0xFFFF
    assert result["gaps"][0]["size"] == 1


def test_empty_summary_is_valid_empty_link_output():
    assert parse_map("SUMMARY:\n")["banks"] == []


def test_pinned_upstream_map_file_fixture_rom0_excerpt():
    # Exact bank excerpt (whitespace normalized) from RGBDS's map-file fixture
    # at the source pin above, test/link/map-file/ref.out.map:9-15.
    text = r'''ROM0 bank #0:
    SECTION: $0000-$0000 ($0001 byte) ["rom0"]
             $0000 = Label0
             $0001 = Label0.local
    SECTION: $0001 ($0000 bytes) ["\n\r\t\"\\"]
    EMPTY: $0001-$3fff ($3fff bytes)
    TOTAL EMPTY: $3fff bytes
'''
    result = parse_map(text)
    assert result["sections"][1]["name"] == '\n\r\t"\\'
    assert result["banks"][0]["used"] == 1


def test_bank_block_order_does_not_change_result():
    other = "VRAM bank #0:\n    EMPTY\n"
    block = BASIC[BASIC.index("ROM0 bank"):]
    assert parse_map(block + other) == parse_map(other + block)


@pytest.mark.parametrize("text", [
    'HRAM bank #0:\n    SECTION: $ffff-$ffff ($0001 byte) ["past"]\n'
    '    TOTAL EMPTY: $007e bytes\n',
    'ROMX bank #0:\n    EMPTY\n',
    'WRAMX bank #8:\n    EMPTY\n',
    'VRAM bank #2:\n    EMPTY\n',
    'SRAM bank #256:\n    EMPTY\n',
    BASIC.replace('SECTION: $0000-$0003 ($0004 bytes)',
                  'SECTION: $0000 ($0004 bytes)'),
    BASIC.replace('SECTION: $0000-$0003 ($0004 bytes)',
                  'SECTION: $0000-$0000 ($0000 bytes)'),
    BASIC.replace('TOTAL EMPTY: $3ffc bytes', 'EMPTY'),
    BASIC.replace('16380 free', '16380 free in 2 banks'),
    BASIC.replace('header', r'bad\qescape'),
    'SUMMARY:\n    ROM0: 0 bytes used / 16384 free\n',
    'SUMMARY:\nROM0 bank #0:\n    EMPTY\n',
    'ROM0 bank #0:\n    EMPTY\n    $0000 = Orphan\n',
    'SUMMARY:\n    ROM0: 0 bytes used / 32768 free\n'
    '    ROMX: 0 bytes used / 16384 free in 1 bank\n'
    'ROM0 bank #0:\n    EMPTY\nROMX bank #1:\n    EMPTY\n',
])
def test_refuses_unsupported_bounds_and_structural_contradictions(text):
    with pytest.raises(ValueError):
        parse_map(text)


@pytest.mark.parametrize("name", [
    "pokered", "pokeblue", "pokegreen", "purered_slink", "pureblue_slink", "puregreen_slink",
])
def test_all_tracked_purergb_maps(name):
    # Required tracked files: do not silently skip a missing regression fixture.
    result = parse_map((REPO / "data" / "purergb" / f"{name}.map").read_text("utf-8"))
    assert result["sections"][0] == {
        "type": "ROM0", "bank": 0, "start": 0, "end_exclusive": 0, "size": 0, "name": "NULL",
    }
    stack = next(section for section in result["sections"] if section["name"] == "Stack")
    assert stack == {"type": "WRAMX", "bank": 1, "start": 0xDF00,
                     "end_exclusive": 0xE000, "size": 0x100, "name": "Stack"}
    # SLink's emitted allocation occupies 14 of the clean map's 22 spare bytes.
    start, size = (0xDEF8, 8) if name.endswith("_slink") else (0xDEEA, 0x16)
    assert {"type": "WRAMX", "bank": 1, "start": start,
            "end_exclusive": 0xDF00, "size": size, "status": "CANDIDATE"} in result["gaps"]
