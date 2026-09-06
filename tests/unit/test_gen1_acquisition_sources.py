"""Source census controls, independent of later transaction/predicate qualification."""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
try:
    spec = importlib.util.spec_from_file_location("acquisition_census", ROOT / "tools/gen_gen1_acquisition_sources.py")
    census = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(census)
finally:
    sys.path.pop(0)


@pytest.fixture(scope="module")
def data():
    return census.build()


def test_generated_census_is_current_and_does_not_claim_runtime_readiness(data):
    assert data == json.loads(census.OUTPUT.read_text())
    assert data["runtime_ready"] is False
    body = {key: value for key, value in data.items() if key != "content_sha256"}
    assert census.digest(body) == data["content_sha256"]


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
def test_every_source_is_unique_and_only_four_acquisition_classes_are_used(data, title):
    rows = data["titles"][title]["sources"]
    assert len({row["source_id"] for row in rows}) == len(rows)
    expected = {"scripted_grant": 11 if title == "yellow" else 8, "catchable_static": 14,
                "npc_exchange": 7 if title == "yellow" else 9,
                "uncatchable_script_battle": 4 if title == "yellow" else 3}
    assert dict(Counter(row["kind"] for row in rows)) == expected


def test_blue_fossil_call_uses_its_own_compiled_address(data):
    def fossil(title):
        return next(row for row in data["titles"][title]["sources"] if row["source_id"] == "grant:fossil_revival:0")
    assert fossil("red")["call"]["rom_offset"] == 0x75DB6
    assert fossil("blue")["call"]["rom_offset"] == 0x75DB7
    assert fossil("yellow")["call"]["rom_offset"] == 0x75631


@pytest.mark.parametrize("title", ["red", "blue", "yellow"])
def test_snorlax_is_scripted_static_and_ghost_marowak_is_never_catchable(data, title):
    rows = {row["source_id"]: row for row in data["titles"][title]["sources"]}
    for route in (12, 16):
        row = rows[f"static:route{route}_snorlax"]
        assert row["kind"] == "catchable_static" and row["species_index"] == 0x84
        assert row["expected_assignment_hex"].startswith("3e84ea")
    ghost = rows["script-battle:ghost-marowak"]
    assert ghost["kind"] == "uncatchable_script_battle"
    assert "script-battle:ghost-marowak" in rows["script-battle:unidentified-tower-ghost"]["exclude_source_ids"]


def test_yellow_only_handouts_and_unreachable_trade_rows_are_explicit(data):
    for title, counts in (("red", (0, 1)), ("blue", (0, 1)), ("yellow", (3, 3))):
        profile = data["titles"][title]
        assert sum(bool(row.get("yellow_only")) for row in profile["sources"]) == counts[0]
        assert len(profile["unused_trade_rows"]) == counts[1]
        used = {row["trade_index"] for row in profile["sources"] if row["kind"] == "npc_exchange"}
        unused = {row["index"] for row in profile["unused_trade_rows"]}
        assert used.isdisjoint(unused) and used | unused == set(range(10))


@pytest.mark.parametrize("corruption", ["target-byte", "ambiguous-call"])
def test_instruction_lookup_requires_one_exact_call_within_the_source_scope(tmp_path, corruption):
    file = tmp_path / "grant.asm"
    file.write_text("Start:\n call GivePokemon\nAfter:\n ret\n")
    syms = {"Start": (2, 0x4000), "After": (2, 0x4008), "GivePokemon": (0, 0x1234)}
    rom = bytearray(0xC000)
    rom[0x8000:0x8003] = b"\xcd\x34\x12"
    assert census.call_sites(file, syms, rom)[0]["call"]["rom_offset"] == 0x8000
    if corruption == "target-byte":
        rom[0x8001] ^= 1
    else:
        rom[0x8003:0x8006] = b"\xcd\x34\x12"
    with pytest.raises(ValueError, match="missing/ambiguous"):
        census.call_sites(file, syms, rom)
