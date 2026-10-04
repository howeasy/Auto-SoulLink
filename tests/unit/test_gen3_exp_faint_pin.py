"""The expansion faint site is SetValuesOnFaint+0x86, proven from the reference ROM.

The old pin was Cmd_tryfaintmon+0x8A, which the battle opcode reaches but the C
faint-block fallback does not, so a natural faint that never ran the opcode was
silent. One site inside SetValuesOnFaint covers both, because +0x86 is the join.
"""
import json
import os
import re
from pathlib import Path

import capstone
import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
TITLE = "emerald_expansion_28877d73"
ROM_BASE = 0x08000000
IMAGE_END = 0x200000          # the 0x08 image is file 0..0x200000 in this 32 MiB build

SYMBOL = "SetValuesOnFaint"
ADDRESS, SIZE = 0x080DF4A4, 0xD0
CAPTURE = 0x86
ANCHOR = 0x82
ANCHOR_HEX = "124BDA74F0BC01BC00470E4D6B78FF2B"
ROM_OFFSET = 0x000DF526
# The two BL call SITES (not targets) that reach SetValuesOnFaint in this build.
CALLERS = (0x080A5BDA, 0x080936FC)


def _art(name: str) -> Path:
    path = ART / name
    if not path.is_file():
        pytest.skip(f"expansion reference artifact absent: {path}")
    return path


def _rom() -> bytes:
    return _art("pokeemerald.gba").read_bytes()


def _bl_sites(rom: bytes):
    """(target, call_site) for every Thumb BL in the ROM's 0x08 image.

    Decoded with capstone rather than by hand: the Thumb-2 BL offset interleaves
    I1/I2 (hw2 bits 10/9) between imm10 and imm11, so a naive
    ((imm10 << 12) | (imm11 << 1)) lands two bytes off and silently loses a
    caller instead of failing.
    """
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    out = []
    for i in md.disasm(rom[:IMAGE_END], ROM_BASE):
        if i.mnemonic in ("bl", "blx"):
            out.append((int(i.op_str.lstrip("#"), 16), i.address))
    return out


def _disasm():
    rom = _rom()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    ins = list(md.disasm(rom[ADDRESS - ROM_BASE:ADDRESS - ROM_BASE + SIZE], ADDRESS))
    return {i.address - ADDRESS: i for i in ins}


def test_symbol_is_one_global_of_the_expected_size():
    rows = [re.match(r"^([0-9a-f]{8}) ([a-z]) ([0-9a-f]{8}) (\S+)$", line.strip())
            for line in _art("pokeemerald.sym").read_text().splitlines()]
    hit = [m for m in rows if m and m.group(4) == SYMBOL]
    assert len(hit) == 1, "symbol must be unique in the build's .sym"
    assert int(hit[0].group(1), 16) == ADDRESS
    assert hit[0].group(2) == "g"
    assert int(hit[0].group(3), 16) == SIZE


def test_capture_is_the_pop_that_both_branches_join():
    at = _disasm()
    pop = at[CAPTURE]
    assert pop.mnemonic == "pop"
    assert [r.strip() for r in pop.op_str.strip("{}").split(",")] == ["r4", "r5", "r6", "r7"]
    # the player branch falls through into it from the faint-counter store
    assert at[CAPTURE - 2].mnemonic == "strb"
    # the opponent branch rejoins it, and it is the ONLY branch target in the body
    target = ADDRESS + CAPTURE
    branches = [i for i in at.values()
                if i.mnemonic in ("b", "beq", "bne", "bge", "ble", "bgt", "blt")]
    rejoins = [i for i in branches if int(i.op_str.lstrip("#").strip(), 16) == target]
    assert len(rejoins) == 1, "exactly one branch rejoins the capture"


def test_battler_register_is_r4_at_the_capture():
    at = _disasm()
    assert at[0x002].mnemonic == "lsls" and at[0x002].op_str == "r4, r0, #0x18"
    assert at[0x004].mnemonic == "lsrs" and at[0x004].op_str == "r4, r4, #0x18"


def test_both_named_bl_call_sites_decode_and_target_the_faint_function():
    """The two call sites named in the pin's contract decode as BLs into SetValuesOnFaint.

    This pins the two named sites, not the ROM-wide "exactly two and no more"
    count: a whole-0x08-image capstone sweep is not reliable here (linear
    disassembly aborts on the first undecodable word, and skipping it in chunks
    would need per-chunk padding). That exhaustive fact is the coordinator's
    ROM-wide scan and is recorded in the contract prose.
    """
    rom = _rom()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    for site in CALLERS:
        off = site - ROM_BASE
        one = list(md.disasm(rom[off:off + 4], site))
        assert len(one) == 1 and one[0].mnemonic == "bl", f"no BL decoded at {site:#x}"
        assert int(one[0].op_str.lstrip("#"), 16) == ADDRESS, f"BL at {site:#x} misses"


def test_site_bytes_are_unique_and_match_the_pack():
    rom = _rom()
    base = ADDRESS - ROM_BASE
    assert rom[base + ANCHOR:base + ANCHOR + 16].hex().upper() == ANCHOR_HEX
    assert rom.count(bytes.fromhex(ANCHOR_HEX)) == 1
    pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
    site = pack["titles"][TITLE]["artifacts"]["clean"]["sites"]["faint"]
    assert site["function"]["symbol"] == SYMBOL
    assert site["function"]["size"] == SIZE
    assert site["function"]["anchor_offset"] == ANCHOR
    assert site["function"]["capture_offset"] == CAPTURE
    assert site["function"]["size_evidence"] == "verified_build_symbol"
    assert site["rom_offset"] == ROM_OFFSET
    assert site["capture_offset"] == CAPTURE - ANCHOR
    assert site["expected_hex"].upper() == ANCHOR_HEX   # the anchor; site["context"] holds the function-entry bytes


def test_the_old_tryfaintmon_pin_is_gone_from_the_expansion_binding():
    src = (ROOT / "tools/gen_gen3_engine_signals.py").read_text()
    expansion = src.split("EXPANSION_BINDINGS = {", 1)[1].split("\n}\n", 1)[0]
    assert '"faint": ("SetValuesOnFaint", 0x86' in expansion
    # the contract names both old call sites in prose; the pin itself must not
    assert '"faint": ("Cmd_tryfaintmon"' not in expansion, "vanilla BINDINGS keeps its own row"
    pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
    site = pack["titles"][TITLE]["artifacts"]["clean"]["sites"]["faint"]
    assert site["function"]["symbol"] == SYMBOL
