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
    map_constants,
    rom_bytes,
    run_generator,
    source_lines,
)


@pytest.mark.parametrize("script", ["area_map", "statics", "gifts"])
def test_direct_generator_cli_check_without_pythonpath(script):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-E", str(root / "tools" / f"gen_gen2_{script}.py"), "--check"],
        cwd=root, env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def context(request):
    # Required build inputs: absence is a failure, never a skipped qualification.
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
