"""Source/ROM area facts and refusal behavior; no emulator qualification."""
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import gen2_source_data
from tools.gen_gen2_area_map import (
    build_area_map,
    constants,
    fishing_water,
    map_constants,
    rom_bytes,
    run_generator,
    source_lines,
)


@pytest.mark.parametrize("script", ["area_map", "statics", "gifts"])
def test_direct_generator_cli_check_without_pythonpath(script):
    root = Path(__file__).resolve().parents[2]
    for repo in ("pokecrystal", "pokegold"):   # the generator needs both clones (tests/conftest.py)
        if not (root / ".cache/gen2-build" / repo).is_dir():
            pytest.skip(f"{repo} not cloned: {root / '.cache/gen2-build' / repo}")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-E", str(root / "tools" / f"gen_gen2_{script}.py"), "--check"],
        cwd=root, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def context(request):
    # Required build inputs. Absent clone -> the named skip (tests/conftest.py); the Gen 2 release gate
    # allows no skips (verify_gen2_release.ALLOWED_SKIPS == ()), so qualification still fails without it.
    return gen2_source_data.load_context(request.param)


def test_all_map_headers_are_bound_and_contest_is_separate(context):
    rows = build_area_map(context)
    assert len(rows) == (388 if context.title == "crystal" else 368)
    assert all(key == str(row["map_group"] * 256 + row["map_number"]) for key, row in rows.items())
    by_name = {row["map_const"]: row for row in rows.values()}
    assert by_name["NATIONAL_PARK"]["area_id"] == "national_park"
    assert by_name["NATIONAL_PARK_BUG_CONTEST"]["area_id"] == "national_park_contest"
    assert by_name["UNION_CAVE_1F"]["area_id"] == by_name["UNION_CAVE_B1F"]["area_id"] == "union_cave"
    assert all(row["source"]["commit"] == context.source_commit for row in rows.values())


def test_fishing_water_follows_the_accepted_rule(context):
    """F6 (docs/gen2/reviews/OMP_FISHING_ASSOCIATION_2026-09-22.md): a rod needs a water
    quadrant with a standable neighbour, so a header fish group alone is not enough."""
    rows = {row["map_const"]: row for row in build_area_map(context).values()}
    assert all(isinstance(row["fishing_water"], bool) for row in rows.values())
    # Water the rod can face from walkable ground, including an indoor cave (F7).
    assert all(rows[name]["fishing_water"] for name in ("NEW_BARK_TOWN", "ROUTE_32", "UNION_CAVE_1F"))
    # No water at all (ElmsLab, PlayersHouse1F) or water walled off from every standing
    # tile (Route 16's decorative pockets).
    assert not any(rows[name]["fishing_water"] for name in ("ELMS_LAB", "PLAYERS_HOUSE_1F", "ROUTE_16"))
    # Cerulean Gym is the documented pret bug: the pool is reachable, but only Gold/Silver
    # give the map a fish group (Crystal data/maps/maps.asm:218 vs Gold :210).
    assert rows["CERULEAN_GYM"]["fishing_water"] is True
    assert rows["CERULEAN_GYM"]["fishing_group"] == (0 if context.title == "crystal" else 1)


def test_fishing_water_rule_needs_a_standable_neighbour():
    """The rule is the engine's own: faced-tile permission, block 0 = wall, and a neighbour
    the player can occupy (home/map.asm:1591-1650, :1713-1716)."""
    names = {"COLL_FLOOR": 0x00, "LAND_TILE": 0x00, "WATER_TILE": 0x01, "COLL_PIT": 0x60,
             "HI_NYBBLE_LEDGES": 0xA0, "HI_NYBBLE_SIDE_WALLS": 0xB0, "HI_NYBBLE_SIDE_BUOYS": 0xC0}
    permissions = [0x00] * 256
    permissions[0x29] = 0x01  # COLL_WATER -> WATER_TILE (data/collision/collision_permissions.asm)
    permissions[0xB2] = 0x00  # COLL_UP_WALL keeps LAND_TILE but GetMovementPermissions refuses it
    permissions[0xA3] = 0x00  # COLL_HOP_DOWN likewise: a hop is never a standing tile
    water, floor = bytes([0x29] * 4), bytes(4)
    # metatile 0 unused, 1 all water, 2 all floor, 3 side wall, 4 hop ledge
    table = bytes(4) + water + floor + bytes([0xB2] * 4) + bytes([0xA3] * 4)
    assert fishing_water(b"\x01", 1, 1, table, permissions, names) is False      # nothing to stand on
    assert fishing_water(b"\x01\x02", 2, 1, table, permissions, names) is True   # floor beside water
    assert fishing_water(b"\x01\x03", 2, 1, table, permissions, names) is False  # side wall only
    assert fishing_water(b"\x01\x04", 2, 1, table, permissions, names) is False  # hop ledge only
    assert fishing_water(b"\x00\x01", 2, 1, table, permissions, names) is False  # block 0 is wall
    with pytest.raises(ValueError, match="outside the tileset collision table"):
        fishing_water(b"\x09\x01", 2, 1, table, permissions, names)


