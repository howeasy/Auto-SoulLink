"""The client's ROM reader and the server's parser must agree, byte for byte.

There are two readers of the same tables: `M.readRomContent` in lua/games/gen1_rby.lua,
which runs inside BizHawk against the cartridge being played, and
server/adapters/gen1_rom_scan.py, which reads a ROM file. If they ever disagree the server
renders something the player is not playing -- which is the exact failure this whole phase
exists to prevent.

So the Lua is executed here, under lupa, with a fake `memory` domain backed by a REAL ROM,
and its output is compared against the Python scan of the same bytes. No emulator needed.

The division of labour is deliberate and is what these tests pin: Lua follows pointers and
ships RAW HEX; it never interprets a record. Every layout rule -- ten slots per method, a
block present only when its rate is non-zero, Yellow's reversed super-rod fields -- lives in
Python, so there is one parser rather than two that can drift.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 game module")

from server.adapters import get_adapter
from server.adapters.gen1_rom_scan import (
    RomScanError, build_encounter_tables, parse_client_content, scan_fishing, scan_wild,
)

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_ROMS = {
    "red": os.path.join(_REPO, "patch", "build", "gen1_red.gb"),
    "blue": os.path.join(_REPO, "patch", "build", "gen1_blue.gb"),
    "yellow": os.path.join(_REPO, "patch", "build", "gen1_yellow.gbc"),
}
TITLES = ("red", "blue", "yellow")


def _rom(title: str) -> bytes:
    path = _ROMS[title]
    if not os.path.exists(path):
        pytest.skip(f"{path} not present")
    with open(path, "rb") as f:
        return f.read()


def _lua_rom_content(title: str) -> dict:
    """Run M.readRomContent(variant) against a real ROM, outside BizHawk."""
    rom = _rom(title)
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()

    def read_u8(addr, domain=None):
        # The reader must use the FLAT "ROM" domain. Refusing anything else here is what
        # makes a regression to System Bus reads (where 0x4000-0x7FFF is a bank window)
        # fail loudly instead of returning plausible nonsense.
        assert domain == "ROM", f"read from domain {domain!r}, expected the flat ROM domain"
        if not 0 <= addr < len(rom):
            raise IndexError(addr)
        return rom[addr]

    g.memory = rt.table_from({
        "getmemorydomainlist": lambda: rt.table_from(["ROM"]),
        "read_u8": read_u8,
    })
    g.console = rt.table_from({"log": lambda *_a: None})
    g.SLINK_ROOT = _REPO

    with open(os.path.join(_REPO, "lua", "games", "gen1_rby.lua"), encoding="utf-8") as f:
        module = rt.execute(f.read())
    out = module.readRomContent(title)
    assert out is not None, f"readRomContent returned nil for {title}"

    def to_dict(tbl):
        return {str(k): v for k, v in tbl.items()}

    return {
        "variant": out["variant"],
        "wild": to_dict(out["wild"]),
        "old_rod": out["old_rod"],
        "good_rod": out["good_rod"],
        "super_rod": to_dict(out["super_rod"]),
    }


# ── the two readers agree ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_lua_and_python_read_the_same_wild_tables(title):
    rom = _rom(title)
    got = parse_client_content(_lua_rom_content(title))
    assert got["wild"] == scan_wild(rom), (
        f"{title}: the client's wild tables differ from the file scan")


@pytest.mark.parametrize("title", TITLES)
def test_lua_and_python_read_the_same_fishing_tables(title):
    rom = _rom(title)
    got = parse_client_content(_lua_rom_content(title))["fishing"]
    want = scan_fishing(rom)
    assert got["old_rod"] == want["old_rod"]
    assert got["good_rod"] == want["good_rod"]
    assert got["super_rod"] == want["super_rod"], (
        f"{title}: super rod differs — Yellow stores (species, level) and R/B "
        f"(level, species), so a swapped read stays in range and only a value check finds it")


@pytest.mark.parametrize("title", TITLES)
def test_the_payload_is_a_realistic_size_for_one_line(title):
    """It travels as one newline-delimited JSON line, so its size is a design constraint."""
    payload = json.dumps(_lua_rom_content(title))
    assert len(payload) < 32 * 1024, f"{title} rom_content is {len(payload)} bytes"
    assert len(payload) > 2 * 1024, f"{title} rom_content is only {len(payload)} bytes"


# ── what the UI is given ─────────────────────────────────────────────────────────────────
def _tables_from_rom(title: str) -> dict:
    rom = _rom(title)
    area_map = json.load(open(os.path.join(
        _REPO, "data", "games", "gen1_rby", "area_map.json"), encoding="utf-8"))
    species = json.load(open(os.path.join(
        _REPO, "data", "games", "gen1_rby", "species_index.json"), encoding="utf-8"))
    adapter = get_adapter("gen1_rby", rom_type=title.capitalize())
    return build_encounter_tables(
        {"wild": scan_wild(rom), "fishing": scan_fishing(rom)},
        {int(k): v["area_id"] for k, v in area_map.items()},
        {int(k): v for k, v in species["index_to_national"].items()},
        adapter.species_name)


def _shipped(title: str) -> dict:
    with open(os.path.join(_REPO, "data", "games", "gen1_rby",
                           "encounter_tables.json"), encoding="utf-8") as f:
        return json.load(f)[title]


def _strip_names(tables: dict) -> dict:
    return {a: {m: [{k: v for k, v in e.items() if k != "name"} for e in es]
                for m, es in b.items()}
            for a, b in tables.items()}


@pytest.mark.parametrize("title", TITLES)
def test_a_clean_rom_reproduces_the_shipped_tables(title):
    """The known-positive control: vanilla in, the tables SLink already ships out.

    Compared without `name` for one reason, pinned separately below: the shipped file
    renders dex 83 as "Farfetchd" because tools/gen_gen1_encounters.py derives display names
    from pret's constant, while everything else in the UI asks the adapter and gets
    "Farfetch'd". Species, rate and level ranges must match exactly.
    """
    built = _tables_from_rom(title)
    shipped = _shipped(title)
    # `m.split(" ")[0]`, because a multi-floor dungeon's methods carry the floor:
    # "Grass B1F", "Water B4F". An exact-name filter dropped every such area, which made
    # this control quietly stop covering seven of them. Super Rod is still excluded --
    # the shipped file has no fishing at all, which the two tests below pin.
    grass_water = {a: {m: v for m, v in b.items() if m.split(" ")[0] in ("Grass", "Water")}
                   for a, b in built.items()}
    grass_water = {a: b for a, b in grass_water.items() if b}

    assert set(grass_water) == set(shipped), (
        f"{title}: areas differ — only built {sorted(set(grass_water) - set(shipped))}, "
        f"only shipped {sorted(set(shipped) - set(grass_water))}")
    stripped_built, stripped_shipped = _strip_names(grass_water), _strip_names(shipped)
    for area in sorted(shipped):
        for method in shipped[area]:
            assert stripped_built[area].get(method) == stripped_shipped[area][method], (
                f"{title}/{area}/{method} differs from the shipped table")


def test_names_come_from_the_adapter_not_the_generator():
    """Pins the one deliberate difference, so it is a decision rather than a surprise."""
    built = _tables_from_rom("yellow")
    names = {e["name"] for b in built.values() for es in b.values() for e in es
             if e["species_id"] == 83}
    assert names == {"Farfetch'd"}, f"got {names}"
    shipped_names = {e["name"] for b in _shipped("yellow").values()
                     for es in b.values() for e in es if e["species_id"] == 83}
    assert shipped_names == {"Farfetchd"}, (
        "the shipped file changed; this test exists to document that it disagrees")


def test_later_floors_are_no_longer_dropped():
    """This test used to assert that the SCANNER recovered a table the generator dropped.

    It does not need to any more: gen_gen1_encounters.py took the first MAP per area and
    skipped later floors whole, so twenty of the ROM's fifty-nine wild tables were
    unreachable — including Yellow's Seafoam surfing tables, which live on B3F and B4F while
    the first map has grass only. The generator now emits one method per floor, so the fix
    is at the source and both paths agree (which `test_a_clean_rom_reproduces_the_shipped_tables`
    checks in full).

    What is pinned here is the property that made it worth doing: a multi-floor dungeon
    exposes every floor, and a method that exists only on a later floor is present.
    """
    shipped = _shipped("yellow")["seafoam_islands"]
    floors = {m.split(" ", 1)[1] for m in shipped if " " in m}
    assert floors == {"1F", "B1F", "B2F", "B3F", "B4F"}, f"got {sorted(floors)}"
    assert any(m.startswith("Water") for m in shipped), (
        "the surfing table that only exists on a later floor is missing again")

    # And a single-map area keeps the plain, unsuffixed labels it always had.
    assert set(_shipped("yellow")["route_1"]) == {"Grass"}


@pytest.mark.parametrize("title", TITLES)
def test_percentages_sum_to_100_per_method(title):
    for area, block in _tables_from_rom(title).items():
        for method, entries in block.items():
            total = sum(e["rate"] for e in entries)
            assert total == 100, f"{title}/{area}/{method} sums to {total}"


def test_super_rod_is_added_where_the_shipped_tables_have_no_fishing_at_all():
    """The shipped file only ever carries Grass and Water, so fishing is invisible today."""
    assert all({m.split(" ")[0] for m in b} <= {"Grass", "Water"}
               for b in _shipped("red").values())
    built = _tables_from_rom("red")
    assert sum(1 for b in built.values() if "Super Rod" in b) > 10


# ── untrusted input ──────────────────────────────────────────────────────────────────────
def _good_payload() -> dict:
    return _lua_rom_content("red")


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p.update(variant="gold"), "unknown variant"),
    (lambda p: p.update(wild={}), "no wild tables"),
    (lambda p: p.update(wild={"12": "ZZ"}), "not valid hex"),
    # A rate byte with no slots behind it: the record is truncated, not empty.
    (lambda p: p.update(wild={"12": "19"}), "only 0 bytes remain"),
    (lambda p: p.update(wild={"12": ""}), "ran out of bytes"),
    (lambda p: p.update(wild={"999": "0000"}), "outside 0-255"),
    (lambda p: p.update(wild={"nope": "0000"}), "not a map id"),
    (lambda p: p.update(super_rod={"0": "00"}), "does not match"),
])
def test_a_malformed_payload_is_refused_rather_than_half_read(mutate, match):
    """A client is another process; its payload is untrusted input, not a given.

    Refusing matters more than it looks: the caller's correct response to a bad payload is
    to mark the encounter data UNAVAILABLE, never to fall back to the decomp tables, because
    vanilla species shown beside a randomized cartridge is the misinformation this exists
    to remove.
    """
    payload = _good_payload()
    mutate(payload)
    with pytest.raises(RomScanError, match=match):
        parse_client_content(payload)


def test_a_record_with_trailing_bytes_is_refused():
    payload = _good_payload()
    payload["wild"] = {"12": payload["wild"]["12"] + "00"}
    with pytest.raises(RomScanError, match="trailing bytes"):
        parse_client_content(payload)


def test_an_oversized_payload_is_refused():
    payload = _good_payload()
    payload["wild"] = {str(i): "0000" for i in range(600)}
    with pytest.raises(RomScanError, match="declares 600 maps"):
        parse_client_content(payload)
