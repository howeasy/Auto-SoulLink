"""lua/gen1/rom.lua's pure fishing walkers vs server/adapters/gen1_rom_scan.py's own scan.

Mirrors tests/unit/test_gen1_rom_tables.py::test_lua_raw_tables_match_python_scanner, but on
a built PureRed ROM: the same `rom_content()` function (shared by both foundations, P3b) has
to detect a pureRGB profile (`rom.GoodRodMonsOcean` present) and read pureRGB's own fishing
shapes -- ItemUseOldRod's two `lb bc, LEVEL, SPECIES` immediates (a 50/50 Magikarp/Goldeen
roll, not vanilla's one fixed species), and GoodRodMons/GoodRodMonsOcean's two back-to-back
(level, species) tables -- instead of silently asserting vanilla's shapes and failing inside
its own caller's pcall (the bug this whole card exists to fix: `hello.rom_content` came back
nil on a pure ROM).

Skips whole when SLINK_PURERGB_SRC is unset (no built ROM to read); vanilla's own
test_gen1_rom_content.py must stay green regardless, since this file never touches its ROMs
or its assertions.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 ROM reader")

from server.adapters import gen1_rom_scan as scan  # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
# The pinned checkout: $SLINK_PURERGB_SRC, else tools/gen1_foundation.py's default .cache/purergb.
_SRC = os.environ.get("SLINK_PURERGB_SRC") or os.path.join(REPO, ".cache", "purergb")
if not os.path.isdir(_SRC):
    pytest.skip(f"pureRGB checkout not found at {_SRC} (set SLINK_PURERGB_SRC)", allow_module_level=True)

_ROM_PATH = os.path.join(_SRC, "pokered.gbc")
if not os.path.isfile(_ROM_PATH):
    pytest.skip(f"{_ROM_PATH} not present", allow_module_level=True)

with open(os.path.join(REPO, "data", "games", "gen1_purergb", "profile.json"),
          encoding="utf-8") as _f:
    _PROFILE = json.load(_f)["titles"]["purered"]


def _rom() -> bytes:
    with open(_ROM_PATH, "rb") as f:
        return f.read()


def _lua_rom_content(rom: bytes) -> dict:
    """Run lua/gen1/rom.lua's rom_content() against the built PureRed ROM, outside BizHawk."""
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)

    def read_u8(addr, domain=None):
        # Same guard as the vanilla test: a regression to System Bus reads must fail loudly.
        assert domain == "ROM", f"read from domain {domain!r}, expected the flat ROM domain"
        if not 0 <= addr < len(rom):
            raise IndexError(addr)
        return rom[int(addr)]

    rom_lua = os.path.join(REPO, "lua", "gen1", "rom.lua").replace("\\", "/")
    json_lua = os.path.join(REPO, "lua", "json_codec.lua").replace("\\", "/")
    module = rt.eval(f'dofile("{rom_lua}")')
    codec_lua = rt.eval(f'dofile("{json_lua}")')
    reader = module.new(rt.table_from(_PROFILE, recursive=True), rt.table(read_u8=read_u8))
    return json.loads(str(codec_lua.encode(reader.rom_content())))


def test_pure_rom_content_declares_the_ocean_table():
    """The presence of this key IS the foundation switch rom.lua reads (docstring above)."""
    payload = _lua_rom_content(_rom())
    assert payload["variant"] == "purered"
    assert "good_rod_ocean" in payload
    assert payload["old_rod"], "pureRGB's Old Rod payload must not be empty"


def test_pure_old_rod_is_two_entries_not_one():
    """The exact defect this card exists to fix: rom.lua asserted vanilla's ItemUseOldRod+6
    shape unconditionally, so on a pure ROM the opcode assertion failed inside rom_content's
    caller's pcall and hello.rom_content came back nil."""
    rom = _rom()
    parsed = scan.parse_client_content(_lua_rom_content(rom))
    assert len(parsed["fishing"]["old_rod"]) == 2
    species = {e["species_index"] for e in parsed["fishing"]["old_rod"]}
    assert len(species) == 2, "50/50 Magikarp/Goldeen roll must name two distinct species"


def test_pure_good_rod_tables_have_no_terminator_leaked_onto_the_wire():
    """A stray FF,FF forwarded as a pair would read back as species 255 with no validation
    catching it (old_rod/good_rod carry no per-entry range check, unlike super_rod)."""
    rom = _rom()
    parsed = scan.parse_client_content(_lua_rom_content(rom))
    for key in ("good_rod", "good_rod_ocean"):
        entries = parsed["fishing"][key]
        assert len(entries) == 4, f"{key}: expected pureRGB's four fixed pairs, got {entries}"
        assert all(e["species_index"] != 255 for e in entries), f"{key}: terminator leaked"


def test_lua_rom_content_matches_the_python_scanner():
    """The end-to-end proof: everything rom_content() reports, parsed the way the server
    parses an untrusted client payload, equals what the server's own trusted ROM scan sees."""
    rom = _rom()
    payload = _lua_rom_content(rom)
    parsed = scan.parse_client_content(payload)
    assert parsed["variant"] == scan.identify(rom)["variant"] == "purered"
    assert parsed["wild"] == scan.scan_wild(rom)
    assert parsed["fishing"] == scan.scan_fishing(rom)


def test_lua_rom_content_fingerprint_matches_the_rom():
    """The wire contract's whole purpose: the client's report and a direct ROM read must
    fingerprint identically, or the server could show a player a ROM they are not playing."""
    rom = _rom()
    parsed = scan.parse_client_content(_lua_rom_content(rom))
    assert scan.content_fingerprint(parsed["variant"], parsed["wild"], parsed["fishing"]) == (
        scan.fingerprint_rom(rom))


def test_vanilla_old_rod_shape_is_unaffected():
    """rom.lua's foundation switch (rom.GoodRodMonsOcean presence) must never fire for
    vanilla: guards against the two code paths bleeding into each other."""
    with open(os.path.join(REPO, "data", "games", "gen1_rby", "profile.json"),
              encoding="utf-8") as f:
        vanilla_profile = json.load(f)["titles"]["red"]
    assert "GoodRodMonsOcean" not in vanilla_profile["rom"]