def test_collision_permission_table_is_cross_checked_against_the_rom(context):
    rom = bytearray(context.rom)
    offset = gen2_source_data.rom_offset(*context.symbol("CollisionPermissionTable"))
    rom[offset + 0x29] ^= 1  # COLL_WATER's permission byte
    with pytest.raises(ValueError, match="permission table differs"):
        build_area_map(replace(context, rom=bytes(rom)))


def test_header_landmark_byte_corruption_refuses(context):
    row = next(iter(build_area_map(context).values()))
    rom = bytearray(context.rom)
    rom[row["source"]["header_flat"] + 5] ^= 1
    with pytest.raises(ValueError, match="source/header ROM mismatch"):
        build_area_map(replace(context, rom=bytes(rom)))


def test_source_name_missing_refuses(context):
    original = context.read_source
    fake = SimpleNamespace(**vars(context), symbol=context.symbol)
    fake.read_source = lambda path: original(path).replace("NEW BARK<BSP>TOWN@", "BROKEN")
    with pytest.raises(ValueError, match="display names"):
        build_area_map(fake)


@pytest.mark.parametrize("text", [
    "newgroup TEST\nmap_const ONE, 10, 10\n",  # unterminated
    "newgroup TEST\nmap_const ONE, 0, 10\nendgroup\n",
    "newgroup TEST\nmap_const ONE, 10, 256\nendgroup\n",
    "newgroup TEST\nmap_const ONE, 10, 10\nmap_const ONE, 10, 10\nendgroup\n",
    "newgroup TEST\nendgroup\n",
])
def test_bad_map_constants_refuse(text):
    with pytest.raises(ValueError):
        map_constants(text, "crystal")


def test_unknown_and_unterminated_condition_refuse():
    for text in ("IF DEF(_OTHER)\nENDC", "IF DEF(_GOLD)\ndb 1"):
        with pytest.raises(ValueError):
            list(source_lines(text, "gold"))
    text = "IF DEF(_GOLD)\ndb 1\nELIF DEF(_SILVER)\ndb 2\nENDC"
    assert [line for _, line in source_lines(text, "gold")] == ["db 1"]
    assert [line for _, line in source_lines(text, "silver")] == ["db 2"]


def test_unresolved_named_constant_refuses():
    with pytest.raises(ValueError, match="unresolved"):
        constants("const_def UNKNOWN\nconst FISHGROUP_FAKE", "FISHGROUP_", "gold")


def test_rom_table_must_fit_bank_and_actual_rom():
    fake = SimpleNamespace(rom=bytes(0x8000), symbol=lambda _: gen2_source_data.Symbol(1, 0x7fff))
    with pytest.raises(ValueError, match="crosses ROM bank"):
        rom_bytes(fake, "Table", 2)
    fake.rom = b""
    with pytest.raises(ValueError, match="outside ROM"):
        rom_bytes(fake, "Table", 1)


def test_check_preserves_bytes_and_mtime_and_refuses_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(gen2_source_data, "load_context", lambda title, root: SimpleNamespace(title=title))
    def builder(ctx):
        return {"value": ctx.title}
    args = ["--root", str(tmp_path), "--title", "gold"]
    assert run_generator(args, "area_map.json", builder) == 0
    output = tmp_path / "data/games/gen2_gold/area_map.json"
    before = output.read_bytes(), output.stat().st_mtime_ns
    assert run_generator([*args, "--check"], "area_map.json", builder) == 0
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before
    output.write_bytes(b"stale\n")
    before = output.read_bytes(), output.stat().st_mtime_ns
    assert run_generator([*args, "--check"], "area_map.json", builder) == 1
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before


def test_all_titles_validate_before_any_output_changes(tmp_path, monkeypatch):
    def load(title, root):
        if title == "gold":
            raise ValueError("stale pinned ROM")
        return SimpleNamespace(title=title)

    monkeypatch.setattr(gen2_source_data, "load_context", load)
    output = tmp_path / "data/games/gen2_crystal/area_map.json"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"preserved")
    before = output.read_bytes(), output.stat().st_mtime_ns
    assert run_generator(["--root", str(tmp_path)], "area_map.json", lambda _: {}) == 1
    assert (output.read_bytes(), output.stat().st_mtime_ns) == before
