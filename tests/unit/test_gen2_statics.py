"""Pinned scripted battle inventory and byte witness refusal controls."""
import re
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
    assert row["static_area_id"] == "legend_245"  # what the client publishes (O-16/O-21)
    for title in ("gold", "silver"):
        assert all(r["species"] != 245 for r in packs[title]["encounters"])


# ── gen2-static-canon (O-16, docs/gen2/RESUME.md:61): the id is pack-owned ──────────────────

STATIC_ID = re.compile(r"static_[a-z][a-z0-9_]*_([1-9][0-9]{0,2})\Z")


def test_static_area_ids_are_canonical_and_title_independent(packs):
    """The same static in Crystal, Gold and Silver is ONE id: the Union Cave B2F Lapras was
    static_807_131 (Crystal, map 03:39) beside static_799_131 (Gold, 03:31) -- keyed by the
    lowercase MAP CONSTANT now, never by group*256+number, so a cross-title pair links there."""
    lapras = {title: next(row["static_area_id"] for row in pack["encounters"]
                          if row["script"] == "UnionCaveLapras")
              for title, pack in packs.items()}
    assert set(lapras.values()) == {"static_union_cave_b2f_131"}, lapras
    # One id, one (map_name, species) across the whole title matrix: a shared id IS the same
    # encounter, and the pack's duplicate script rows are the same site, never two.
    owners = {}
    for title, pack in packs.items():
        for row in pack["encounters"]:
            if row["applicability"]["selected"] and not row["source_unused"]:
                owners.setdefault(row["static_area_id"], set()).add((row["map_name"], row["species"]))
    assert all(len(sites) == 1 for sites in owners.values()), owners
    shared = set.intersection(*[{row["static_area_id"] for row in pack["encounters"]}
                                for pack in packs.values()])
    assert {"static_union_cave_b2f_131", "static_route_36_185", "static_lake_of_rage_130",
            "static_vermilion_city_143", "static_tin_tower_roof_250",
            "static_whirl_island_lugia_chamber_249"} <= shared, shared


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_canonical_id_shape_and_species_suffix(packs, title):
    """static_<lowercase map constant>_<species>, or the row's own legend_<species>."""
    for row in packs[title]["encounters"]:
        canonical = row["static_area_id"]
        if canonical.startswith("legend_"):
            assert canonical == f"legend_{row['species']}", canonical
            continue
        match = STATIC_ID.fullmatch(canonical)
        assert match is not None and int(match[1]) == row["species"], (title, canonical)


def test_a_title_only_static_keeps_a_unique_id(packs):
    """Rows only one title carries stay unique and never appear on a pack without them:
    Crystal's Tin Tower Suicune (legend_245) and Ilex Forest Celebi, the G/S Burned Tower
    Entei (whose row is source_unused there anyway)."""
    by_title = {title: {row["static_area_id"] for row in pack["encounters"]}
                for title, pack in packs.items()}
    assert {"legend_245", "static_ilex_forest_251"} <= by_title["crystal"]
    assert not ({"legend_245", "static_ilex_forest_251"} & (by_title["gold"] | by_title["silver"]))
    assert "static_burned_tower_b1f_244" in by_title["gold"] | by_title["silver"]
    assert "static_burned_tower_b1f_244" not in by_title["crystal"]


def test_a_map_constant_that_is_not_a_plain_name_refuses(contexts, monkeypatch):
    """The id is the lowercased constant, so a constant that is not a plain name has no id to
    publish -- refused, never lowercased into something plausible."""
    maps = generator.build_area_map(contexts["crystal"])
    location = next(row for row in maps.values() if row["map_name"] == "UnionCaveB2F")
    location["map_const"] = "union_cave_b2f"
    monkeypatch.setattr(generator, "build_area_map", lambda ctx: maps)
    with pytest.raises(ValueError, match="plain name"):
        generator.build(contexts["crystal"])


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
