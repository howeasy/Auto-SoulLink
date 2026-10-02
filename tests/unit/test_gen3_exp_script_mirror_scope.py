"""EXP-SCRIPT-MIRROR-SCOPE: which command tables are actually mirrored at the expansion pin.

Measured at the pin (05acb5ba audit): gScriptCmdTable 231/231 entries are 0x0A-prefixed;
gBattleScriptingCommandsTable has 0/251 >= 0x0A000000; gSpecials has 1/621 (index 287,
GetPlayerFacingDirection). So only SCRIPT commands need the alias hook -- but the pack
mirrors every site, which is harmless (a uniform offset cannot collide) and blind to nothing.
This test is the tripwire for the case that WOULD matter: a config change that starts
mirroring gBattleScriptingCommandsTable would silently displace the faint and capture_wild
hooks (they are reached through that table) with no pack diff to notice.

The entry COUNTS are pinned too, so a table that grows fails loudly here instead of a prefix
check silently passing on the first N entries.

Two traps this file exists to not fall into again:
  * in Python `&` binds TIGHTER than `==`, so `p & 0xFF000000 == X` parses as
    `p & (0xFF000000 == X)` -- always false. Every mask below is parenthesised.
  * the OFFSET added to a ROM address is MIRROR (0x02000000); the resulting top byte is
    0x0A. Comparing against the offset itself matches nothing.
"""
import os
import struct
from pathlib import Path

import pytest

ARTIFACTS = Path(os.environ.get(
    "SLINK_EXPANSION_ARTIFACTS",
    Path(__file__).resolve().parents[2] / ".cache/expansion-output/reference"))
BASE = 0x08000000
MIRROR = 0x02000000
MIRROR_TOP = (BASE + MIRROR) & 0xFF000000
ENTRY_COUNTS = {"gScriptCmdTable": 231, "gBattleScriptingCommandsTable": 251, "gSpecials": 621}
MAX_MIRRORED = {"gScriptCmdTable": 231, "gBattleScriptingCommandsTable": 0, "gSpecials": 1}


@pytest.fixture(scope="module")
def rom_and_syms():
    gba, sym = ARTIFACTS / "pokeemerald.gba", ARTIFACTS / "pokeemerald.sym"
    if not (gba.is_file() and sym.is_file()):
        pytest.skip("reference expansion ROM absent")
    out = {}
    for line in sym.read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            out[parts[3]] = int(parts[0], 16)
    return gba.read_bytes(), out


def _ptrs(rom, syms, name):
    off = syms[name] - BASE
    n = ENTRY_COUNTS[name]
    return struct.unpack(f"<{n}I", rom[off:off + n * 4])


def _mirrored(ptrs):
    return [i for i, p in enumerate(ptrs) if (p & 0xFF000000) == MIRROR_TOP]


@pytest.mark.parametrize("name", sorted(ENTRY_COUNTS))
def test_only_the_documented_tables_are_mirrored(rom_and_syms, name):
    rom, syms = rom_and_syms
    mirrored = _mirrored(_ptrs(rom, syms, name))
    assert len(mirrored) == MAX_MIRRORED[name], (
        f"{name}: {len(mirrored)} mirrored entries, audit says {MAX_MIRRORED[name]} "
        f"({mirrored[:4]}); a config change here can blind a pinned site")


def test_the_battle_scripting_table_stays_unmirrored(rom_and_syms):
    """faint and capture_wild are reached through this table; a mirrored entry would move the
    handler to 0x0A and the 0x08-only hook would never fire again."""
    rom, syms = rom_and_syms
    ptrs = _ptrs(rom, syms, "gBattleScriptingCommandsTable")
    assert not _mirrored(ptrs)
    for fn in ("Cmd_tryfaintmon", "Cmd_givecaughtmon"):
        assert [p for p in ptrs if p == syms[fn] + 1], f"{fn} not in gBattleScriptingCommandsTable"


def test_the_specials_mirror_is_only_getplayerfacingdirection(rom_and_syms):
    rom, syms = rom_and_syms
    ptrs = _ptrs(rom, syms, "gSpecials")
    mirrored = _mirrored(ptrs)
    assert mirrored == [287], mirrored
    assert ptrs[287] == syms["GetPlayerFacingDirection"] + 1 + MIRROR


def test_every_script_command_is_mirrored(rom_and_syms):
    """The reason the alias hook exists at all: 231/231 script handlers run at 0x0A."""
    rom, syms = rom_and_syms
    assert len(_mirrored(_ptrs(rom, syms, "gScriptCmdTable"))) == 231