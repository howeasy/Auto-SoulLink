"""F-4/F-5 (two-path): lua/gen1/rom.lua reads dex order and base stats from the cartridge; the
Python scanner (gen1_rom_scan) reads the same tables its own way. They must agree on every
species, on all three titles.
"""
from __future__ import annotations

import copy
import json
import pathlib

import lupa
import pytest

from server.adapters import gen1_codec as codec, gen1_rom_scan as scan

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILE = json.loads((REPO / "data" / "games" / "gen1_rby" / "profile.json").read_text(encoding="utf-8"))["titles"]
ROM_LUA = (REPO / "lua" / "gen1" / "rom.lua").as_posix()
DUMPS = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}


def _rom_bytes(title: str) -> bytes:
    path = REPO / "patch" / "build" / DUMPS[title]
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    return path.read_bytes()


def _lua_rom(title: str, rom: bytes):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    io = lua.table(read_u8=lambda addr, domain: rom[int(addr)])
    R = lua.eval(f'dofile("{ROM_LUA}")')
    return R.new(lua.table_from(PROFILE[title], recursive=True), io)


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_dex_order_matches_the_codec_table(title):
    """The codec's dex table came from pret source; the Lua reads the ROM. Same 190 answers."""
    rom = _rom_bytes(title)
    r = _lua_rom(title, rom)
    for internal in range(1, 191):
        py = codec.internal_to_natdex(internal) or None  # 0 = MissingNo. hole in the codec table
        got = r.natdex(internal)
        assert (got if isinstance(got, int) else None) == py, (title, internal, got, py)


@pytest.mark.parametrize("title", sorted(DUMPS))
def test_base_stats_match_the_python_scanner_for_every_dex(title):
    rom = _rom_bytes(title)
    r = _lua_rom(title, rom)
    table = scan.scan_base_stats(rom)
    assert set(table) == set(range(1, 152))
    for dex, entry in table.items():
        got = r.base_stats(dex)
        assert got is not None, (title, dex)
        for field in ("hp", "attack", "defense", "speed", "special", "growth_rate"):
            assert got[field] == entry[field], (title, dex, field)
    assert r.base_stats(0)[0] is None and r.base_stats(152)[0] is None


def test_base_stats_for_an_internal_index_goes_through_dex_order():
    rom = _rom_bytes("red")
    r = _lua_rom("red", rom)
    # internal 0x99 is Bulbasaur (dex 1) in Gen 1's scrambled order
    assert codec.internal_to_natdex(0x99) == 1
    assert r.base_stats_for(0x99)["dex"] == 1
    assert r.base_stats_for(0xBE)[0] is None  # MissingNo. hole: no dex entry


def _lua_content(title: str) -> tuple[bytes, dict]:
    rom = _rom_bytes(title)
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = runtime.eval(f'dofile("{(REPO / "lua/gen1/rom.lua").as_posix()}")')
    json_codec = runtime.eval(f'dofile("{(REPO / "lua/json_codec.lua").as_posix()}")')

    def read_u8(offset: int, domain: str) -> int:
        assert domain == "ROM"
        return rom[int(offset)]

    profile = runtime.table_from(PROFILE[title], recursive=True)
    reader = module.new(profile, runtime.table(read_u8=read_u8))
    return rom, json.loads(str(json_codec.encode(reader.rom_content())))


@pytest.mark.parametrize("title", DUMPS)
def test_lua_raw_tables_match_python_scanner(title: str) -> None:
    rom, payload = _lua_content(title)
    parsed = scan.parse_client_content(payload)
    assert parsed["variant"] == scan.identify(rom)["variant"]
    # Both source trees include map IDs with no wild encounters. The actual populated
    # count on the three pinned dumps is 57 (scan_wild; the card estimated 59).
    assert len(parsed["wild"]) == len(scan.scan_wild(rom)) == 57
    assert parsed["wild"] == scan.scan_wild(rom)
    assert parsed["fishing"] == scan.scan_fishing(rom)
    assert scan.content_fingerprint(parsed["variant"], parsed["wild"], parsed["fishing"]) == (
        scan.fingerprint_rom(rom)
    )


def test_one_wild_slot_byte_corruption_breaks_fingerprint() -> None:
    rom, payload = _lua_content("red")
    changed = copy.deepcopy(payload)
    map_id = min(changed["wild"], key=int)
    record = bytearray.fromhex(changed["wild"][map_id])
    # A nonzero grass rate starts the first (level, species) slot at byte 1;
    # otherwise the water rate is byte 1 and its first level is byte 2.
    level_at = 1 if record[0] else 2
    record[level_at] = 1 if record[level_at] != 1 else 2
    changed["wild"][map_id] = record.hex()
    parsed = scan.parse_client_content(changed)
    assert scan.content_fingerprint(parsed["variant"], parsed["wild"], parsed["fishing"]) != (
        scan.fingerprint_rom(rom)
    )


def test_hello_carries_matching_rom_content() -> None:
    from tests.unit.test_gen1_client import World

    world = World("red")
    mon = codec.decode_party_mon(bytes(44))
    mon.update(species=0x99, level=5, hp=20, max_hp=20)
    world.seed_party([mon])
    world.set_map(0x0C)
    world.connect()
    world.step(60)
    hello = world.events("hello")[0]
    parsed = scan.parse_client_content(hello["rom_content"])
    assert scan.content_fingerprint(parsed["variant"], parsed["wild"], parsed["fishing"]) == (
        scan.fingerprint_rom(world.rom)
    )
    world.assert_all_conform()
