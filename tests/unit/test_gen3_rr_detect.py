"""The shipped Gen 3 detector must not call a vanilla FRLG ROM Radical Red.

Regression: ``gen3_frlge.detect_variant()`` returned ``radical_red`` for vanilla FireRed.  The
version string at ROM 0x108 is present in vanilla FRLG too (it is the GBA header name), and the
only ROM-side probe accepted the whole ``0x08000000..0x08FFFFFF`` range - which vanilla satisfies,
because the word at ROM 0x1BC is that build's own ``gBaseStats`` pointer (FR 0x08254784,
LG 0x08254760).  Observed live as ``[probe] variant=radical_red game_id=gen3_frlge`` in
``docs/gen3/probes/census_fr_overworld_2026-09-21.txt:1``.

``radical_red`` now requires the ROM-only CFRU signature: that word landing in the expanded half
of the image (``0x09000000..0x0A000000``; RR clean and companion both 0x097B98EC).

The detector is driven directly - no emulator, no client.  RAM/ROM reads go through a fake
``memory``; where a real dump is on this host its bytes are used, otherwise the case is skipped.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

lupa = pytest.importorskip("lupa")

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "lua/games/gen3_frlge.lua").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_write_checkpoint as G  # noqa: E402  (the ROM pins live there)

ROM_BASE = 0x08000000
CFRU_PTR_ADDR = 0x080001BC          # the RR profile's gBaseStats pointer word
WORD_OFF = CFRU_PTR_ADDR - ROM_BASE
VERSION_STR_OFF = 0x108             # the detector reads 32 bytes here
VERSION_STR = b"pokemon red version\x00"

# ROM words read from the four admitted dumps (tests/unit/test_gen3_rr_detect.py::test_real_*).
VANILLA_WORDS = {"firered": 0x08254784, "leafgreen": 0x08254760}
CFRU_WORD = 0x097B98EC
CFRU_MIN, CFRU_MAX = 0x09000000, 0x0A000000

AP_SB1_PTR, VANILLA_SB1_PTR, RR_SB1_PTR = 0x03004F58, 0x03005008, 0x03003840
AP_SB1, VANILLA_SB1, RR_SB1 = 0x02010000, 0x02020000, 0x02030000


def le(addr: int, value: int, width: int) -> dict[int, int]:
    return {addr + i: (value >> (8 * i)) & 0xFF for i in range(width)}


def sb1(ptr_addr: int, target: int, map_group: int = 3, map_num: int = 19) -> dict[int, int]:
    """A SaveBlock1 pointer plus the fields `_validateSB1Ptr` reads through it."""
    out = le(ptr_addr, target, 4)
    out[target + 0x04] = map_group
    out[target + 0x05] = map_num
    return out


def loaded_save_ram() -> dict[int, int]:
    """A running game with a save loaded: the vanilla and RR SB1 pointers validate.

    The AP pointer is deliberately left unset - it is checked first, so making it
    validate would shadow every other leg (that is its own test, below).
    """
    ram: dict[int, int] = {}
    ram.update(sb1(VANILLA_SB1_PTR, VANILLA_SB1))
    ram.update(sb1(RR_SB1_PTR, RR_SB1))
    return ram


def synthetic_ram(rom_word: int) -> dict[int, int]:
    """`loaded_save_ram` plus a version string and a CFRU word, for ROM-file-less cases."""
    ram = loaded_save_ram()
    ram.update({ROM_BASE + VERSION_STR_OFF + i: b for i, b in enumerate(VERSION_STR)})
    ram.update(le(CFRU_PTR_ADDR, rom_word, 4))
    return ram


class Probe:
    """gen3_frlge.lua loaded over a fake `memory`: ROM bytes first, then sparse RAM."""

    def __init__(self, rom: bytes = b"", ram: dict[int, int] | None = None,
                 unreadable: tuple[int, ...] = ()):
        self.rom = rom
        self.unreadable = set(unreadable)
        self.ram = dict(ram or {})
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.read = self._read
        self.lua.execute("""
            memory = {
                read_u8     = function(a, d) return read(a, 1) end,
                read_u16_le = function(a, d) return read(a, 2) end,
                read_u32_le = function(a, d) return read(a, 4) end,
            }
        """)
        self.gen3 = self.lua.execute(SOURCE)

    def _byte(self, addr: int) -> int:
        if addr in self.unreadable:
            raise ValueError(f"unreadable at {addr:#010x}")
        offset = addr - ROM_BASE
        if 0 <= offset < len(self.rom):
            return self.rom[offset]
        return self.ram.get(addr, 0)

    def _read(self, addr: int, width: int) -> int:
        return sum(self._byte(addr + i) << (8 * i) for i in range(width))

    def variant(self) -> str:
        return self.gen3.detect_variant()


def rom_bytes(pack: str, title: str, kind: str) -> bytes | None:
    path, _sha1 = G.ROMS[(pack, title, kind)]
    return path.read_bytes() if path.exists() else None


# ── synthetic memory ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", [0x08FFFFFC, VANILLA_WORDS["firered"], VANILLA_WORDS["leafgreen"],
                                  0x0A000000])
def test_a_16mb_image_word_is_never_radical_red(word):
    """RAM looks RR-plausible, the ROM word does not: the ROM word must decide."""
    assert Probe(ram=synthetic_ram(word)).variant() == "vanilla"


@pytest.mark.parametrize("word", [CFRU_MIN, CFRU_WORD, CFRU_MAX - 4])
def test_an_expanded_image_word_is_radical_red(word):
    assert Probe(ram=synthetic_ram(word)).variant() == "radical_red"


def test_cfru_word_decides_before_any_save_is_loaded():
    """RR at the title screen: no SB1 pointer validates, the ROM word still identifies it."""
    ram = {ROM_BASE + VERSION_STR_OFF + i: b for i, b in enumerate(VERSION_STR)}
    ram.update(le(CFRU_PTR_ADDR, CFRU_WORD, 4))
    assert Probe(ram=ram).variant() == "radical_red"


def test_cfru_word_beats_a_validating_vanilla_pointer():
    # `synthetic_ram` already validates the vanilla pointer: RAM cannot veto the ROM word.
    assert Probe(ram=synthetic_ram(CFRU_WORD)).variant() == "radical_red"


def test_ap_pointer_keeps_its_priority():
    ram = synthetic_ram(CFRU_WORD)
    ram.update(sb1(AP_SB1_PTR, AP_SB1))
    assert Probe(ram=ram).variant() == "ap"


def test_unreadable_signature_fails_closed():
    p = Probe(ram=synthetic_ram(VANILLA_WORDS["firered"]), unreadable=(CFRU_PTR_ADDR,))
    assert p.variant() == "vanilla"  # no raise, and never radical_red from a missing read


def test_emerald_game_code_is_unchanged():
    ram = {ROM_BASE + 0xAC + i: b for i, b in enumerate(b"BPEE")}
    assert Probe(ram=ram).variant() == "emerald"


def test_an_rr_plausible_ram_map_cannot_promote_a_16mb_image():
    """The RAM probe alone used to return radical_red for exactly this memory."""
    ram = synthetic_ram(VANILLA_WORDS["firered"])
    ram[RR_SB1 + 0x34] = 3                       # party count 0-6
    ram.update(le(RR_SB1 + 0x38, 0x12345678, 4))  # first mon: non-zero personality
    ram.update(le(RR_SB1 + 0x38 + 0x58, 44, 2))   # and plausible maxHP
    assert Probe(ram=ram).variant() == "vanilla"


# ── the real dumps ─────────────────────────────────────────────────────────────

REAL_ROMS = [
    ("gen3_frlg", "firered", "clean", False),
    ("gen3_frlg", "leafgreen", "clean", False),
    ("gen3_rr", "radical_red", "clean", True),
    ("gen3_rr", "radical_red", "companion", True),
]


@pytest.mark.parametrize("pack,title,kind,is_cfru", REAL_ROMS)
def test_real_rom_signature(pack, title, kind, is_cfru):
    rom = rom_bytes(pack, title, kind)
    if rom is None:
        pytest.skip(f"{pack}/{title}/{kind} not present on this host")
    word = int.from_bytes(rom[WORD_OFF:WORD_OFF + 4], "little")
    assert (CFRU_MIN <= word < CFRU_MAX) is is_cfru, f"{title}/{kind}: word {word:#010x}"
    if not is_cfru:
        # The old probe matched this range, which is why vanilla FR was radical_red.
        assert 0x08000000 <= word < CFRU_MIN
        assert word == VANILLA_WORDS[title]


@pytest.mark.parametrize("pack,title,kind,is_cfru", REAL_ROMS)
def test_real_rom_detection(pack, title, kind, is_cfru):
    rom = rom_bytes(pack, title, kind)
    if rom is None:
        pytest.skip(f"{pack}/{title}/{kind} not present on this host")
    ram = loaded_save_ram()  # a running game with a save loaded
    got = Probe(rom=rom, ram=ram).variant()
    if is_cfru:
        assert got == "radical_red", f"{title}/{kind}: {got}"
    else:
        # Not radical_red is the regression contract; `vanilla` is what a loaded
        # save produces (the SB1 pointer validates).  With RAM uninitialised the
        # detector keeps its historical "ap" fallback - asserted, not blessed.
        assert got == "vanilla", f"{title}/{kind}: {got}"
        assert Probe(rom=rom).variant() in ("vanilla", "ap")
