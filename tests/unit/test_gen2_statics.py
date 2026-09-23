"""Pinned scripted battle inventory and byte witness refusal controls."""
from dataclasses import replace

import pytest

from tools import gen_gen2_statics as generator
from tools.gen2_source_data import load_context


@pytest.fixture(scope="module")
def contexts():
    return {title: load_context(title) for title in ("crystal", "gold", "silver")}


@pytest.fixture(scope="module")
def packs(contexts):
    return {title: generator.build(ctx) for title, ctx in contexts.items()}


def test_tutorials_traps_unused_and_selected_version_levels(packs):
    for title, pack in packs.items():
        rows = pack["encounters"]
        assert len(rows) == (17 if title == "crystal" else 18)
        assert len([row for row in rows if row["kind"] == "tutorial"]) == 3
        assert len([row for row in rows if row["kind"] == "scripted_trap_battle"]) == 3
        selected = [row for row in rows if row["applicability"]["selected"]]
        hooh = [row["level"] for row in selected if row["species"] == 250]
        lugia = [row["level"] for row in selected if row["species"] == 249]
        assert hooh == [{"crystal": 60, "gold": 40, "silver": 70}[title]]
        assert lugia == [{"crystal": 60, "gold": 70, "silver": 40}[title]]
        assert all(row["capture_success"] == "OPEN" and row["finalization"] == "OPEN" for row in rows)
        if title != "crystal":
            unused = [row for row in rows if row["source_unused"]]
            assert [(row["species"], row["level"]) for row in unused] == [(244, 40)]


def test_known_static_byte_divergence_refuses(contexts, packs):
    ctx = contexts["crystal"]
    row = next(row for row in packs["crystal"]["encounters"] if row["species"] == 251)
    rom = bytearray(ctx.rom)
    rom[row["rom"]["flat"] + 1] ^= 1
    with pytest.raises(ValueError, match="witness missing"):
        generator.build(replace(ctx, rom=bytes(rom)))


def test_missing_script_symbol_refuses(contexts):
    ctx = contexts["crystal"]
    symbols = dict(ctx.symbols)
    del symbols["RedGyarados"]
    with pytest.raises(ValueError, match="missing script symbol"):
        generator.build(replace(ctx, symbols=symbols))


def test_crystal_tin_tower_suicune_is_a_legend_not_a_tin_tower_capture(packs):
    """O-21 (docs/gen2/REVIEW_RECORD.md), SOURCE classification only: the Tin Tower Suicune static is
    legend_245 like the Gold/Silver roaming Suicune, and never claims the
    ordinary tin_tower map area for its capture."""
    row = next(r for r in packs["crystal"]["encounters"] if r["species"] == 245)
    assert row["script"] == "TinTower1FSuicuneBattleScript.Next2"
    assert row["map_name"] == "TinTower1F"  # source map identity is retained
    assert row["area_id"] == "legend_245"
    for title in ("gold", "silver"):
        assert all(r["species"] != 245 for r in packs[title]["encounters"])


def test_check_never_repairs_malformed_output(tmp_path, monkeypatch, packs):
    from tools import gen_gen2_charmap as common

    monkeypatch.setattr(common, "load_context", lambda title, root: title)
    monkeypatch.setattr(generator, "build", lambda title: packs[title])
    argv = ["--root", str(tmp_path)]
    assert generator.main(argv) == 0
    assert generator.main([*argv, "--check"]) == 0
    path = tmp_path / "data/games/gen2_gold/static_encounters.json"
    path.write_bytes(b"{}\n")
    before = path.stat().st_mtime_ns
    assert generator.main([*argv, "--check"]) == 1
    assert path.read_bytes() == b"{}\n" and path.stat().st_mtime_ns == before


def test_runtime_battle_type_is_resolved_per_row(packs, monkeypatch, contexts):
    """N12b: loadvar, catchtutorial or the verified Celebi asm special; else NORMAL."""
    for title, pack in packs.items():
        types = {row["species"]: row["runtime_battle_type"] for row in pack["encounters"]}
        assert {s: types[s] for s in (130, 19, 185, 100, 101, 250, 131, 143, 249)} == {
            130: 7, 19: 3, 185: 0, 100: 9, 101: 0, 250: 10, 131: 0, 143: 10, 249: 10}
        if title == "crystal":
            assert (types[251], types[245]) == (11, 12)
        else:
            assert types[244] == 0
    monkeypatch.setitem(generator.ASM_BATTLE_TYPES, "CelebiShrineEvent",
                        ("engine/events/celebi.asm", "CheckCaughtCelebi"))
    with pytest.raises(ValueError, match="unverified battle-type special"):
        generator.build(contexts["crystal"])
